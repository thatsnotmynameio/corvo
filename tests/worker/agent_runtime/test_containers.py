import asyncio
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from docker import DockerClient
from hatchet_sdk import Context, EmptyModel

from corvo.agents.envelope import (
    AgentRequest,
    Failed,
    RunReport,
    Succeeded,
)
from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.worker.agent_runtime import containers
from corvo.worker.agent_runtime.containers import AgentFailed, Runtime, run_agent
from corvo.worker.agent_runtime.spec import Credential
from corvo.worker.hatchet_client import hatchet

from .fake_podman import Behaviour, Exit, FakeClient

REPORT = RunReport(
    subtype="success", num_turns=2, total_cost_usd=0.0042, session_id="s-1"
)
OK = Succeeded(output={"tone": "friendly", "friendly": True}, report=REPORT)


# A task of the tests' own that runs an agent through the piece, as every
# agent task does.
@hatchet.task(name="containers-example", input_validator=ToneInput)
async def example(input: ToneInput, ctx: Context) -> ToneOutput:
    return await run_agent("tone", input, ToneOutput, ctx)


class WorkdirInput(EmptyModel):
    workdir: str


@hatchet.task(name="containers-workdir-example", input_validator=WorkdirInput)
async def workdir_example(input: WorkdirInput, ctx: Context) -> ToneOutput:
    return await run_agent(
        "tone", ToneInput(text="hi"), ToneOutput, ctx, workdir=Path(input.workdir)
    )


def writes(envelope: Succeeded | Failed, *stderr: bytes, code: int = 0) -> Behaviour:
    """A container that writes the envelope as corvo-agent does, and exits."""

    def behaviour(run_dir: Path) -> Exit:
        (run_dir / "result.json").write_text(envelope.model_dump_json())
        return Exit(stderr=list(stderr), code=code)

    return behaviour


@pytest.fixture
def logged(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    lines: list[str] = []
    monkeypatch.setattr(Context, "log", lambda self, line: lines.append(line))
    return lines


@pytest.fixture
def ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pins the run's IDs, which a mock run makes up."""
    monkeypatch.setattr(Context, "task_run_id", property(lambda self: "task-1"))
    monkeypatch.setattr(Context, "workflow_run_id", property(lambda self: "run-1"))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "runs").mkdir()
    (tmp_path / "workdirs").mkdir()
    return tmp_path


@pytest.fixture
def podman(root: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient(writes(OK))
    runtime = Runtime(
        client=cast(DockerClient, client),
        root=root,
        image="corvo-agent",
        credential=Credential(kind="api_key", value="secret"),
        deployment="tenant@http://hatchet",
    )
    monkeypatch.setattr(containers, "state", runtime)
    return client


async def test_a_run_returns_the_output_of_an_ok_envelope(
    podman: FakeClient, root: Path, logged: list[str]
) -> None:
    output = await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert output == ToneOutput(tone="friendly", friendly=True)
    assert "agent tone: ok, cost=0.0042 turns=2 session=s-1" in logged


async def test_the_container_is_the_spec_of_this_run(
    podman: FakeClient, root: Path, logged: list[str]
) -> None:
    created: list[dict[str, object]] = []
    behaviour = podman.behaviour

    def record(run_dir: Path) -> Exit:
        [container] = podman.containers.made
        created.append(container.spec)
        return behaviour(run_dir)

    podman.behaviour = record

    await example.aio_mock_run(ToneInput(text="Thanks!"))

    [spec] = created
    labels = cast(dict[str, str], spec["labels"])
    assert spec["image"] == "corvo-agent"
    assert spec["command"] == ["run"]
    assert spec["name"] == f"corvo-agent-{labels['corvo.task_run_id']}-0"
    assert labels["corvo.deployment"] == "tenant@http://hatchet"
    assert labels["corvo.agent"] == "tone"
    assert cast(dict[str, str], spec["environment"])["ANTHROPIC_API_KEY"] == "secret"


async def test_the_request_carries_the_input_and_a_budget_below_the_timeout(
    podman: FakeClient, logged: list[str]
) -> None:
    requests: list[AgentRequest] = []
    behaviour = podman.behaviour

    def record(run_dir: Path) -> Exit:
        request = (run_dir / "request.json").read_text()
        requests.append(AgentRequest.model_validate_json(request))
        return behaviour(run_dir)

    podman.behaviour = record

    await example.aio_mock_run(ToneInput(text="Thanks!"))

    [request] = requests
    assert (request.agent, request.input) == ("tone", {"text": "Thanks!"})
    assert 0 < request.budget_seconds < 14 * 60


async def test_a_finished_run_removes_its_container_and_run_directory(
    podman: FakeClient, root: Path, logged: list[str]
) -> None:
    await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert podman.containers.made == []
    assert len(podman.removals) == 1
    assert list((root / "runs").iterdir()) == []


@pytest.mark.parametrize("status", [404, 409])
async def test_cleanup_takes_a_missing_or_busy_container_as_removed(
    podman: FakeClient, root: Path, logged: list[str], status: int
) -> None:
    behaviour = podman.behaviour

    def failing_removal(run_dir: Path) -> Exit:
        [container] = podman.containers.made
        container.remove_fails_with = status
        return behaviour(run_dir)

    podman.behaviour = failing_removal

    output = await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert output.friendly
    assert not any("cleanup" in line for line in logged)
    assert list((root / "runs").iterdir()) == []


async def test_a_failed_envelope_fails_the_task_with_its_report(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = writes(Failed(reason="error_max_turns", report=REPORT), code=1)

    with pytest.raises(AgentFailed, match="agent tone failed: error_max_turns"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert "agent tone: failed, cost=0.0042 turns=2 session=s-1" in logged
    assert podman.containers.made == []


async def test_stderr_reaches_the_log_behind_a_prefix_cut_and_capped(
    podman: FakeClient, logged: list[str]
) -> None:
    long = b"x" * 600
    lines = [b"session s-1\n", b"half a ", b"line\x1b[31m\n", long + b"\n"]
    lines += [b"more\n"] * 1000
    podman.behaviour = writes(OK, *lines)

    await example.aio_mock_run(ToneInput(text="Thanks!"))

    forwarded = [line for line in logged if line.startswith("agent stderr: ")]
    assert forwarded[:3] == [
        "agent stderr: session s-1",
        "agent stderr: half a line[31m",
        "agent stderr: " + "x" * 500,
    ]
    assert len(forwarded) == 900


def fifo(path: Path) -> None:
    os.mkfifo(path)


def link(path: Path) -> None:
    secret = path.parent / "secret"
    secret.write_text(OK.model_dump_json())
    path.symlink_to(secret)


def large(path: Path) -> None:
    path.write_text(" " * (1024 * 1024) + OK.model_dump_json())


def invalid(path: Path) -> None:
    path.write_text('{"status": "ok", "output": "leaked-content"}')


@pytest.mark.parametrize("make", [fifo, link, Path.mkdir, large, invalid])
async def test_an_untrusted_envelope_fails_without_its_content(
    podman: FakeClient, logged: list[str], make: Callable[[Path], object]
) -> None:
    def behaviour(run_dir: Path) -> Exit:
        make(run_dir / "result.json")
        return Exit()

    podman.behaviour = behaviour

    async with asyncio.timeout(5):
        with pytest.raises(AgentFailed, match="invalid envelope") as failure:
            await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert "leaked-content" not in str(failure.value)
    assert not any("leaked-content" in line for line in logged)
    assert "agent tone: invalid envelope, cost=unknown" in "\n".join(logged)


async def test_an_out_of_memory_exit_without_an_envelope_fails(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = lambda run_dir: Exit(code=137, oom_killed=True)

    with pytest.raises(AgentFailed, match="no envelope"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert (
        "agent tone: no envelope, cost=unknown turns=unknown session=unknown "
        "exit_code=137 oom_killed=True"
    ) in logged


async def test_an_output_the_task_cannot_read_fails(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = writes(Succeeded(output={"tone": "leaked"}, report=REPORT))

    with pytest.raises(AgentFailed, match="not a valid ToneOutput") as failure:
        await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert "leaked" not in str(failure.value)
    assert failure.value.__cause__ is None
    assert failure.value.__suppress_context__


async def test_a_rerun_after_a_lost_worker_cleans_up_and_fails(
    podman: FakeClient, root: Path, logged: list[str], ids: None
) -> None:
    earlier = podman.stray(**{"corvo.task_run_id": "task-1"})
    (root / "runs" / "task-1-0").mkdir()

    with pytest.raises(AgentFailed, match="worker was lost"):
        await example.aio_mock_run(ToneInput(text="Thanks!"), retry_count=1)

    assert earlier.removed.is_set()
    assert podman.containers.made == []
    assert list((root / "runs").iterdir()) == []


async def test_a_replay_with_nothing_left_runs(
    podman: FakeClient, logged: list[str], ids: None
) -> None:
    output = await example.aio_mock_run(ToneInput(text="Thanks!"), retry_count=1)

    assert output.friendly
    assert podman.lookups[0] == {"corvo.managed": "true", "corvo.task_run_id": "task-1"}


async def test_a_run_directory_that_exists_fails_before_any_container(
    podman: FakeClient, root: Path, ids: None
) -> None:
    (root / "runs" / "task-1-0").mkdir()

    with pytest.raises(AgentFailed, match="already exists"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert podman.lookups == []
    assert podman.containers.made == []


async def test_a_cancel_during_create_still_removes_the_container(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.containers.create_gate = threading.Event()
    run = asyncio.create_task(example.aio_mock_run(ToneInput(text="Thanks!")))
    await asyncio.to_thread(podman.containers.creating.wait, 5)

    run.cancel()
    await asyncio.sleep(0.1)
    podman.containers.create_gate.set()

    with pytest.raises(asyncio.CancelledError):
        await run
    assert podman.containers.made == []
    assert len(podman.removals) == 1


async def test_without_configuration_a_run_fails_at_once(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers, "state", containers.NOT_CONFIGURED)

    with pytest.raises(AgentFailed, match="agents are not configured"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))


async def test_disabled_agents_fail_a_run_with_the_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(containers, "state", containers.NOT_CONFIGURED)
    containers.disable("the probe's pids.max is 'max', not '256'")

    with pytest.raises(AgentFailed, match="pids.max is 'max'"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))


async def test_a_workdir_outside_the_root_fails_before_any_container(
    podman: FakeClient, tmp_path_factory: pytest.TempPathFactory
) -> None:
    outside = tmp_path_factory.mktemp("outside")

    with pytest.raises(AgentFailed, match="is not a directory below"):
        await workdir_example.aio_mock_run(WorkdirInput(workdir=str(outside)))

    assert podman.lookups == []
    assert podman.containers.made == []


async def test_removing_the_in_flight_containers_spares_the_others(
    podman: FakeClient,
) -> None:
    runtime = cast(Runtime, containers.state)
    mine = podman.stray(**{"corvo.task_run_id": "mine"})
    other = podman.stray(**{"corvo.task_run_id": "other"})
    runtime.in_flight.add("mine")

    await containers.remove_in_flight(runtime)

    assert mine.removed.is_set()
    assert not other.removed.is_set()


def test_the_envelope_reader_reads_a_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"a": 1}))

    assert containers.read_untrusted(path) == b'{"a": 1}'


async def test_a_container_removed_mid_run_fails_on_its_missing_envelope(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = lambda run_dir: Exit(hangs=True)
    run = asyncio.create_task(example.aio_mock_run(ToneInput(text="Thanks!")))
    while not (podman.containers.made and podman.containers.made[0].started):
        await asyncio.sleep(0.01)

    # As the SIGTERM hook does.
    await containers.remove_in_flight(cast(Runtime, containers.state))

    with pytest.raises(AgentFailed, match="no envelope"):
        await run
    assert any("exit_code=unknown" in line for line in logged)
