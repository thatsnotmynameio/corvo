"""The one piece of the worker that runs agent containers (R17).

run_agent runs one agent session for an agent task: it writes the request
into a fresh run directory, starts a container built by spec.container_spec
on the agents' rootless Podman, forwards its stderr to the run's log, waits
for it to exit, and reads the envelope corvo-agent wrote. Then it removes
the container and the run directory, whatever happened, cancel and timeout
included. Every agent task calls it; none starts a container itself.

What the container wrote is untrusted. The envelope is read without
following links or blocking, only when it is a regular file of at most
1 MiB, validated with the envelope model, and never echoed: an invalid one
fails the run without its content. A working directory an agent may have
written is untrusted output too: the worker runs no git, hooks, config or
code from it.

docker-py is synchronous, so each of its calls runs in a thread (KTD5). A
cancel can land while the thread that creates the container is still
running, so cleanup waits for that thread, then removes containers by the
run's label, never by the handle create returned (KTD8).
"""

import asyncio
import os
import shutil
import stat
import time
import unicodedata
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docker import DockerClient
from docker.errors import APIError, NotFound
from docker.models.containers import Container
from hatchet_sdk import Context
from pydantic import BaseModel, ValidationError

from corvo.agents.envelope import ENVELOPE, AgentRequest, Failed, RunReport, Succeeded
from corvo.worker.agent_runtime.spec import (
    MANAGED,
    Credential,
    InvalidWorkdir,
    Run,
    check_workdir,
    container_spec,
    session_budget,
)

# The largest envelope or probe report the worker reads.
MAX_UNTRUSTED_BYTES = 1024 * 1024

# Forwarded stderr: each line behind the prefix, so no line the agent prints
# passes for one of the worker's own, cut to MAX_LINE characters, up to
# MAX_LINES lines. Hatchet keeps 1000 lines a run.
STDERR_PREFIX = "agent stderr: "
MAX_LINE = 500
MAX_LINES = 900

# How long cleanup may take, under a cancel or a timeout.
CLEANUP_TIMEOUT = 30

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


class UntrustedFile(Exception):
    """A file the container wrote that the worker does not read."""


def read_untrusted(path: Path) -> bytes:
    """A regular file of at most MAX_UNTRUSTED_BYTES, read without following
    a link and without blocking, whatever the container put at path.

    Raises FileNotFoundError when there is nothing at path.
    """
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise
    except OSError as error:
        raise UntrustedFile(f"{path.name} cannot be opened") from error
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise UntrustedFile(f"{path.name} is not a regular file")
        if info.st_size > MAX_UNTRUSTED_BYTES:
            raise UntrustedFile(f"{path.name} is larger than 1 MiB")
        chunks = []
        size = 0
        while chunk := os.read(fd, 65536):
            size += len(chunk)
            if size > MAX_UNTRUSTED_BYTES:
                raise UntrustedFile(f"{path.name} is larger than 1 MiB")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def remove_tree(path: Path) -> None:
    """Removes a run directory without following any link in it."""
    if path.is_symlink():
        path.unlink()
    elif path.exists():
        # rmtree on Linux works on file descriptors, and never follows a
        # link inside the tree.
        shutil.rmtree(path)


def remove_labelled(client: DockerClient, label: str) -> int:
    """Force-removes every managed container carrying the label, and says how
    many it found. A container already gone (404) or being removed (409)
    counts as removed."""
    found = client.containers.list(all=True, filters={"label": [MANAGED, label]})
    for container in found:
        try:
            container.remove(force=True)
        except NotFound:
            pass
        except APIError as error:
            if error.status_code != 409:
                raise
    return len(found)


async def remove_in_flight(runtime: Runtime) -> None:
    """Removes the containers of this worker's in-flight agent runs."""
    for task_run_id in sorted(runtime.in_flight):
        await asyncio.to_thread(
            remove_labelled, runtime.client, f"corvo.task_run_id={task_run_id}"
        )


class Calls:
    """The calls that create and start a run's container, each in a thread
    that cleanup can wait for after a cancel."""

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
        # A line that never ends is cut, rather than held whole.
        if len(pending) > MAX_LINE * 4:
            send(pending)
            pending = b""
    if pending:
        send(pending)


def follow(container: Container, log: Callable[[str], None]) -> tuple[int, bool]:
    """Forwards the container's stderr until it exits, then gives its exit
    code and whether the kernel killed it for lack of memory."""
    forward_stderr(
        container.logs(stream=True, follow=True, stdout=False, stderr=True), log
    )
    exit_code = container.wait()["StatusCode"]
    container.reload()
    return exit_code, bool(container.attrs["State"].get("OOMKilled"))


def describe(report: RunReport) -> str:
    def shown(value: object) -> str:
        return "unknown" if value is None else printable(str(value), 100)

    return (
        f"cost={shown(report.total_cost_usd)} turns={shown(report.num_turns)} "
        f"session={shown(report.session_id)}"
    )


def conclude[T: BaseModel](
    agent: str,
    run_dir: Path,
    exit_code: int,
    oom_killed: bool,
    output: type[T],
    log: Callable[[str], None],
) -> T:
    """The run's output, from the envelope the container left, or the
    failure it reports. Logs the run's cost, turns and session ID either way.
    """
    envelope: Succeeded | Failed | None = None
    try:
        envelope = ENVELOPE.validate_json(read_untrusted(run_dir / "result.json"))
    except FileNotFoundError:
        problem = "no envelope"
    # Two clauses, not one with two types: the organization's coverage check
    # parses this file with a Python older than 3.14 (see corvo.agents.runner).
    except UntrustedFile:
        problem = "invalid envelope"
    except ValidationError:
        problem = "invalid envelope"
    if envelope is None:
        log(
            f"agent {agent}: {problem}, {describe(RunReport())} "
            f"exit_code={exit_code} oom_killed={oom_killed}"
        )
        raise AgentFailed(
            f"agent {agent} left {problem} (exit code {exit_code}, "
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


def make_run_dir(path: Path) -> None:
    """Creates the run directory, failing when it exists, with mode 0770 and
    the setgid group of the runs directory (KTD7)."""
    path.mkdir(mode=0o770)
    path.chmod(0o770 | (path.stat().st_mode & stat.S_ISGID))


def write_request(path: Path, request: AgentRequest) -> None:
    """Writes request.json, failing on anything already at path, a link
    included."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    with os.fdopen(os.open(path, flags, 0o640), "w") as file:
        file.write(request.model_dump_json())


async def guard_rerun(runtime: Runtime, run: Run) -> None:
    """Before a rerun, removes what earlier attempts left, and fails the run
    when they left anything (KTD8).

    The engine re-queues the task of a worker that stopped answering, whatever
    its retries, so an attempt's container or run directory left behind
    means its worker was lost mid-session. A replay someone asked for raises
    the retry count too, but its earlier attempt cleaned up after itself.
    """
    removed = await asyncio.to_thread(
        remove_labelled, runtime.client, f"corvo.task_run_id={run.task_run_id}"
    )
    earlier = [
        path
        for attempt in range(run.attempt)
        if os.path.lexists(
            path := runtime.root / "runs" / f"{run.task_run_id}-{attempt}"
        )
    ]
    for path in earlier:
        await asyncio.to_thread(remove_tree, path)
    if removed or earlier:
        raise AgentFailed(
            f"agent {run.agent}'s earlier attempt left its container, so its "
            "worker was lost mid-session: Hatchet re-queued it, and this run "
            "fails rather than pay for the session again"
        )


async def shielded(cleanup: Coroutine[Any, Any, None]) -> None:
    """Runs cleanup to its end within CLEANUP_TIMEOUT, even when the task is
    cancelled while it runs."""
    await asyncio.shield(
        asyncio.ensure_future(asyncio.wait_for(cleanup, CLEANUP_TIMEOUT))
    )


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

    run_dir = runtime.root / "runs" / f"{run.task_run_id}-{run.attempt}"
    try:
        make_run_dir(run_dir)
    except FileExistsError:
        raise AgentFailed(f"the run directory {run_dir} already exists") from None
    calls = Calls()
    try:
        request = AgentRequest(
            agent=agent,
            input=input.model_dump(mode="json"),
            budget_seconds=session_budget(time.monotonic() - started),
        )
        write_request(run_dir / "request.json", request)
        runtime.in_flight.add(run.task_run_id)
        spec = container_spec(
            image=runtime.image,
            run=run,
            command=["run"],
            run_dir=run_dir,
            workdir=workdir,
            writes_workdir=writes_workdir,
            credential=runtime.credential,
        )
        container = await calls(runtime.client.containers.create, **spec)
        await calls(container.start)
        exit_code, oom_killed = await asyncio.to_thread(follow, container, ctx.log)
        return conclude(agent, run_dir, exit_code, oom_killed, output, ctx.log)
    finally:
        await shielded(clean_up(runtime, run, run_dir, calls, ctx.log))


async def clean_up(
    runtime: Runtime,
    run: Run,
    run_dir: Path,
    calls: Calls,
    log: Callable[[str], None],
) -> None:
    """Removes the run's container and run directory. A failure is logged,
    not raised: it must not hide how the run itself ended."""
    try:
        await calls.settle()
        await asyncio.to_thread(
            remove_labelled, runtime.client, f"corvo.task_run_id={run.task_run_id}"
        )
        runtime.in_flight.discard(run.task_run_id)
        await asyncio.to_thread(remove_tree, run_dir)
    except Exception as error:
        log(f"agent {run.agent}: cleanup failed: {type(error).__name__}: {error}")
