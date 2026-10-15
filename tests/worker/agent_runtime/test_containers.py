import asyncio
import socket
import threading
import time
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
from corvo.agents.frame import MAX_UNTRUSTED_BYTES, encode
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

# A request past the socket's buffers, which a container that never reads
# leaves the write blocked on.
LARGE = "x" * (MAX_UNTRUSTED_BYTES // 2)


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


class LongInput(EmptyModel):
    text: str


# The same, with an input of any length, as no real agent's is.
@hatchet.task(name="containers-long-example", input_validator=LongInput)
async def long_example(input: LongInput, ctx: Context) -> ToneOutput:
    return await run_agent("tone", input, ToneOutput, ctx)


def framed(envelope: Succeeded | Failed) -> bytes:
    return encode(envelope.model_dump_json().encode())


def writes(envelope: Succeeded | Failed, *stderr: bytes, code: int = 0) -> Behaviour:
    """A container that frames the envelope on its stdout as corvo-agent
    does, and exits."""

    def behaviour(request: bytes) -> Exit:
        return Exit(stdout=[framed(envelope)], stderr=list(stderr), code=code)

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


def until_started(podman: FakeClient) -> asyncio.Future[None]:
    async def started() -> None:
        while not (podman.containers.made and podman.containers.made[0].started):
            await asyncio.sleep(0.01)

    return asyncio.ensure_future(asyncio.wait_for(started(), 5))


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

    def record(request: bytes) -> Exit:
        [container] = podman.containers.made
        created.append(container.spec)
        return behaviour(request)

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


async def test_the_container_is_attached_to_before_it_starts(
    podman: FakeClient, logged: list[str]
) -> None:
    await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert podman.events == ["create", "attach", "start"]


async def test_the_request_carries_the_input_and_a_budget_below_the_timeout(
    podman: FakeClient, root: Path, logged: list[str]
) -> None:
    files: list[list[Path]] = []
    behaviour = podman.behaviour

    def record(request: bytes) -> Exit:
        # Mid-run, as the container reads it: no file holds the request.
        files.append([path for path in root.rglob("*") if path.is_file()])
        return behaviour(request)

    podman.behaviour = record

    await example.aio_mock_run(ToneInput(text="Thanks!"))

    [sent] = podman.requests
    request = AgentRequest.model_validate_json(sent)
    assert (request.agent, request.input) == ("tone", {"text": "Thanks!"})
    assert 0 < request.budget_seconds < 14 * 60
    assert files == [[]]


async def test_a_finished_run_removes_its_container_and_closes_its_socket(
    podman: FakeClient, root: Path, logged: list[str]
) -> None:
    await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert podman.containers.made == []
    assert len(podman.removals) == 1
    assert podman.open_sockets() == []
    assert list(root.iterdir()) == [root / "workdirs"]


@pytest.mark.parametrize("status", [404, 409])
async def test_cleanup_takes_a_missing_or_busy_container_as_removed(
    podman: FakeClient, logged: list[str], status: int
) -> None:
    removal(podman, fails_with=status)

    output = await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert output.friendly
    assert not any("cleanup" in line for line in logged)


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

    output = await example.aio_mock_run(ToneInput(text="Thanks!"))

    # Interleaved with the envelope's frame, stderr never enters it.
    assert output.friendly
    forwarded = [line for line in logged if line.startswith("agent stderr: ")]
    assert forwarded[:3] == [
        "agent stderr: session s-1",
        "agent stderr: half a line[31m",
        "agent stderr: " + "x" * 500,
    ]
    assert len(forwarded) == 900


async def test_an_envelope_split_across_frames_and_reads_is_read_whole(
    podman: FakeClient, logged: list[str]
) -> None:
    whole = framed(OK)
    chunks = [whole[i : i + 7] for i in range(0, len(whole), 7)]
    podman.behaviour = lambda request: Exit(stdout=chunks, trickles=True)

    output = await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert output.friendly
    assert "agent tone: ok, cost=0.0042 turns=2 session=s-1" in logged


@pytest.mark.parametrize(
    "stdout",
    [
        b"leaked-content",
        b"+5\nleaked-content",
        encode(b'{"status": "ok", "output": "leaked-content"}'),
        # Past the cap: kept to its start and drained to its end.
        b"%d\n" % (2 * MAX_UNTRUSTED_BYTES) + b"leaked-content" * 150_000,
    ],
)
async def test_an_untrusted_envelope_fails_without_its_content(
    podman: FakeClient, logged: list[str], stdout: bytes
) -> None:
    podman.behaviour = lambda request: Exit(stdout=[stdout])

    async with asyncio.timeout(5):
        with pytest.raises(AgentFailed, match="invalid envelope") as failure:
            await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert "leaked-content" not in str(failure.value)
    assert not any("leaked-content" in line for line in logged)
    assert "agent tone: invalid envelope, cost=unknown" in "\n".join(logged)


async def test_only_the_start_of_stdout_is_kept(
    podman: FakeClient, logged: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # One byte short of the envelope's frame.
    monkeypatch.setattr(containers, "MAX_KEPT", len(framed(OK)) - 1)

    with pytest.raises(AgentFailed, match="no envelope"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))


@pytest.mark.parametrize("stdout", [[], [b"100\n{"]])
async def test_a_missing_or_truncated_envelope_fails_with_the_exit_code(
    podman: FakeClient, logged: list[str], stdout: list[bytes]
) -> None:
    podman.behaviour = lambda request: Exit(stdout=stdout, code=3)

    with pytest.raises(AgentFailed, match="no envelope"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert (
        "agent tone: no envelope, cost=unknown turns=unknown session=unknown "
        "exit_code=3 oom_killed=False"
    ) in logged


async def test_an_out_of_memory_exit_without_an_envelope_fails(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = lambda request: Exit(code=137, oom_killed=True)

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


async def test_a_stream_that_outlives_its_container_is_closed_after_the_drain(
    podman: FakeClient, logged: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers, "DRAIN_TIMEOUT", 0.2)
    podman.behaviour = lambda request: Exit(stdout=[framed(OK)], outlives=True)

    async with asyncio.timeout(5):
        output = await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert output.friendly
    assert podman.open_sockets() == []


async def test_a_stream_that_fails_leaves_the_exit_to_decide(
    podman: FakeClient, logged: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing(sock: socket.socket, size: int) -> bytes | None:
        raise ConnectionResetError

    monkeypatch.setattr(containers, "received", failing)

    with pytest.raises(AgentFailed, match="no envelope"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert any("exit_code=0" in line for line in logged)


async def test_a_request_over_the_cap_fails_before_any_container(
    podman: FakeClient,
) -> None:
    text = "x" * (MAX_UNTRUSTED_BYTES + 1)

    with pytest.raises(AgentFailed, match="request is too large") as failure:
        await long_example.aio_mock_run(LongInput(text=text))

    assert f"outside 1 to {MAX_UNTRUSTED_BYTES}" in str(failure.value)
    assert podman.events == []


async def test_a_container_that_exits_before_reading_fails_on_its_exit(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.reading = "exits"

    with pytest.raises(AgentFailed, match=r"no envelope \(exit code 1"):
        await long_example.aio_mock_run(LongInput(text=LARGE))


async def test_a_container_that_never_reads_fails_within_the_write_bound(
    podman: FakeClient, logged: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers, "REQUEST_WRITE_TIMEOUT", 0.2)
    podman.reading = "never"

    async with asyncio.timeout(5):
        with pytest.raises(AgentFailed, match="did not read its request"):
            await long_example.aio_mock_run(LongInput(text=LARGE))

    assert podman.containers.made == []
    assert podman.open_sockets() == []


async def test_a_rerun_after_a_lost_worker_cleans_up_and_fails(
    podman: FakeClient, logged: list[str], ids: None
) -> None:
    earlier = podman.stray(**{"corvo.task_run_id": "task-1"})

    with pytest.raises(AgentFailed, match="worker was lost"):
        await example.aio_mock_run(ToneInput(text="Thanks!"), retry_count=1)

    assert earlier.removed.is_set()
    assert podman.containers.made == []


async def test_a_replay_with_nothing_left_runs(
    podman: FakeClient, logged: list[str], ids: None
) -> None:
    output = await example.aio_mock_run(ToneInput(text="Thanks!"), retry_count=1)

    assert output.friendly
    assert podman.lookups[0] == {"corvo.managed": "true", "corvo.task_run_id": "task-1"}


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


async def test_a_cancel_during_the_attach_leaves_no_socket_open(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.attach_gate = threading.Event()
    run = asyncio.create_task(example.aio_mock_run(ToneInput(text="Thanks!")))
    while "attach" not in podman.events:
        await asyncio.sleep(0.01)

    run.cancel()
    await asyncio.sleep(0.1)
    podman.attach_gate.set()

    with pytest.raises(asyncio.CancelledError):
        await run
    assert podman.containers.made == []
    assert len(podman.streams) == 1
    assert podman.open_sockets() == []


async def test_a_cancel_during_the_write_leaves_no_socket_open(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.reading = "never"
    run = asyncio.create_task(long_example.aio_mock_run(LongInput(text=LARGE)))
    await until_started(podman)
    await asyncio.sleep(0.1)

    run.cancel()

    async with asyncio.timeout(5):
        with pytest.raises(asyncio.CancelledError):
            await run
    assert podman.containers.made == []
    assert podman.open_sockets() == []


async def test_a_cancel_mid_session_cleans_up_well_inside_its_bound(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = lambda request: Exit(hangs=True)
    run = asyncio.create_task(example.aio_mock_run(ToneInput(text="Thanks!")))
    await until_started(podman)
    await asyncio.sleep(0.1)

    started = time.monotonic()
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run

    assert time.monotonic() - started < containers.CLEANUP_TIMEOUT / 10
    assert podman.containers.made == []
    assert podman.open_sockets() == []


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


async def test_a_container_removed_mid_run_fails_on_its_missing_envelope(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = lambda request: Exit(hangs=True)
    run = asyncio.create_task(example.aio_mock_run(ToneInput(text="Thanks!")))
    await until_started(podman)

    # As the SIGTERM hook does.
    await containers.remove_in_flight(cast(Runtime, containers.state))

    with pytest.raises(AgentFailed, match="no envelope"):
        await run
    assert any("exit_code=unknown" in line for line in logged)


def removal(
    podman: FakeClient, fails_with: int | None = None, takes: float = 0
) -> None:
    """Has the run's container fail or stall its removal."""
    behaviour = podman.behaviour

    def failing(request: bytes) -> Exit:
        [container] = podman.containers.made
        container.remove_fails_with = fails_with
        container.remove_takes = takes
        return behaviour(request)

    podman.behaviour = failing


@pytest.mark.parametrize(
    ("fails_with", "takes", "error"), [(500, 0, "APIError"), (None, 1, "TimeoutError")]
)
async def test_a_cleanup_that_fails_keeps_the_runs_output_and_logs_it(
    podman: FakeClient,
    logged: list[str],
    ids: None,
    monkeypatch: pytest.MonkeyPatch,
    fails_with: int | None,
    takes: float,
    error: str,
) -> None:
    monkeypatch.setattr(containers, "CLEANUP_TIMEOUT", 0.2)
    removal(podman, fails_with=fails_with, takes=takes)

    output = await example.aio_mock_run(ToneInput(text="Thanks!"))

    assert output.friendly
    assert any(
        line.startswith(f"agent tone: cleanup failed: {error}") for line in logged
    )
    # Left for the SIGTERM hook to retry.
    assert cast(Runtime, containers.state).in_flight == {"task-1"}


async def test_a_cleanup_that_fails_keeps_the_runs_own_failure(
    podman: FakeClient, logged: list[str]
) -> None:
    podman.behaviour = writes(Failed(reason="error_max_turns", report=REPORT), code=1)
    removal(podman, fails_with=500)

    with pytest.raises(AgentFailed, match="agent tone failed: error_max_turns"):
        await example.aio_mock_run(ToneInput(text="Thanks!"))
