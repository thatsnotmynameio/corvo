from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeAgentOptions, SandboxSettings

from corvo.agents.session import Session, sandbox_settings
from support.isolation import assert_isolated
from support.scripted import session


def isolated(given: Session) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cli_path=given.cli_path,
        cwd=given.cwd,
        env=given.env,
        sandbox=given.sandbox,
        stderr=given.stderr,
        model="claude-haiku-5-5",
        tools=["Read"],
        allowed_tools=[],
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


WORKDIR = Path("/var/lib/corvo/agents/workdirs/issue-7")


def in_workdir(**changes: Any) -> tuple[ClaudeAgentOptions, Session]:
    given = replace(session(), cwd=WORKDIR)
    return replace(isolated(given), tools=["Read", "Glob", "Grep"], **changes), given


def test_file_reads_scoped_to_the_working_directory_pass() -> None:
    options, given = in_workdir(allowed_tools=[f"Read(/{WORKDIR}/**)"])

    assert_isolated(options, given)


@pytest.mark.parametrize(
    "allowed",
    [
        ["Read"],
        ["Glob"],
        ["Grep"],
        ["Read(**)"],
        ["Read(//var/lib/corvo/agents/**)"],
        [f"Glob(/{WORKDIR}/**)"],
    ],
    ids=[
        "Read anywhere",
        "Glob anywhere",
        "Grep anywhere",
        "Read relative",
        "Read above the working directory",
        "a Glob rule, which is never consulted",
    ],
)
def test_file_tools_allowed_beyond_the_working_directory_fail(
    allowed: list[str],
) -> None:
    options, given = in_workdir(allowed_tools=allowed)

    with pytest.raises(AssertionError):
        assert_isolated(options, given)


def test_a_file_rule_without_a_working_directory_fails() -> None:
    given = session()
    options = replace(isolated(given), allowed_tools=[f"Read(/{WORKDIR}/**)"])

    with pytest.raises(AssertionError):
        assert_isolated(options, given)
