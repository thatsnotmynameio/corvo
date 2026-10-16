"""The fake claude CLI keeps the contract of the SDK's real transport.

Each test runs the fake through the SDK's own subprocess transport, via
cli_path, so a protocol change in an SDK bump fails here. Each runs under a
20-second timeout, so such a change fails fast instead of hanging.
"""

import asyncio
import json
import os
import threading
from http.server import ThreadingHTTPServer
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

from corvo.agents.session import sandbox_settings
from corvo.agents.tone.models import ToneVerdict

from .scripted_api import handler

FAKE = Path(__file__).with_name("fake_claude.py")
TIMEOUT = 20
# Whatever credential the environment holds, the fake sends it.
PLACEHOLDER = "a-placeholder"


async def collect(
    prompt: str, options: ClaudeAgentOptions, messages: list[Message] | None = None
) -> list[Message]:
    """The session's messages, gathered into messages when given, so a test
    still has them after query() raises."""
    gathered = [] if messages is None else messages
    async with asyncio.timeout(TIMEOUT):
        async for message in query(prompt=prompt, options=options):
            gathered.append(message)
    return gathered


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
    assert not {"ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"} & set(seen["names"])


@pytest.mark.fake_cli
async def test_the_session_s_sandbox_reaches_the_engine_s_settings(
    tmp_path: Path,
) -> None:
    stderr: list[str] = []
    options = ClaudeAgentOptions(
        cli_path=FAKE, cwd=tmp_path, sandbox=sandbox_settings(), stderr=stderr.append
    )

    await collect("Thanks a lot!", options)

    [seen] = [json.loads(line) for line in stderr]
    argv = seen["argv"]
    settings = json.loads(argv[argv.index("--settings") + 1])
    assert settings["sandbox"]["failIfUnavailable"] is True
    assert settings["sandbox"]["allowUnsandboxedCommands"] is False
    # What the integration stack reads of the engine's surroundings.
    assert seen["writable"] is True
    assert os.getpid() in {process["pid"] for process in seen["processes"]}


@pytest.mark.fake_cli
async def test_the_turn_limit_ends_in_an_error_result_then_result_error() -> None:
    messages: list[Message] = []

    with pytest.raises(ResultError) as error:
        await collect(
            "fake:max-turns", ClaudeAgentOptions(cli_path=FAKE, max_turns=3), messages
        )

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
        await collect("fake:api-error", ClaudeAgentOptions(cli_path=FAKE), messages)

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
@pytest.mark.parametrize(
    ("variable", "headers"),
    [
        ("ANTHROPIC_API_KEY", {"X-Api-Key": PLACEHOLDER}),
        (
            "CLAUDE_CODE_OAUTH_TOKEN",
            {
                "Authorization": f"Bearer {PLACEHOLDER}",
                "Anthropic-Beta": "oauth-2025-04-20",
            },
        ),
    ],
)
async def test_an_api_call_sends_the_credential_as_the_engine_does(
    tmp_path: Path, variable: str, headers: dict[str, str]
) -> None:
    log = tmp_path / "log.jsonl"
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler([], log))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    address = f"127.0.0.1:{server.server_address[1]}"
    options = ClaudeAgentOptions(
        cli_path=FAKE,
        env={variable: PLACEHOLDER, "ANTHROPIC_BASE_URL": f"http://{address}"},
        output_format={
            "type": "json_schema",
            "schema": ToneVerdict.model_json_schema(),
        },
    )
    try:
        result = last_result(await collect("fake:api", options))
    finally:
        server.shutdown()
        server.server_close()

    assert ToneVerdict.model_validate(result.structured_output).tone == "friendly"
    (entry,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert (entry["method"], entry["path"]) == ("POST", "/v1/messages")
    assert entry["headers"] == headers | {"Host": address}


@pytest.mark.fake_cli
async def test_a_hanging_session_ends_at_the_caller_s_timeout() -> None:
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(1):
            async for _ in query(
                prompt="fake:hang", options=ClaudeAgentOptions(cli_path=FAKE)
            ):
                pass
