import asyncio
import io
import os
import socket
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from corvo.agents import runner
from corvo.agents.envelope import (
    ENVELOPE,
    AgentRequest,
    AgentRunFailed,
    Failed,
    ProbeReport,
    RunReport,
    Succeeded,
)
from corvo.agents.fingerprint import fingerprint
from corvo.agents.frame import encode, extract
from corvo.agents.tone import agent
from corvo.agents.tone.models import ToneInput, ToneOutput

REPORT = RunReport(
    subtype="success", num_turns=2, total_cost_usd=0.0042, session_id="s-1"
)


def request(agent: str = "tone", text: str = "Thanks!", budget: float = 5) -> bytes:
    sent = AgentRequest(agent=agent, input={"text": text}, budget_seconds=budget)
    return sent.model_dump_json().encode()


async def executed(raw: bytes | None) -> tuple[bool, Succeeded | Failed]:
    """Whether the run was ok, and the envelope it framed on its stdout."""
    out = io.BytesIO()
    ok = await runner.execute(raw, out)
    framed = extract(out.getvalue())
    assert framed is not None
    return ok, ENVELOPE.validate_json(framed)


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


async def test_a_run_frames_an_ok_envelope_with_the_output_and_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent, "run", succeeding)

    ok, envelope = await executed(request())

    assert ok
    assert envelope == Succeeded(
        output={"tone": "friendly", "friendly": True}, report=REPORT
    )


async def test_a_failed_run_frames_its_reason_and_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent, "run", failing)

    ok, envelope = await executed(request())

    assert not ok
    assert envelope == Failed(reason="error_max_turns", report=REPORT)


async def test_a_run_past_its_budget_fails_with_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(agent, "run", hanging)

    _, envelope = await executed(request(budget=0.05))

    assert envelope == Failed(reason="deadline", report=RunReport())


async def test_a_package_that_does_not_exist_fails_the_run() -> None:
    _, envelope = await executed(request(agent="nope"))

    assert envelope == Failed(reason="unknown_agent", report=RunReport())


async def test_a_package_outside_corvo_agents_is_refused() -> None:
    raw = b'{"agent": "tone.agent", "input": {}, "budget_seconds": 5}'

    _, envelope = await executed(raw)

    assert envelope == Failed(reason="invalid_request", report=RunReport())


@pytest.mark.parametrize("raw", [None, b"not json"])
async def test_a_request_that_did_not_arrive_or_is_invalid_fails_the_run(
    raw: bytes | None,
) -> None:
    _, envelope = await executed(raw)

    assert envelope == Failed(reason="invalid_request", report=RunReport())


async def test_an_input_the_agent_rejects_fails_the_run() -> None:
    _, envelope = await executed(request(text=""))

    assert envelope == Failed(reason="invalid_input", report=RunReport())


@pytest.fixture
def stdin() -> Iterator[tuple[int, int]]:
    """A pipe whose read end stands for the runner's stdin."""
    read_end, write_end = os.pipe()
    yield read_end, write_end
    os.close(read_end)
    try:
        os.close(write_end)
    except OSError:
        pass


def is_null(fd: int) -> bool:
    return os.fstat(fd).st_rdev == os.stat(os.devnull).st_rdev


def test_the_request_is_read_from_its_frame_and_stdin_then_closed(
    stdin: tuple[int, int],
) -> None:
    read_end, write_end = stdin
    os.write(write_end, encode(request()) + b"late bytes")

    assert runner.read_request(read_end) == request()
    assert is_null(read_end)


@pytest.mark.parametrize(
    "sent",
    [
        # Covers AE2: the header promises more bytes than arrive.
        b"100\n" + request(),
        b"x" + encode(request()),
        b"%d\n" % (1024 * 1024 + 1),
        b"",
    ],
)
def test_a_request_that_does_not_arrive_whole_is_none(
    stdin: tuple[int, int],
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
    sent: bytes,
) -> None:
    monkeypatch.setattr(runner, "REQUEST_READ_TIMEOUT", 0.2)
    read_end, write_end = stdin
    os.write(write_end, sent)

    assert runner.read_request(read_end) is None
    assert is_null(read_end)
    # The reason names sizes at most, never the request.
    err = capfd.readouterr().err
    assert "invalid request" in err
    assert "Thanks" not in err


# The runner's main, with the outcome a stand-in that prints to stdout, as
# the CLI or a library might.
NOISY_MAIN = """
import os, sys
from corvo.agents import runner
from corvo.agents.envelope import Failed, RunReport

async def noisy(raw):
    print("printed")
    os.write(1, b"written to fd 1\\n")
    return Failed(reason=raw.decode(), report=RunReport())

runner.outcome = noisy
sys.argv = ["corvo-agent", "run"]
sys.exit(runner.main())
"""


def test_only_the_envelope_reaches_the_runners_stdout() -> None:
    ran = subprocess.run(
        [sys.executable, "-c", NOISY_MAIN],
        input=encode(b"from-stdin"),
        capture_output=True,
        timeout=30,
    )

    assert ran.returncode == 1
    framed = extract(ran.stdout)
    assert framed is not None
    assert ran.stdout == encode(framed)
    assert ENVELOPE.validate_json(framed) == Failed(
        reason="from-stdin", report=RunReport()
    )
    assert b"printed" in ran.stderr
    assert b"written to fd 1" in ran.stderr


def test_the_probe_frames_its_report_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "reaches", lambda address: False)
    out = io.BytesIO()

    runner.send(out, runner.probe(fake_root(tmp_path)))

    framed = extract(out.getvalue())
    assert framed is not None
    assert ProbeReport.model_validate_json(framed).cpu_max == "100000 100000"


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
