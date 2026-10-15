"""The session piece runs one session from the working directory's check to
the cgroup's removal, with the agent and the cgroup tree replaced (R23)."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pytest
from hatchet_sdk import Context
from pydantic import BaseModel

from corvo.agents.report import AgentRunFailed, RunReport
from corvo.agents.session import Session, sandbox_settings
from corvo.settings import get_settings
from corvo.worker.agent_runtime import cgroups, sessions
from corvo.worker.agent_runtime.sandbox import PLACEHOLDER
from corvo.worker.agent_runtime.sessions import (
    MAX_LINE,
    MAX_LINES,
    STDERR_PREFIX,
    WRAPPER,
    AgentFailed,
    run_agent,
    session_budget,
)

from .fake_cgroups import Tree

REPORT = RunReport(
    subtype="success", num_turns=2, total_cost_usd=0.0042, session_id="s-1"
)


class Note(BaseModel):
    text: str


@dataclass
class FakeContext:
    """What the session piece reads of Hatchet's Context."""

    task_name: str = "tone"
    task_run_id: str = "task-1"
    retry_count: int = 0
    lines: list[str] = field(default_factory=list)

    def log(self, line: str) -> None:
        self.lines.append(line)


class Agent:
    """An agent's run, which records the Session it got and then does what
    the test gives it."""

    def __init__(
        self, act: Callable[[Session], object] | None = None, tree: Tree | None = None
    ) -> None:
        self.act = act
        self.tree = tree
        self.sessions: list[Session] = []
        self.started = asyncio.Event()

    async def __call__(self, input: Note, session: Session) -> tuple[Note, RunReport]:
        self.sessions.append(session)
        self.started.set()
        if self.act is not None:
            acted = self.act(session)
            if asyncio.iscoroutine(acted):
                await acted
        return Note(text=input.text.upper()), REPORT

    async def hang(self) -> None:
        """Waits until cancelled, then records its own cleanup."""
        try:
            await asyncio.Event().wait()
        finally:
            assert self.tree is not None
            self.tree.events.append("agent cleanup")


async def run(agent: Agent, ctx: FakeContext | None = None, **options: object) -> Note:
    given = FakeContext() if ctx is None else ctx
    return await run_agent(agent, Note(text="hi"), cast(Context, given), **options)  # type: ignore[arg-type]


def raising(error: BaseException) -> Callable[[Session], object]:
    def act(session: Session) -> None:
        raise error

    return act


async def test_a_session_returns_its_output_and_leaves_no_cgroup(tree: Tree) -> None:
    ctx = FakeContext()

    output = await run(Agent(), ctx)

    assert output == Note(text="HI")
    assert ctx.lines[-1] == "agent tone: succeeded, cost=0.0042 turns=2 session=s-1"
    assert tree.path == tree.root / "run-task-1"
    assert tree.events == ["create", "kill", "remove"]
    # Their values are test_cgroups.py's.
    assert tree.removed == cgroups.LIMITS
    assert sessions.in_flight == set()


async def test_the_session_carries_the_run_s_values(tree: Tree) -> None:
    agent = Agent()

    await run(agent)

    [session] = agent.sessions
    assert session.cli_path == WRAPPER
    assert session.cwd is None
    assert session.sandbox == sandbox_settings()
    assert session.env == {
        "CORVO_SANDBOX_CGROUP": str(tree.root / "run-task-1"),
        "CORVO_SANDBOX_WORKDIR": "",
        "CORVO_SANDBOX_WRITES": "0",
        "CORVO_SANDBOX_ENGINE": "/opt/corvo/engine/claude",
        "CORVO_SANDBOX_TMPFS": str(512 * 1024**2),
        "ANTHROPIC_BASE_URL": "http://proxy:8080",
        "ANTHROPIC_API_KEY": PLACEHOLDER,
    }


async def test_an_oauth_token_s_placeholder_is_the_only_credential(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORVO_AGENT_CREDENTIAL_KIND", "oauth_token")
    get_settings.cache_clear()
    agent = Agent()

    await run(agent)

    [session] = agent.sessions
    assert session.env["CLAUDE_CODE_OAUTH_TOKEN"] == PLACEHOLDER
    assert "ANTHROPIC_API_KEY" not in session.env


async def test_a_working_directory_below_the_root_is_the_session_s(
    tree: Tree, tmp_path: Path
) -> None:
    workdir = tmp_path / "root" / "workdirs" / "issue-7"
    workdir.mkdir()
    agent = Agent()

    await run(agent, workdir="issue-7", writes_workdir=True)

    [session] = agent.sessions
    assert session.cwd == workdir
    assert session.env["CORVO_SANDBOX_WORKDIR"] == str(workdir)
    assert session.env["CORVO_SANDBOX_WRITES"] == "1"


@pytest.mark.parametrize(
    "name",
    ["", ".", "/etc", "../other", "outside", "missing", "file"],
    ids=[
        "empty",
        "the working directories",
        "absolute",
        "leaves them",
        "a link out",
        "missing",
        "not a directory",
    ],
)
async def test_a_working_directory_elsewhere_fails_before_any_cgroup(
    tree: Tree, tmp_path: Path, name: str
) -> None:
    workdirs = tmp_path / "root" / "workdirs"
    (tmp_path / "root" / "other").mkdir()
    (workdirs / "outside").symlink_to(tmp_path / "root" / "other")
    (workdirs / "file").write_text("")
    agent = Agent()

    with pytest.raises(AgentFailed, match="agent tone: "):
        await run(agent, workdir=name)

    assert tree.events == []
    assert agent.sessions == []


async def test_a_working_directory_without_a_root_fails(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORVO_AGENT_ROOT", "")
    get_settings.cache_clear()

    with pytest.raises(AgentFailed, match="CORVO_AGENT_ROOT is not set"):
        await run(Agent(), workdir="issue-7")

    assert tree.events == []


async def test_a_re_run_fails_before_any_cgroup(tree: Tree) -> None:
    agent = Agent()

    with pytest.raises(AgentFailed, match="re-run .* Trigger a new run"):
        await run(agent, FakeContext(retry_count=1))

    assert tree.events == []
    assert agent.sessions == []


async def test_a_failed_session_fails_the_run_with_its_report(tree: Tree) -> None:
    ctx = FakeContext()
    report = RunReport(
        subtype="error_max_turns", num_turns=3, total_cost_usd=0.01, session_id="s-1"
    )

    with pytest.raises(AgentFailed, match="^agent tone failed: error_max_turns$"):
        await run(Agent(raising(AgentRunFailed("error_max_turns", report))), ctx)

    assert ctx.lines[-1] == (
        "agent tone: error_max_turns, cost=0.01 turns=3 session=s-1"
    )
    assert tree.events == ["create", "kill", "remove"]


async def test_an_oom_kill_is_the_failure_s_reason(tree: Tree) -> None:
    tree.oom = 1
    ctx = FakeContext()
    report = RunReport(session_id="s-1")

    with pytest.raises(AgentFailed, match="out of memory"):
        await run(Agent(raising(AgentRunFailed("process_failed", report))), ctx)

    assert ctx.lines[-1] == (
        "agent tone: out of memory, cost=unknown turns=unknown session=s-1"
    )


async def test_any_other_error_fails_the_run_without_its_message(
    tree: Tree,
) -> None:
    ctx = FakeContext()

    with pytest.raises(AgentFailed) as failed:
        await run(Agent(raising(Exception("engine said: secret"))), ctx)

    assert str(failed.value) == "agent tone failed: Exception"
    assert not any("secret" in line for line in ctx.lines)
    assert tree.events == ["create", "kill", "remove"]


async def test_a_session_past_its_budget_is_killed_before_its_cleanup(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "session_budget", lambda elapsed: 0.01)
    agent = Agent(tree=tree)
    agent.act = lambda session: agent.hang()

    with pytest.raises(AgentFailed, match="past its session budget"):
        await run(agent)

    assert tree.events == ["create", "kill", "kill", "agent cleanup", "remove"]


async def test_a_cancel_kills_the_cgroup_before_the_agent_s_cleanup(
    tree: Tree,
) -> None:
    ctx = FakeContext()
    agent = Agent(tree=tree)
    agent.act = lambda session: agent.hang()
    running = asyncio.create_task(run(agent, ctx))
    await agent.started.wait()

    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert tree.events == ["create", "kill", "kill", "agent cleanup", "remove"]
    assert ctx.lines[-1] == (
        "agent tone: cancelled, cost=unknown turns=unknown session=unknown"
    )
    assert sessions.in_flight == set()


async def test_a_cancel_before_the_agent_starts_still_removes_the_cgroup(
    tree: Tree,
) -> None:
    agent = Agent()

    def cancel() -> None:
        # The cancel lands at the piece's first await, its wait on the agent,
        # which the agent's task reaches only for its first step.
        task = asyncio.current_task()
        assert task is not None
        task.cancel()

    tree.after_create = cancel

    with pytest.raises(asyncio.CancelledError):
        await asyncio.create_task(run(agent))

    assert tree.events == ["create", "kill", "remove"]
    assert sessions.in_flight == set()


async def test_a_cancel_during_the_end_still_ends_the_log_with_the_report(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "POLL_INTERVAL", 0)
    ctx = FakeContext()
    running = asyncio.create_task(run(Agent(), ctx))
    polls = iter([True])

    def cancel_on_first_poll() -> bool:
        # The session has ended with its output; the cancel lands at the
        # piece's wait on its end.
        populated = next(polls, False)
        if populated:
            running.cancel()
        return populated

    monkeypatch.setattr(tree, "populated", cancel_on_first_poll)

    with pytest.raises(asyncio.CancelledError):
        await running
    # The end goes on after the task, and its report line follows it.
    async with asyncio.timeout(1):
        while "remove" not in tree.events:
            await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert ctx.lines[-1] == "agent tone: cancelled, cost=0.0042 turns=2 session=s-1"


async def test_the_cgroup_is_killed_on_every_poll_while_the_agent_closes(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "POLL_INTERVAL", 0.01)
    monkeypatch.setattr(sessions, "session_budget", lambda elapsed: 0.01)

    async def close_slowly(session: Session) -> None:
        # As the SDK's transport close waits for the engine to exit.
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0.05)
            tree.events.append("agent closed")

    with pytest.raises(AgentFailed, match="past its session budget"):
        await run(Agent(close_slowly))

    closed = tree.events.index("agent closed")
    assert tree.events[closed:] == ["agent closed", "remove"]
    assert tree.events[:closed].count("kill") >= 3


async def test_a_process_joining_after_the_kill_is_killed_by_a_poll(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "POLL_INTERVAL", 0)
    tree.polls = [True, True]

    await run(Agent())

    assert tree.events == ["create", "kill", "kill", "kill", "remove"]


async def test_a_cgroup_that_never_empties_is_left_and_the_run_keeps_its_failure(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sessions, "CLEANUP_TIMEOUT", 0.05)
    monkeypatch.setattr(sessions, "POLL_INTERVAL", 0.01)
    monkeypatch.setattr(tree, "populated", lambda: True)
    ctx = FakeContext()
    report = RunReport(subtype="error_max_turns")

    with pytest.raises(AgentFailed, match="error_max_turns"):
        await run(Agent(raising(AgentRunFailed("error_max_turns", report))), ctx)

    assert "remove" not in tree.events
    assert sessions.in_flight == {tree.path}
    assert "agent tone: cleanup failed: TimeoutError: " in ctx.lines
    assert "agent tone: run-task-1 is left for the next start's sweep" in ctx.lines
    assert ctx.lines[-1].startswith("agent tone: error_max_turns, ")


async def test_a_cgroup_that_cannot_be_made_fails_the_run(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(root: Path, task_run_id: str) -> Tree:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(cgroups, "create", refuse)
    agent = Agent()

    with pytest.raises(AgentFailed, match="cannot create its cgroup"):
        await run(agent)

    assert agent.sessions == []


async def test_a_first_kill_that_fails_is_retried_by_the_end(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    kills = iter([OSError(16, "Device or resource busy")])

    def kill() -> None:
        error = next(kills, None)
        if error is not None:
            raise error
        tree.events.append("kill")

    monkeypatch.setattr(tree, "kill", kill)
    monkeypatch.setattr(sessions, "POLL_INTERVAL", 0)
    tree.polls = [True]

    await run(Agent())

    assert tree.events == ["create", "kill", "remove"]


async def test_a_cgroup_that_cannot_be_removed_is_left(
    tree: Tree, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse() -> None:
        raise OSError(16, "Device or resource busy")

    monkeypatch.setattr(tree, "remove", refuse)
    ctx = FakeContext()

    assert await run(Agent(), ctx) == Note(text="HI")

    assert sessions.in_flight == {tree.path}
    assert (
        "agent tone: cleanup failed: OSError: [Errno 16] Device or resource busy"
        in ctx.lines
    )
    assert "agent tone: run-task-1 is left for the next start's sweep" in ctx.lines


async def test_the_session_is_in_flight_until_its_cgroup_is_removed(
    tree: Tree,
) -> None:
    seen: list[set[Path]] = []

    await run(Agent(lambda session: seen.append(set(sessions.in_flight))))

    assert seen == [{tree.root / "run-task-1"}]
    assert sessions.in_flight == set()


async def test_stderr_reaches_the_log_behind_its_prefix_up_to_the_cap(
    tree: Tree,
) -> None:
    ctx = FakeContext()

    def print_lines(session: Session) -> None:
        for _ in range(MAX_LINES + 50):
            session.stderr("x" * (MAX_LINE + 20))

    await run(Agent(print_lines), ctx)

    forwarded = [line for line in ctx.lines if line.startswith(STDERR_PREFIX)]
    assert forwarded == [STDERR_PREFIX + "x" * MAX_LINE] * MAX_LINES
    assert ctx.lines[-1].startswith("agent tone: succeeded, ")


async def test_control_characters_never_reach_the_log(tree: Tree) -> None:
    ctx = FakeContext()

    def print_escapes(session: Session) -> None:
        session.stderr("\x1b[2Jcleared\x07")
        session.log("session \x1b]0;title\x07s-1")
        raise AgentRunFailed("bad\x1b[31m\nreason", RunReport(session_id="s\x1b-1"))

    with pytest.raises(AgentFailed) as failed:
        await run(Agent(print_escapes), ctx)

    assert str(failed.value) == "agent tone failed: bad[31mreason"
    assert ctx.lines == [
        "agent stderr: [2Jcleared",
        "session ]0;titles-1",
        "agent tone: bad[31mreason, cost=unknown turns=unknown session=s-1",
    ]


def test_the_session_budget_ends_a_minute_before_hatchet_s_timeout() -> None:
    assert session_budget(0) == 14 * 60
    assert session_budget(100) == 14 * 60 - 100
