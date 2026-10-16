from dataclasses import replace
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, SandboxSettings

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


def weakened(**changes: Any) -> SandboxSettings:
    sandbox: dict[str, Any] = {**sandbox_settings(), **changes}
    return sandbox  # type: ignore[return-value]


def test_options_that_carry_both_halves_pass() -> None:
    given = session()

    assert_isolated(isolated(given), given)


@pytest.mark.parametrize(
    "changes",
    [
        {"tools": ["Read", "WebFetch"]},
        {"tools": ["WebSearch"], "allowed_tools": ["WebSearch"]},
        {"tools": None},
        {"permission_mode": "default"},
        {"setting_sources": ["project"]},
        {"skills": None},
        {"strict_mcp_config": False},
        {"model": None},
        {"max_turns": 0},
        {"max_budget_usd": None},
        {"cli_path": None},
        {"env": {}},
        {"sandbox": None},
    ],
    ids=[
        "web fetch",
        "web search",
        "every built-in",
        "permission prompts",
        "settings from disk",
        "every skill",
        "other MCP servers",
        "no model",
        "no turns",
        "no budget",
        "no wrapper",
        "no run values",
        "not the session's sandbox",
    ],
)
def test_options_that_drop_a_value_fail(changes: dict[str, Any]) -> None:
    given = session()
    options = replace(isolated(given), **changes)

    with pytest.raises(AssertionError):
        assert_isolated(options, given)


@pytest.mark.parametrize(
    "sandbox",
    [
        weakened(enabled=False),
        weakened(failIfUnavailable=False),
        weakened(allowUnsandboxedCommands=True),
        weakened(excludedCommands=["git"]),
        weakened(enableWeakerNestedSandbox=True),
        weakened(network={"allowedDomains": ["x.io"]}),
        weakened(network={}),
    ],
    ids=[
        "off",
        "runs unsandboxed when it cannot start",
        "unsandboxed commands",
        "excluded commands",
        "weaker nested sandbox",
        "a network allowlist",
        "no network allowlist",
    ],
)
def test_a_session_with_a_weaker_sandbox_fails(sandbox: SandboxSettings) -> None:
    # The options carry the session's own sandbox, so the sandbox's content
    # is what fails, not a mismatch with the session.
    given = replace(session(), sandbox=sandbox)

    with pytest.raises(AssertionError):
        assert_isolated(isolated(given), given)
