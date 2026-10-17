"""A scripted session, which an agent's unit tests put in place of query().

The tests replace query on the agent's module with a ScriptedQuery, which
yields real SDK messages and records what the agent passed it (KTD14), and
hand the agent a Session such as the session piece builds.
"""

from collections.abc import AsyncIterator
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions, Message, ResultMessage, SystemMessage

from corvo.agents.session import Session, sandbox_settings

SESSION_ID = "4f0c2b9e-session"


def session(lines: list[str] | None = None) -> Session:
    """A Session whose stderr and log lines go to lines, when given."""
    kept = [] if lines is None else lines
    return Session(
        cli_path=Path("/usr/local/bin/corvo-agent-sandbox"),
        cwd=None,
        env={"CORVO_SANDBOX_CGROUP": "/sys/fs/cgroup/agents/run-1"},
        sandbox=sandbox_settings(),
        stderr=kept.append,
        log=kept.append,
    )


def init() -> SystemMessage:
    return SystemMessage(
        subtype="init",
        data={"type": "system", "subtype": "init", "session_id": SESSION_ID},
    )


def result(
    *,
    subtype: str = "success",
    is_error: bool = False,
    structured_output: object = None,
) -> ResultMessage:
    return ResultMessage(
        subtype=subtype,
        duration_ms=1200,
        duration_api_ms=1000,
        is_error=is_error,
        num_turns=2,
        session_id=SESSION_ID,
        total_cost_usd=0.0042,
        structured_output=structured_output,
    )


class ScriptedQuery:
    """Yields its messages, then raises its error, as query() would."""

    def __init__(self, *messages: Message, error: Exception | None = None) -> None:
        self.messages = messages
        self.error = error
        self.prompts: list[str] = []
        self.options: list[ClaudeAgentOptions] = []

    def __call__(
        self, *, prompt: str, options: ClaudeAgentOptions
    ) -> AsyncIterator[Message]:
        self.prompts.append(prompt)
        self.options.append(options)
        return self.stream()

    async def stream(self) -> AsyncIterator[Message]:
        for message in self.messages:
            yield message
        if self.error is not None:
            raise self.error
