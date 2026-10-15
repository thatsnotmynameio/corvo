"""The isolation every agent's options carry, which each agent's test checks.

Each agent sets these options itself, with the SDK's own names, so no corvo
options builder stands between an agent and its SDK (R4, KTD3). This check
is the one shared place that says what they must be: the options the agent
owns, and the values its Session supplies, passed on unchanged.
"""

from typing import Any, cast

from claude_agent_sdk import ClaudeAgentOptions

from corvo.agents.session import Session

# Tools that fetch from the network, refused until a network decision covers
# what the engine itself may reach (KTD24).
NETWORK_TOOLS = {"WebFetch", "WebSearch"}


def assert_isolated(options: ClaudeAgentOptions, session: Session) -> None:
    # The built-ins the agent lists, and no other.
    assert isinstance(options.tools, list)
    assert not NETWORK_TOOLS & {*options.tools, *options.allowed_tools}
    # Every tool call allowed_tools does not list is denied.
    assert options.permission_mode == "dontAsk"
    # No settings, CLAUDE.md or skills from the host or the working directory.
    assert options.setting_sources == []
    assert options.skills == []
    # No MCP server but the agent's own.
    assert options.strict_mcp_config
    # Every agent declares its model and its limits (R10).
    assert options.model
    assert options.max_turns is not None and options.max_turns > 0
    assert options.max_budget_usd is not None and options.max_budget_usd > 0

    # The session's values, as the session piece built them.
    assert options.cli_path == session.cli_path
    assert options.cwd == session.cwd
    assert options.env == session.env
    assert options.stderr == session.stderr
    assert options.sandbox == session.sandbox
    # Its sandbox: always on, never bypassed, failing where it cannot start.
    # The SDK's type lacks failIfUnavailable, so this reads it as a dict.
    sandbox = cast(dict[str, Any], options.sandbox)
    assert sandbox["enabled"] is True
    assert sandbox["failIfUnavailable"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert not sandbox.get("excludedCommands")
    assert not sandbox.get("enableWeakerNestedSandbox")
    assert sandbox["network"].get("allowedDomains", []) == []
