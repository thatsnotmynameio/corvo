"""The dir-summary agent's custom tool, the example to copy for a new one.

A custom tool runs in the agent worker's own process, outside every sandbox
(R30), so whatever the model passes it is untrusted:

- Its logic lives in the core twin, corvo.core.agents.dir_summary, as a pure
  function over plain values. The tool only adapts it to the SDK: it reads
  the arguments and wraps the result in the SDK's tool-result shape.
- It takes values, never a path. The worker sees its own files, and a
  symlink in a working directory resolves against them, so a tool that
  opened a path the model chose could read the worker's secrets.
- It is async and does no blocking work: it runs on the worker's event loop,
  and a blocked loop starves the worker's heartbeats to Hatchet.

The agent serves its tools from one in-process MCP server, named after the
agent, and allows each by its mcp__<server>__<tool> name.
"""

from typing import Any

from claude_agent_sdk import McpSdkServerConfig, create_sdk_mcp_server, tool

from corvo.core.agents import dir_summary

SERVER = "dir_summary"


@tool("count_words", "Counts the words in a text.", {"text": str})
async def count_words(arguments: dict[str, Any]) -> dict[str, Any]:
    count = dir_summary.count_words(arguments["text"])
    return {"content": [{"type": "text", "text": str(count)}]}


TOOLS = [count_words]


def server() -> McpSdkServerConfig:
    """The agent's MCP server, a new one for each session."""
    return create_sdk_mcp_server(SERVER, tools=TOOLS)


# The name each tool is allowed by.
ALLOWED = [f"mcp__{SERVER}__{each.name}" for each in TOOLS]
