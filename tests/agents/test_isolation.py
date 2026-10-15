from dataclasses import replace
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions

from agents.isolation import assert_isolated
from agents.scripted import session
from corvo.agents.session import Session, sandbox_settings


def isolated(given: Session) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cli_path=given.cli_path,
        cwd=given.cwd,
        env=given.env,
        sandbox=given.sandbox,
        stderr=given.stderr,
        model="claude-haiku-5-5",
        tools=["Read"],
        allowed_tools=["Read"],
        permission_mode="dontAsk",
        setting_sources=[],
        skills=[],
        strict_mcp_config=True,
        max_turns=3,
        max_budget_usd=0.05,
    )


def test_options_that_carry_both_halves_pass() -> None:
    given = session()

    assert_isolated(isolated(given), given)


@pytest.mark.parametrize(
    "changes",
    [
        {"tools": ["Read", "WebFetch"]},
        {"tools": ["WebSearch"], "allowed_tools": ["WebSearch"]},
        {"tools": None},
        {"cli_path": None},
        {"env": {}},
        {"sandbox": None},
        {"sandbox": {**sandbox_settings(), "allowUnsandboxedCommands": True}},
        {"sandbox": {**sandbox_settings(), "network": {"allowedDomains": ["x.io"]}}},
    ],
    ids=[
        "web fetch",
        "web search",
        "every built-in",
        "no wrapper",
        "no run values",
        "no sandbox",
        "unsandboxed commands",
        "a network allowlist",
    ],
)
def test_options_missing_either_half_fail(changes: dict[str, Any]) -> None:
    given = session()
    options = replace(isolated(given), **changes)

    with pytest.raises(AssertionError):
        assert_isolated(options, given)
