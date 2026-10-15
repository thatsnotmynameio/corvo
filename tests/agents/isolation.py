"""The isolation every agent's options carry, which each agent's test checks.

Each agent sets these options itself, with the SDK's own names, so no corvo
options builder stands between an agent and its SDK (R4, KTD3). This check
is the one shared place that says what they must be.
"""

from claude_agent_sdk import ClaudeAgentOptions


def assert_isolated(options: ClaudeAgentOptions) -> None:
    # The built-ins the agent lists, and no other.
    assert isinstance(options.tools, list)
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
