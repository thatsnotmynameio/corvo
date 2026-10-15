"""The one piece of the worker that runs agent containers (R17).

run_agent runs one agent session for an agent task: it creates a container
built by spec.container_spec on the agents' rootless Podman, attaches to
it, starts it, and writes the request, framed by its length, to its stdin
(corvo.agents.frame). No file on the host ever holds the request. Over the
same attach stream it forwards the container's stderr to the run's log and
keeps its stdout, where corvo-agent frames the envelope, until the stream
ends after the container exits. Then it removes the container, whatever
happened, cancel and timeout included. Every agent task calls it; none
starts a container itself.

What the container wrote is untrusted. At most 1 MiB of its stdout is
kept, past which it is drained and dropped, so the container never blocks;
the envelope is validated with the envelope model and never echoed: an
invalid one fails the run without its content. A working directory an
agent may have written is untrusted output too: the worker runs no git,
hooks, config or code from it.

docker-py is synchronous, so each of its calls runs in a thread (KTD5). A
cancel can land while the thread that creates the container is still
running, so cleanup waits for that thread, then removes containers by the
run's label, never by the handle create returned (KTD8).
"""

import asyncio
import socket
import struct
import threading
import time
import unicodedata
from collections.abc import Callable, Coroutine, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from hatchet_sdk import Context
from pydantic import BaseModel, ValidationError

from corvo.agents.envelope import ENVELOPE, AgentRequest, Failed, RunReport, Succeeded
from corvo.agents.frame import (
    CHUNK,
    MAX_HEADER,
    MAX_UNTRUSTED_BYTES,
    FrameError,
    encode,
    extract,
)
from corvo.worker.agent_runtime.spec import (
    MANAGED,
    Credential,
    InvalidWorkdir,
    Run,
    check_workdir,
    container_spec,
    session_budget,
    task_run_label,
)

# Forwarded stderr: each line behind the prefix, so no line the agent prints
# passes for one of the worker's own, cut to MAX_LINE characters, up to
# MAX_LINES lines. Hatchet keeps 1000 lines a run.
STDERR_PREFIX = "agent stderr: "
MAX_LINE = 500
MAX_LINES = 900
# A line that runs longer than this without ending is sent cut, rather than
# held whole.
MAX_PENDING = MAX_LINE * 4

# How long cleanup may take, under a cancel or a timeout.
CLEANUP_TIMEOUT = 30

# How long the container may take to read its request, above the runner's
# own bound on its read, and how long its stream may take to end once it
# has exited.
REQUEST_WRITE_TIMEOUT = 45
DRAIN_TIMEOUT = 5

# The attach: stdin for the request, stdout and stderr back. No detach
# keys, where docker-py would otherwise send those of ~/.docker/config.json.
ATTACH = {"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "detachKeys": ""}

# The attach stream's frame header: the stream, three zero bytes and the
# payload's length.
STREAM_HEADER = struct.Struct(">BxxxL")
STDOUT, STDERR = 1, 2

# The most of the container's stdout kept: one frame at the cap.
MAX_KEPT = MAX_UNTRUSTED_BYTES + MAX_HEADER

# How long one Podman API call may take: below CLEANUP_TIMEOUT, so a create
# that cleanup waits for returns while cleanup can still remove its
# container. docker-py's own default is 60 seconds. Its wait drops the
# timeout, and the attach's reads lift it, so a session may stay silent for
# longer.
PODMAN_TIMEOUT = 10

NOT_CONFIGURED = "agents are not configured"


class AgentFailed(Exception):
    """An agent run that gave no valid output. Its message holds nothing the
    container wrote, beyond its failure reason."""


@dataclass
class Runtime:
    """What every agent run needs, set by the worker's preparation."""

    client: DockerClient
    root: Path
    image: str
    credential: Credential
    deployment: str
    # The task run IDs whose containers this worker may have started, which
    # the SIGTERM hook removes.
    in_flight: set[str] = field(default_factory=set)


# The runtime, or why agents are off. The worker's preparation sets it once,
# before it serves any task.
state: Runtime | str = NOT_CONFIGURED


def enable(runtime: Runtime) -> None:
    global state
    state = runtime


def disable(reason: str) -> None:
    global state
    state = reason


def current() -> Runtime:
    if isinstance(state, str):
        raise AgentFailed(state)
    return state


def printable(text: str, limit: int = MAX_LINE) -> str:
    """The text without control characters, cut to limit characters."""
    kept = "".join(c for c in text if not unicodedata.category(c).startswith("C"))
    return kept[:limit]


def remove(container: Container) -> None:
    """Force-removes the container, running or exited. One already gone (404)
    or being removed (409) counts as removed."""
    try:
        container.remove(force=True)
    except NotFound:
        pass
    except APIError as error:
        if error.status_code != 409:
            raise


def remove_labelled(client: DockerClient, label: str) -> int:
    """Force-removes every managed container carrying the label, and says how
    many it found."""
    found = client.containers.list(all=True, filters={"label": [MANAGED, label]})
    for container in found:
        remove(container)
    return len(found)


async def remove_in_flight(runtime: Runtime) -> None:
    """Removes the containers of this worker's in-flight agent runs."""
    for task_run_id in sorted(runtime.in_flight):
        await asyncio.to_thread(
            remove_labelled, runtime.client, task_run_label(task_run_id)
        )


class Calls:
    """The calls that create, attach to and start a run's container, and
    write its request, each in a thread that cleanup can wait for after a
    cancel."""

    def __init__(self) -> None:
        self.pending: set[asyncio.Future[Any]] = set()

    async def __call__[T](self, function: Callable[..., T], **arguments: Any) -> T:
        call = asyncio.ensure_future(asyncio.to_thread(function, **arguments))
        self.pending.add(call)
        call.add_done_callback(self.pending.discard)
        return await asyncio.shield(call)

    async def settle(self) -> None:
        if self.pending:
            await asyncio.wait(self.pending)


def forward_stderr(chunks: Iterable[bytes], log: Callable[[str], None]) -> None:
    """Sends the container's stderr to the run's log, line by line, until
    the container's output ends."""
    sent = 0
    pending = b""

    def send(line: bytes) -> None:
        nonlocal sent
        if sent < MAX_LINES:
            log(STDERR_PREFIX + printable(line.decode(errors="replace")))
            sent += 1

    for chunk in chunks:
        *lines, pending = (pending + chunk).split(b"\n")
        for line in lines:
            send(line)
        if len(pending) > MAX_PENDING:
            send(pending)
            pending = b""
    if pending:
        send(pending)


def received(sock: socket.socket, size: int) -> bytes | None:
    """Exactly size bytes, or None when the stream ends first."""
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(min(size - len(data), CHUNK))
        if not chunk:
            return None
        data += chunk
    return bytes(data)


class Attachment:
    """A run's attach to its container, once it has one.

    It is the only code that touches docker-py's raw socket, which
    attach_socket returns inside a stream, with the HTTP response that
    holds the socket open. Closing it ends a read or a write blocked on it,
    and an attach that returns after the close is closed at once, so a
    cancel during the attach leaves no socket open.
    """

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sock: socket.socket | None = None
        self.response: Any = None
        self.closed = False

    def open(self, client: DockerClient, container: str) -> None:
        stream = client.api.attach_socket(container, params=ATTACH)
        with self.lock:
            self.sock, self.response = stream._sock, stream._response
            if self.closed:
                self.shut()

    def write(self, data: bytes) -> None:
        """Sends data within REQUEST_WRITE_TIMEOUT, then lifts the timeout
        the socket has from the client, for the reads."""
        assert self.sock is not None
        self.sock.settimeout(REQUEST_WRITE_TIMEOUT)
        self.sock.sendall(data)
        self.sock.settimeout(None)

    def frames(self) -> Iterator[tuple[int, bytes]]:
        """Each frame's stream and payload, until the stream ends or fails."""
        assert self.sock is not None
        try:
            while (header := received(self.sock, STREAM_HEADER.size)) is not None:
                stream, size = STREAM_HEADER.unpack(header)
                payload = received(self.sock, size)
                if payload is None:
                    return
                yield stream, payload
        except OSError:
            return

    def close(self) -> None:
        with self.lock:
            self.closed = True
            if self.sock is not None:
                self.shut()

    def shut(self) -> None:
        assert self.sock is not None
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.response.close()
        self.sock.close()


def exit_status(container: Container) -> tuple[int | None, bool]:
    """The container's exit code once it exits, and whether the kernel killed
    it for lack of memory. The exit code is None when the container was
    removed before it exited, as the SIGTERM hook removes it."""
    try:
        exit_code = container.wait()["StatusCode"]
        container.reload()
    except NotFound:
        return None, False
    return exit_code, bool(container.attrs["State"].get("OOMKilled"))


def follow(
    container: Container, attachment: Attachment, log: Callable[[str], None]
) -> tuple[int | None, bool, bytes]:
    """Forwards the container's stderr and keeps the start of its stdout,
    until its stream ends, at most DRAIN_TIMEOUT after it exits: its wait
    can return before the last frames arrive. Then gives its exit status
    and the stdout kept. A stream that fails ends the read, and the exit
    and the envelope decide."""
    kept = bytearray()

    def stderr() -> Iterator[bytes]:
        for stream, payload in attachment.frames():
            if stream == STDERR:
                yield payload
            elif stream == STDOUT:
                kept.extend(payload[: MAX_KEPT - len(kept)])

    drain = threading.Timer(DRAIN_TIMEOUT, attachment.close)
    with ThreadPoolExecutor(max_workers=1) as pool:
        exited = pool.submit(exit_status, container)
        exited.add_done_callback(lambda _: drain.start())
        forward_stderr(stderr(), log)
        drain.cancel()
        exit_code, oom_killed = exited.result()
    return exit_code, oom_killed, bytes(kept)


def describe(report: RunReport) -> str:
    def shown(value: object) -> str:
        return "unknown" if value is None else printable(str(value), 100)

    return (
        f"cost={shown(report.total_cost_usd)} turns={shown(report.num_turns)} "
        f"session={shown(report.session_id)}"
    )


def conclude[T: BaseModel](
    agent: str,
    stdout: bytes,
    exit_code: int | None,
    oom_killed: bool,
    output: type[T],
    log: Callable[[str], None],
) -> T:
    """The run's output, from the envelope the container framed on its
    stdout, or the failure it reports. Logs the run's cost, turns and session
    ID either way."""
    envelope: Succeeded | Failed | None = None
    problem = "no envelope"
    try:
        framed = extract(stdout)
        if framed is not None:
            envelope = ENVELOPE.validate_json(framed)
    # Two clauses, not one with two types: the organization's coverage check
    # parses this file with a Python older than 3.14, which needs parentheses
    # there, and ruff removes them for 3.14.
    except FrameError:
        problem = "invalid envelope"
    except ValidationError:
        problem = "invalid envelope"
    if envelope is None:
        code = "unknown" if exit_code is None else exit_code
        log(
            f"agent {agent}: {problem}, {describe(RunReport())} "
            f"exit_code={code} oom_killed={oom_killed}"
        )
        raise AgentFailed(
            f"agent {agent} left {problem} (exit code {code}, "
            f"killed for lack of memory: {oom_killed})"
        )

    log(f"agent {agent}: {envelope.status}, {describe(envelope.report)}")
    if oom_killed:
        raise AgentFailed(f"agent {agent} was killed for lack of memory")
    if isinstance(envelope, Failed):
        raise AgentFailed(f"agent {agent} failed: {printable(envelope.reason, 100)}")
    try:
        return output.model_validate(envelope.output)
    except ValidationError:
        # From None: the validation error quotes the output.
        raise AgentFailed(
            f"agent {agent}'s output is not a valid {output.__name__}"
        ) from None


async def guard_rerun(runtime: Runtime, run: Run) -> None:
    """Before a rerun, removes the containers earlier attempts left, and fails
    the run when there were any (KTD8).

    The engine re-queues the task of a worker that stopped answering, whatever
    its retries, so an attempt's container left behind means its worker was
    lost mid-session: the sweep removes only containers whose run ended, and
    a re-queued run has not. A replay someone asked for raises the retry
    count too, but its earlier attempt removed its container.
    """
    removed = await asyncio.to_thread(
        remove_labelled, runtime.client, task_run_label(run.task_run_id)
    )
    if removed:
        raise AgentFailed(
            f"agent {run.agent}'s earlier attempt left its container, so its "
            "worker was lost mid-session: Hatchet re-queued it, and this run "
            "fails rather than pay for the session again"
        )


async def remove_run(
    client: DockerClient, label: str, attachment: Attachment, calls: Calls
) -> None:
    """Removes a container once the calls that create, attach to and start
    it have returned. Its attachment is closed first, so no call stays
    blocked on it."""
    attachment.close()
    await calls.settle()
    await asyncio.to_thread(remove_labelled, client, label)


async def shielded(cleanup: Coroutine[Any, Any, None]) -> None:
    """Runs cleanup to its end, even when the task is cancelled while it
    runs. The cleanup bounds itself."""
    await asyncio.shield(asyncio.ensure_future(cleanup))


async def run_agent[T: BaseModel](
    agent: str,
    input: BaseModel,
    output: type[T],
    ctx: Context,
    *,
    workdir: Path | None = None,
    writes_workdir: bool = False,
) -> T:
    """Runs the agent package corvo.agents.<agent> on input, in a container of
    its own, and returns its output.

    workdir, when given, must be a directory below <agent root>/workdirs; it
    is mounted at /workspace, read-only unless writes_workdir.
    """
    started = time.monotonic()
    runtime = current()
    if workdir is not None:
        try:
            workdir = check_workdir(runtime.root, workdir)
        except InvalidWorkdir as error:
            raise AgentFailed(str(error)) from None
    run = Run(
        deployment=runtime.deployment,
        run_id=ctx.workflow_run_id,
        task_run_id=ctx.task_run_id,
        attempt=ctx.retry_count,
        agent=agent,
    )
    if run.attempt > 0:
        await guard_rerun(runtime, run)

    request = AgentRequest(
        agent=agent,
        input=input.model_dump(mode="json"),
        budget_seconds=session_budget(time.monotonic() - started),
    )
    try:
        framed = encode(request.model_dump_json().encode())
    except FrameError as error:
        raise AgentFailed(f"agent {agent}'s request is too large: {error}") from None
    calls = Calls()
    attachment = Attachment()
    try:
        runtime.in_flight.add(run.task_run_id)
        spec = container_spec(
            image=runtime.image,
            name=run.name,
            labels=run.labels,
            command=["run"],
            workdir=workdir,
            writes_workdir=writes_workdir,
            credential=runtime.credential,
        )
        container = await calls(runtime.client.containers.create, **spec)
        await calls(attachment.open, client=runtime.client, container=run.name)
        await calls(container.start)
        try:
            await calls(attachment.write, data=framed)
        except TimeoutError:
            raise AgentFailed(
                f"agent {agent}'s container did not read its request within "
                f"{REQUEST_WRITE_TIMEOUT} seconds"
            ) from None
        except ConnectionError:
            # It exited before reading: its exit and envelope tell.
            pass
        exit_code, oom_killed, stdout = await asyncio.to_thread(
            follow, container, attachment, ctx.log
        )
        return conclude(agent, stdout, exit_code, oom_killed, output, ctx.log)
    finally:
        await shielded(clean_up(runtime, run, attachment, calls, ctx.log))


async def clean_up(
    runtime: Runtime,
    run: Run,
    attachment: Attachment,
    calls: Calls,
    log: Callable[[str], None],
) -> None:
    """Removes the run's container within CLEANUP_TIMEOUT.
    A failure, the timeout included, is logged, not raised: it must not hide
    how the run itself ended. The run then stays in flight, for the SIGTERM
    hook to retry."""
    try:
        async with asyncio.timeout(CLEANUP_TIMEOUT):
            await remove_run(
                runtime.client, task_run_label(run.task_run_id), attachment, calls
            )
        runtime.in_flight.discard(run.task_run_id)
    except Exception as error:
        log(f"agent {run.agent}: cleanup failed: {type(error).__name__}: {error}")
