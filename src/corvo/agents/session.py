"""The result rule every agent applies to its session.

An agent builds its ClaudeAgentOptions and calls query() itself, then hands
the messages query() yields to consume. consume only reads them: it wraps and
replaces no SDK call.

A run succeeds only when its last result is not an error, its subtype is
success, and its structured_output validates. Anything else raises
AgentRunFailed, carrying what the session reported: the turn or budget
limit (an error result, then ResultError), an API failure (a success result
with is_error, then ResultError), a result with no structured output, or a
CLI that exits without a result (ProcessError).
"""

import sys
from collections.abc import AsyncIterator

from claude_agent_sdk import Message, ProcessError, ResultMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from corvo.agents.envelope import AgentRunFailed, RunReport


async def consume[T: BaseModel](
    messages: AsyncIterator[Message], schema: type[T]
) -> tuple[T, RunReport]:
    """The session's structured output, validated as schema, and its report."""
    session_id: str | None = None
    result: ResultMessage | None = None
    try:
        async for message in messages:
            if isinstance(message, SystemMessage) and message.subtype == "init":
                session_id = message.data.get("session_id")
                # The worker logs it before the run ends, or without an end.
                print(f"session {session_id}", file=sys.stderr, flush=True)
            elif isinstance(message, ResultMessage):
                result = message
    except ProcessError as error:
        # ResultError follows an error result, which the checks below read.
        if result is None or not result.is_error:
            raise AgentRunFailed(
                "process_failed", RunReport(session_id=session_id)
            ) from error

    if result is None:
        raise AgentRunFailed("no_result", RunReport(session_id=session_id))
    report = RunReport(
        subtype=result.subtype,
        num_turns=result.num_turns,
        total_cost_usd=result.total_cost_usd,
        session_id=result.session_id,
    )
    if result.subtype != "success":
        raise AgentRunFailed(result.subtype, report)
    if result.is_error:
        raise AgentRunFailed("api_error", report)
    if result.structured_output is None:
        raise AgentRunFailed("no_structured_output", report)
    try:
        output = schema.model_validate(result.structured_output)
    except ValidationError as error:
        raise AgentRunFailed("invalid_structured_output", report) from error
    return output, report
