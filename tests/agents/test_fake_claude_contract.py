"""The fake claude CLI keeps the contract of the SDK's real transport.

Each test runs the fake through the SDK's own subprocess transport, via
cli_path, so a protocol change in an SDK bump fails here. Each runs under a
20-second timeout, so such a change fails fast instead of hanging.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import (
    ClaudeAgentOptions,
    Message,
    ResultError,
    ResultMessage,
    create_sdk_mcp_server,
    query,
    tool,
)

from corvo.agents.tone.models import ToneVerdict

FAKE = Path(__file__).with_name("fake_claude.py")
TIMEOUT = 20


async def collect(prompt: str, options: ClaudeAgentOptions) -> list[Message]:
    messages = []
    async with asyncio.timeout(TIMEOUT):
        async for message in query(prompt=prompt, options=options):
            messages.append(message)
    return messages


def last_result(messages: list[Message]) -> ResultMessage:
    result = messages[-1]
    assert isinstance(result, ResultMessage)
    return result


@pytest.mark.fake_cli
async def test_a_success_carries_the_canned_structured_output() -> None:
    stderr: list[str] = []
    options = ClaudeAgentOptions(
        cli_path=FAKE,
        max_turns=3,
        output_format={
            "type": "json_schema",
            "schema": ToneVerdict.model_json_schema(),
        },
        stderr=stderr.append,
    )

    result = last_result(await collect("Thanks a lot!", options))

    assert (result.subtype, result.is_error) == ("success", False)
    assert ToneVerdict.model_validate(result.structured_output).tone == "friendly"
    [seen] = [json.loads(line) for line in stderr]
    assert "--max-turns" in seen["argv"]
    assert seen["credentials"] == []


@pytest.mark.fake_cli
async def test_the_turn_limit_ends_in_an_error_result_then_result_error() -> None:
    messages: list[Message] = []

    with pytest.raises(ResultError) as error:
        async with asyncio.timeout(TIMEOUT):
            async for message in query(
                prompt="fake:max-turns",
                options=ClaudeAgentOptions(cli_path=FAKE, max_turns=3),
            ):
                messages.append(message)

    assert error.value.subtype == "error_max_turns"
    result = last_result(messages)
    assert (result.subtype, result.is_error, result.num_turns) == (
        "error_max_turns",
        True,
        3,
    )


@pytest.mark.fake_cli
async def test_an_api_error_is_a_success_result_with_is_error() -> None:
    messages: list[Message] = []

    with pytest.raises(ResultError):
        async with asyncio.timeout(TIMEOUT):
            async for message in query(
                prompt="fake:api-error", options=ClaudeAgentOptions(cli_path=FAKE)
            ):
                messages.append(message)

    result = last_result(messages)
    assert (result.subtype, result.is_error) == ("success", True)


@pytest.mark.fake_cli
async def test_a_custom_tool_is_called_through_the_sdk() -> None:
    @tool("shout", "Upper-cases a text.", {"text": str})
    async def shout(arguments: dict[str, Any]) -> dict[str, Any]:
        return {"content": [{"type": "text", "text": arguments["text"].upper()}]}

    options = ClaudeAgentOptions(
        cli_path=FAKE,
        mcp_servers={"words": create_sdk_mcp_server("words", tools=[shout])},
    )

    result = last_result(await collect('fake:call words shout {"text": "hi"}', options))

    assert result.result == "HI"


@pytest.mark.fake_cli
async def test_a_hanging_session_ends_at_the_caller_s_timeout() -> None:
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(1):
            async for _ in query(
                prompt="fake:hang", options=ClaudeAgentOptions(cli_path=FAKE)
            ):
                pass
