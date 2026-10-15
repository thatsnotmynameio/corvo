"""The one piece of the agent worker that runs agent sessions (R17).

run_agent runs one session for an agent task, from the working directory's
check to the removal of the run's cgroup. Every agent task calls it; none
runs an agent itself.

1. It fails a re-run (KTD8), and a working directory outside
   <root>/workdirs (KTD7), before anything exists.
2. It creates the run's cgroup (corvo.worker.agent_runtime.cgroups) and
   builds the Session: the wrapper as cli_path, the wrapper's per-run
   variables and the credential's placeholder as env, and the SDK's sandbox.
3. It starts the agent's run as a child task and waits for it, bounded by
   the session budget. The wait forwards neither a cancel nor the deadline
   into the child: a cancel would start the SDK's transport close, which can
   take 15 seconds, and the kill comes first.
4. However the session ended, result, failure, budget, Hatchet's timeout or
   cancel, it kills the cgroup before anything else. Then it cancels the
   child, which lets the SDK close its transport, waits until the cgroup is
   empty, killing it again on every poll, and removes it, all shielded and
   within CLEANUP_TIMEOUT. Hatchet frees the slot a second after a cancel
   without waiting for this, which is why the kill comes first.

What a session hands back or prints is untrusted (R29): the output is the
agent's validated model, every line it prints reaches the run log behind a
prefix with its control characters stripped, and a failure's message holds
only its reason. The worker runs nothing from the working directory.

The run log always ends with the run's report line: its outcome, cost, turns
and session ID (KTD27). ctx.log also writes each line to the worker's own
log, which still reaches the operator after a cancel.
"""

import asyncio
import sys
import time
import unicodedata
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from hatchet_sdk import Context
from pydantic import BaseModel

from corvo.agents.report import AgentRunFailed, RunReport
from corvo.agents.session import Session, sandbox_settings
from corvo.settings import Settings, get_settings
from corvo.worker.agent_runtime import cgroups
from corvo.worker.agent_runtime.cgroups import Cgroup
from corvo.worker.agent_runtime.sandbox import PLACEHOLDER
from corvo.worker.defaults import (
    AGENT_DEADLINE_MARGIN,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_TMPFS_SIZE,
)

# Forwarded stderr: each line behind the prefix, so no line the engine prints
# passes for one of the worker's own, cut to MAX_LINE characters, up to
# MAX_LINES lines. Hatchet keeps 1000 lines a run, which leaves room for the
# worker's own.
STDERR_PREFIX = "agent stderr: "
MAX_LINE = 500
MAX_LINES = 900

# How long the end may take, under a cancel or a timeout, and how often it
# looks whether the cgroup has emptied.
CLEANUP_TIMEOUT = 10
POLL_INTERVAL = 0.1

# The SDK's cli_path: corvo-agent-sandbox, installed next to the worker's
# Python.
WRAPPER = Path(sys.executable).parent / "corvo-agent-sandbox"

# The variable each kind of credential's placeholder reaches the engine
# under, which the proxy replaces with the credential (KTD12).
CREDENTIAL_VARIABLES = {
    "api_key": "ANTHROPIC_API_KEY",
    "oauth_token": "CLAUDE_CODE_OAUTH_TOKEN",
}

# The cgroups of this worker's sessions that have not been removed, which
# the SIGTERM hook kills.
in_flight: set[Path] = set()

# An agent package's run (KTD1).
type AgentRun[I, O] = Callable[[I, Session], Coroutine[Any, Any, tuple[O, RunReport]]]


class AgentFailed(Exception):
    """An agent run that gave no valid output. Its message holds nothing the
    session wrote beyond its failure reason, stripped."""


class InvalidWorkdir(ValueError):
    """A working directory a run may not use."""


def printable(text: str, limit: int = MAX_LINE) -> str:
    """The text without control characters, cut to limit characters."""
    kept = "".join(c for c in text if not unicodedata.category(c).startswith("C"))
    return kept[:limit]


def check_workdir(root: str, name: str) -> Path:
    """The working directory a run's input names, resolved, when it is a
    directory strictly below <root>/workdirs once every link is followed
    (KTD7).

    The name is relative to <root>/workdirs, which itself is refused: it
    would expose every other run's.
    """
    if not root:
        raise InvalidWorkdir("CORVO_AGENT_ROOT is not set")
    workdirs = (Path(root) / "workdirs").resolve()
    shown = repr(printable(name, 100))
    if not name or Path(name).is_absolute():
        raise InvalidWorkdir(f"{shown} is not a name below {workdirs}")
    try:
        resolved = (workdirs / name).resolve(strict=True)
    except OSError:
        raise InvalidWorkdir(f"{shown} does not exist below {workdirs}") from None
    if workdirs not in resolved.parents or not resolved.is_dir():
        raise InvalidWorkdir(f"{shown} is not a directory below {workdirs}")
    return resolved


def session_budget(elapsed: float) -> float:
    """The seconds the session may take, given the seconds the task has run:
    it ends AGENT_DEADLINE_MARGIN before Hatchet's timeout."""
    return (AGENT_EXECUTION_TIMEOUT - AGENT_DEADLINE_MARGIN).total_seconds() - elapsed


def forward_stderr(log: Callable[[str], None]) -> Callable[[str], None]:
    """The SDK's stderr callback: each line to the run log, up to MAX_LINES."""
    sent = 0

    def forward(line: str) -> None:
        nonlocal sent
        if sent < MAX_LINES:
            log(STDERR_PREFIX + printable(line))
            sent += 1

    return forward


def session_env(
    settings: Settings, cgroup: Cgroup, cwd: Path | None, writes_workdir: bool
) -> dict[str, str]:
    """The wrapper's per-run variables and the credential's placeholder. The
    wrapper sets the isolation flags itself (KTD20)."""
    return {
        "CORVO_SANDBOX_CGROUP": str(cgroup.path),
        "CORVO_SANDBOX_WORKDIR": "" if cwd is None else str(cwd),
        "CORVO_SANDBOX_WRITES": "1" if writes_workdir else "0",
        "CORVO_SANDBOX_ENGINE": settings.agent_engine,
        "CORVO_SANDBOX_TMPFS": str(AGENT_TMPFS_SIZE),
        "ANTHROPIC_BASE_URL": settings.agent_proxy_url,
        CREDENTIAL_VARIABLES[settings.agent_credential_kind]: PLACEHOLDER,
    }


def report_line(agent: str, outcome: str, report: RunReport) -> str:
    def shown(value: object) -> str:
        return "unknown" if value is None else printable(str(value), 100)

    return (
        f"agent {agent}: {outcome}, cost={shown(report.total_cost_usd)} "
        f"turns={shown(report.num_turns)} session={shown(report.session_id)}"
    )


async def run_agent[I: BaseModel, O: BaseModel](
    run: AgentRun[I, O],
    input: I,
    ctx: Context,
    *,
    workdir: str | None = None,
    writes_workdir: bool = False,
) -> O:
    """Runs one session of the agent whose run is given, on input, and
    returns its output.

    workdir, when given, names a directory relative to <root>/workdirs. The
    session sees it read-only unless writes_workdir.
    """
    started = time.monotonic()
    agent = ctx.task_name
    if ctx.retry_count > 0:
        raise AgentFailed(
            f"agent {agent}: this is a re-run (retry {ctx.retry_count}), which "
            "fails rather than pay for the session again. Trigger a new run, "
            "or replay the parent step, which spawns a fresh child."
        )
    settings = get_settings()
    cwd = None
    if workdir is not None:
        try:
            cwd = check_workdir(settings.agent_root, workdir)
        except InvalidWorkdir as error:
            raise AgentFailed(f"agent {agent}: {error}") from None

    try:
        cgroup = cgroups.create(Path(settings.agent_cgroup_root), ctx.task_run_id)
    except OSError as error:
        raise AgentFailed(f"agent {agent}: cannot create its cgroup: {error}") from None
    in_flight.add(cgroup.path)
    session = Session(
        cli_path=WRAPPER,
        cwd=cwd,
        env=session_env(settings, cgroup, cwd, writes_workdir),
        sandbox=sandbox_settings(),
        stderr=forward_stderr(ctx.log),
        log=lambda line: ctx.log(printable(line)),
    )
    child = asyncio.create_task(run(input, session))
    cancelled = False
    try:
        await asyncio.wait({child}, timeout=session_budget(time.monotonic() - started))
    except asyncio.CancelledError:
        cancelled = True
        raise
    finally:
        finished = child.done()
        # First, with no await before it: after a cancel, Hatchet frees the
        # slot without waiting for what follows.
        try:
            cgroup.kill()
        except OSError:
            # The end kills again, and logs what fails.
            pass
        ending = asyncio.ensure_future(end(agent, cgroup, child, cancelled, ctx.log))
        out_of_memory = await asyncio.shield(ending)
    return conclude(agent, child, finished, out_of_memory, ctx.log)


async def end(
    agent: str,
    cgroup: Cgroup,
    child: asyncio.Task[Any],
    cancelled: bool,
    log: Callable[[str], None],
) -> bool:
    """Ends the session once its cgroup has been killed, and says whether the
    kernel killed it for lack of memory.

    A failure, the timeout included, is logged, not raised: it must not hide
    how the run itself ended. A cgroup left stays in flight, for the SIGTERM
    hook, and the next start's sweep removes it.
    """
    child.cancel()
    emptied = False
    try:
        async with asyncio.timeout(CLEANUP_TIMEOUT):
            await asyncio.wait({child})
            # A wrapper that joined just after a kill is caught by the next.
            while cgroup.populated():
                cgroup.kill()
                await asyncio.sleep(POLL_INTERVAL)
        emptied = True
    except Exception as error:
        log(f"agent {agent}: cleanup failed: {type(error).__name__}: {error}")

    out_of_memory = False
    try:
        out_of_memory = cgroup.oom_kills() > 0
        if emptied:
            cgroup.remove()
            in_flight.discard(cgroup.path)
    except Exception as error:
        log(f"agent {agent}: cleanup failed: {type(error).__name__}: {error}")
    if cgroup.path in in_flight:
        log(f"agent {agent}: {cgroup.path.name} is left for the next start's sweep")
    if cancelled:
        outcome = "out of memory" if out_of_memory else "cancelled"
        log(report_line(agent, outcome, RunReport()))
    return out_of_memory


def conclude[O](
    agent: str,
    child: asyncio.Task[tuple[O, RunReport]],
    finished: bool,
    out_of_memory: bool,
    log: Callable[[str], None],
) -> O:
    """The run's output, or the failure that ends it, after its report line."""
    if not finished:
        reason, report = "past its session budget", RunReport()
    elif isinstance(error := child.exception(), AgentRunFailed):
        reason, report = error.reason, error.report
    elif error is not None:
        # Such as the SDK's bare Exception when the engine never answers its
        # start. Its message may quote what the engine printed.
        reason, report = type(error).__name__, RunReport()
    else:
        output, report = child.result()
        log(report_line(agent, "succeeded", report))
        return output

    if out_of_memory:
        reason = "out of memory"
    log(report_line(agent, printable(reason, 100), report))
    raise AgentFailed(f"agent {agent} failed: {printable(reason, 100)}")
