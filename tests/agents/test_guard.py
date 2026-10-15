"""No test reaches Claude: the guard in tests/conftest.py fails any test that
runs the SDK without replacing it, before the SDK starts its CLI."""

import os
from typing import Any

import anyio
import pytest
from claude_agent_sdk import query
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport


async def test_running_the_sdk_unreplaced_fails_the_test(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Only records a process the SDK would start, so the test never runs the
    # real CLI, which would reach Claude on the developer's own login.
    started: list[Any] = []

    async def open_process(command: Any, **options: Any) -> None:
        started.append(command)
        raise AssertionError("the SDK started a process")

    monkeypatch.setattr(anyio, "open_process", open_process)

    with pytest.raises(pytest.fail.Exception, match=request.node.nodeid):
        async for _ in query(prompt="Say hi."):
            pass

    assert started == []


def test_no_credential_reaches_the_tests() -> None:
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in os.environ
    assert os.environ["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:9"


@pytest.mark.fake_cli
def test_the_fake_cli_marker_keeps_the_real_transport() -> None:
    connect = SubprocessCLITransport.connect

    assert connect.__qualname__ == "SubprocessCLITransport.connect"
