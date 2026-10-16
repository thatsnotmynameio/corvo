"""The values a session runs with, and the result rule every agent applies.

The agent worker's session piece builds a Session for each run, and the
agent's run passes its values into ClaudeAgentOptions under the SDK's own
names, next to the options the agent owns (KTD1, KTD3).

An agent builds its ClaudeAgentOptions and calls query() itself, then hands
the messages query() yields to consume. consume only reads them: it wraps and
replaces no SDK call.

A run succeeds only when its last result is not an error, its subtype is
success, and its structured_output validates. Anything else raises
AgentRunFailed, carrying what the session reported: the turn or budget
limit (an error result, then ResultError), an API failure (a success result
with is_error, then ResultError), a result with no structured output, a
CLI that fails with no error result (ProcessError), even after a success, or
any other SDK failure, such as a CLI that never starts or an unreadable
message.
"""

from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from claude_agent_sdk import (
    ClaudeSDKError,
    Message,
    ProcessError,
    ResultMessage,
    SandboxSettings,
    SystemMessage,
)
from pydantic import BaseModel, ValidationError

from corvo.agents.report import AgentRunFailed, RunReport


@dataclass(frozen=True)
class Session:
    """The per-run values the session piece supplies, under the SDK's names."""

    # corvo-agent-sandbox, which starts the engine in a bubblewrap of its own.
    cli_path: Path
    # The run's working directory, None for an agent that works in none.
    cwd: Path | None
    # The wrapper's per-run variables and the credential's placeholder.
    env: dict[str, str]
    # sandbox_settings(): the wrapper refuses a session without them.
    sandbox: SandboxSettings
    # The engine's stderr lines, for the run log.
    stderr: Callable[[str], None]
    # corvo's own lines for the run log, such as the session ID.
    log: Callable[[str], None]


def sandbox_settings() -> SandboxSettings:
    """The SDK's sandbox for a session's commands: always on, never bypassed,
    failing where it cannot start, and with no network."""
    settings = {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        # Without it the engine runs commands unsandboxed when the sandbox
        # cannot start. The engine reads it, but SDK 0.2.167's type lacks it.
        "failIfUnavailable": True,
        "network": {"allowedDomains": []},
    }
    return cast(SandboxSettings, settings)


async def consume[T: BaseModel](
    messages: AsyncIterator[Message], schema: type[T], log: Callable[[str], None]
) -> tuple[T, RunReport]:
    """The session's structured output, validated as schema, and its report."""
    session_id: str | None = None
    result: ResultMessage | None = None
    try:
        async for message in messages:
            if isinstance(message, SystemMessage) and message.subtype == "init":
                session_id = message.data.get("session_id")
                # The run log holds it before the run ends, or without an end.
                log(f"session {session_id}")
            elif isinstance(message, ResultMessage):
                result = message
    except ProcessError as error:
        # ResultError follows an error result, which the checks below read.
        # Any other exit fails the run, even after a success result.
        if result is None or not result.is_error:
            raise AgentRunFailed(
                "process_failed", report(result, session_id)
            ) from error
    except ClaudeSDKError as error:
        raise AgentRunFailed("sdk_error", report(result, session_id)) from error

    if result is None:
        raise AgentRunFailed("no_result", report(result, session_id))
    run_report = report(result, session_id)
    if result.subtype != "success":
        raise AgentRunFailed(result.subtype, run_report)
    if result.is_error:
        raise AgentRunFailed("api_error", run_report)
    if result.structured_output is None:
        raise AgentRunFailed("no_structured_output", run_report)
    try:
        output = schema.model_validate(result.structured_output)
    except ValidationError as error:
        raise AgentRunFailed("invalid_structured_output", run_report) from error
    return output, run_report


def report(result: ResultMessage | None, session_id: str | None) -> RunReport:
    """What the session reported: its result's, or only the session ID the
    init message gave when no result arrived."""
    if result is None:
        return RunReport(session_id=session_id)
    return RunReport(
        subtype=result.subtype,
        num_turns=result.num_turns,
        total_cost_usd=result.total_cost_usd,
        session_id=result.session_id,
    )
