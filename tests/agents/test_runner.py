import asyncio
import os
import socket
from pathlib import Path

import pytest

from corvo.agents import runner
from corvo.agents.envelope import (
    ENVELOPE,
    AgentRequest,
    AgentRunFailed,
    Failed,
    RunReport,
    Succeeded,
)
from corvo.agents.fingerprint import fingerprint
from corvo.agents.tone import agent
from corvo.agents.tone.models import ToneInput, ToneOutput

REPORT = RunReport(
    subtype="success", num_turns=2, total_cost_usd=0.0042, session_id="s-1"
)


def request(
    run_dir: Path, agent: str = "tone", text: str = "Thanks!", budget: float = 5
) -> None:
    sent = AgentRequest(agent=agent, input={"text": text}, budget_seconds=budget)
    (run_dir / "request.json").write_text(sent.model_dump_json())


def envelope(run_dir: Path) -> Succeeded | Failed:
    return ENVELOPE.validate_json((run_dir / "result.json").read_bytes())


async def succeeding(
    input: ToneInput, workdir: Path | None
) -> tuple[ToneOutput, RunReport]:
    return ToneOutput(tone="friendly", friendly=True), REPORT


async def failing(
    input: ToneInput, workdir: Path | None
) -> tuple[ToneOutput, RunReport]:
    raise AgentRunFailed("error_max_turns", REPORT)


async def hanging(
    input: ToneInput, workdir: Path | None
) -> tuple[ToneOutput, RunReport]:
    await asyncio.sleep(60)
    raise AssertionError("the deadline did not fire")


async def test_a_run_writes_an_ok_envelope_with_the_output_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "run", succeeding)
    request(tmp_path)

    ok = await runner.execute(tmp_path)

    assert ok
    assert envelope(tmp_path) == Succeeded(
        output={"tone": "friendly", "friendly": True}, report=REPORT
    )


async def test_a_failed_run_writes_its_reason_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "run", failing)
    request(tmp_path)

    ok = await runner.execute(tmp_path)

    assert not ok
    assert envelope(tmp_path) == Failed(reason="error_max_turns", report=REPORT)


async def test_a_run_past_its_budget_fails_with_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "run", hanging)
    request(tmp_path, budget=0.05)

    await runner.execute(tmp_path)

    assert envelope(tmp_path) == Failed(reason="deadline", report=RunReport())


async def test_the_envelope_replaces_the_file_by_a_rename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(agent, "run", succeeding)
    request(tmp_path)
    (tmp_path / "result.json").write_text("old")
    # A second name for the old file: a write in place would change it too.
    os.link(tmp_path / "result.json", tmp_path / "observer")

    await runner.execute(tmp_path)

    assert (tmp_path / "observer").read_text() == "old"
    assert isinstance(envelope(tmp_path), Succeeded)
    assert sorted(path.name for path in tmp_path.iterdir()) == [
        "observer",
        "request.json",
        "result.json",
    ]


async def test_a_package_that_does_not_exist_fails_the_run(tmp_path: Path) -> None:
    request(tmp_path, agent="nope")

    await runner.execute(tmp_path)

    assert envelope(tmp_path) == Failed(reason="unknown_agent", report=RunReport())


async def test_a_package_outside_corvo_agents_is_refused(tmp_path: Path) -> None:
    (tmp_path / "request.json").write_text(
        '{"agent": "tone.agent", "input": {}, "budget_seconds": 5}'
    )

    await runner.execute(tmp_path)

    assert envelope(tmp_path) == Failed(reason="invalid_request", report=RunReport())


async def test_a_missing_request_fails_the_run(tmp_path: Path) -> None:
    await runner.execute(tmp_path)

    assert envelope(tmp_path) == Failed(reason="invalid_request", report=RunReport())


async def test_an_input_the_agent_rejects_fails_the_run(tmp_path: Path) -> None:
    request(tmp_path, text="")

    await runner.execute(tmp_path)

    assert envelope(tmp_path) == Failed(reason="invalid_input", report=RunReport())


ROUTE = (
    "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\n"
    "eth0\t0000000A\t00000000\t0001\t0\t0\t0\t000000FF\n"
    "eth0\t00000000\t0100007F\t0003\t0\t0\t0\t00000000\n"
)

MOUNTS = (
    "overlay / overlay ro,relatime,lowerdir=/l 0 0\n"
    "tmpfs /tmp tmpfs rw,nosuid,nodev,noexec,relatime,size=102400k 0 0\n"
    "tmpfs /home/agent tmpfs rw,nosuid,nodev,noexec,relatime,size=512000k 0 0\n"
)


def fake_root(root: Path) -> Path:
    cgroup = root / "sys" / "fs" / "cgroup"
    cgroup.mkdir(parents=True)
    (cgroup / "memory.max").write_text("1073741824\n")
    (cgroup / "cpu.max").write_text("100000 100000\n")
    (cgroup / "pids.max").write_text("256\n")
    (root / "proc" / "self").mkdir(parents=True)
    (root / "proc" / "net").mkdir()
    (root / "proc" / "self" / "status").write_text(
        "Name:\tcorvo-agent\nCapEff:\t0000000000000000\nCapBnd:\t0000000000000000\n"
    )
    (root / "proc" / "self" / "mounts").write_text(MOUNTS)
    (root / "proc" / "net" / "route").write_text(ROUTE)
    return root


def test_the_probe_reports_what_it_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only the gateway answers; reaches itself is tested below.
    monkeypatch.setattr(runner, "reaches", lambda address: address == "127.0.0.1")

    report = runner.probe(fake_root(tmp_path))

    assert report.fingerprint == fingerprint()
    assert (report.memory_max, report.cpu_max, report.pids_max) == (
        "1073741824",
        "100000 100000",
        "256",
    )
    assert report.cap_eff == "0000000000000000"
    assert report.root_read_only
    assert report.mounts == {
        "/tmp": ["rw", "nosuid", "nodev", "noexec", "relatime", "size=102400k"],
        "/home/agent": ["rw", "nosuid", "nodev", "noexec", "relatime", "size=512000k"],
    }
    assert "PATH" in report.env_names
    assert report.gateway == "127.0.0.1"
    assert report.gateway_reachable
    assert not report.metadata_reachable


def test_without_a_default_route_the_gateway_is_not_probed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "reaches", lambda address: False)
    root = fake_root(tmp_path)
    (root / "proc" / "net" / "route").write_text(ROUTE.splitlines(keepends=True)[0])

    report = runner.probe(root)

    assert (report.gateway, report.gateway_reachable) == (None, None)


def test_an_address_that_accepts_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        monkeypatch.setattr(runner, "PROBE_PORT", server.getsockname()[1])

        assert runner.reaches("127.0.0.1")


def test_an_address_that_refuses_is_reached(monkeypatch: pytest.MonkeyPatch) -> None:
    with socket.create_server(("127.0.0.1", 0)) as server:
        closed = server.getsockname()[1]
    monkeypatch.setattr(runner, "PROBE_PORT", closed)

    assert runner.reaches("127.0.0.1")


def test_an_address_that_never_answers_is_not_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def silent(address: tuple[str, int], timeout: float) -> socket.socket:
        raise TimeoutError("timed out")

    monkeypatch.setattr(socket, "create_connection", silent)

    assert not runner.reaches("169.254.169.254")
