#!/usr/bin/env python3
"""A stand-in for the claude CLI, which never reaches Claude.

The SDK runs it through cli_path, and in the integration stack the sandbox
wrapper runs it as the engine. It speaks the stream-json protocol of the
SDK's subprocess transport, after the SDK's own
tests/test_run_end_subprocess.py: it answers
-v, replies to each control_request, calls custom tools through
mcp_message, and ends the session with a result.

The prompt picks the scenario:

- with no marker, a success result, with the canned structured output of
  the JSON Schema's title, as CANNED holds it;
- fake:max-turns, an error_max_turns result, then exit 1, as the CLI does;
- fake:api-error, a success result with is_error, then exit 1;
- fake:hang, no answer at all, until the process is killed;
- fake:hog, memory taken until the process is killed, or exit 1 once it
  holds HOG_BYTES, past any session's memory limit;
- fake:call <server> <tool> <JSON arguments>, a call to that SDK MCP tool
  before the success result, whose result text is the tool's.

It prints to stderr, as one JSON line, its arguments, the isolation
variables, the name of every variable it saw, the processes its /proc lists
and whether it can write its working directory. It uses the standard
library alone, since a sandbox holds no corvo package.
"""

import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

VERSION = "99.0.0 (fake claude)"
SESSION_ID = "fake-session"

ISOLATION = (
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY",
    "ENABLE_CLAUDEAI_MCP_SERVERS",
    "CLAUDE_CONFIG_DIR",
    "HOME",
)

# Twice AGENT_MEMORY, held in steps whose pages are all written.
HOG_BYTES = 4 << 30
HOG_STEP = 64 << 20

# The structured output of each agent's verdict schema, by its title.
CANNED: dict[str, dict[str, Any]] = {
    "ToneVerdict": {"tone": "friendly"},
}

type Frame = dict[str, Any]


def send(frame: Frame) -> None:
    sys.stdout.write(json.dumps(frame) + "\n")
    sys.stdout.flush()


def frames() -> Iterator[Frame]:
    for line in sys.stdin:
        if line.strip():
            yield json.loads(line)


def option(name: str) -> str | None:
    arguments = sys.argv[1:]
    if name in arguments:
        return arguments[arguments.index(name) + 1]
    return None


def result(subtype: str, *, is_error: bool, **fields: Any) -> Frame:
    return {
        "type": "result",
        "subtype": subtype,
        "duration_ms": 5,
        "duration_api_ms": 0,
        "is_error": is_error,
        "num_turns": 1,
        "session_id": SESSION_ID,
        "total_cost_usd": 0.0,
        **fields,
    }


def request(incoming: Iterator[Frame], request_id: str, body: Frame) -> Frame:
    """Send a control request to the SDK and wait for its response."""
    send({"type": "control_request", "request_id": request_id, "request": body})
    for frame in incoming:
        response: Frame = frame.get("response", {})
        if frame["type"] == "control_response" and (
            response.get("request_id") == request_id
        ):
            return response
    raise SystemExit(f"stdin closed before the response to {request_id}")


def call_tool(
    incoming: Iterator[Frame], server: str, tool: str, arguments: Frame
) -> str:
    """Call an SDK MCP tool as the CLI does: the MCP handshake first."""

    def mcp(request_id: str, message: Frame) -> Frame:
        body = {"subtype": "mcp_message", "server_name": server, "message": message}
        mcp_response: Frame = request(incoming, request_id, body)["response"][
            "mcp_response"
        ]
        return mcp_response

    mcp(
        "fake-mcp-init",
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "fake-claude", "version": VERSION},
            },
        },
    )
    mcp(
        "fake-mcp-initialized",
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    called = mcp(
        "fake-mcp-call",
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        },
    )
    return "".join(part.get("text", "") for part in called["result"]["content"])


def processes() -> list[dict[str, Any]]:
    """Each process /proc lists, by PID and command name."""
    listed = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                name = (entry / "comm").read_text().strip()
            except OSError:
                continue  # It ended while being listed.
            listed.append({"pid": int(entry.name), "comm": name})
    return sorted(listed, key=lambda process: process["pid"])


def hog() -> int:
    held: list[bytes] = []
    while len(held) * HOG_STEP < HOG_BYTES:
        held.append(b"x" * HOG_STEP)
    print(f"fake claude: held {HOG_BYTES} bytes, not killed", file=sys.stderr)
    return 1


def main() -> int:
    if sys.argv[1:] == ["-v"]:
        print(VERSION)
        return 0
    seen = {
        "argv": sys.argv[1:],
        "env": {name: os.environ.get(name) for name in ISOLATION},
        "names": sorted(os.environ),
        "processes": processes(),
        "writable": os.access(".", os.W_OK),
    }
    print(json.dumps(seen), file=sys.stderr, flush=True)

    incoming = frames()
    prompt = None
    for frame in incoming:
        if frame["type"] == "control_request":
            response = {"subtype": "success", "request_id": frame["request_id"]}
            send({"type": "control_response", "response": {**response, "response": {}}})
        elif frame["type"] == "user":
            prompt = frame["message"]["content"]
            break
    if prompt is None:
        return 1

    send({"type": "system", "subtype": "init", "session_id": SESSION_ID})
    if "fake:hang" in prompt:
        while True:
            time.sleep(3600)
    if "fake:hog" in prompt:
        return hog()
    if "fake:max-turns" in prompt:
        turns = int(option("--max-turns") or 1)
        send(result("error_max_turns", is_error=True, num_turns=turns))
        return 1
    if "fake:api-error" in prompt:
        send(
            result(
                "success",
                is_error=True,
                result="API Error: 529 Overloaded",
                api_error_status=529,
            )
        )
        return 1

    text = "done"
    if "fake:call " in prompt:
        line = prompt.split("fake:call ", 1)[1].splitlines()[0]
        server, tool, arguments = line.split(" ", 2)
        text = call_tool(incoming, server, tool, json.loads(arguments))
    schema = json.loads(option("--json-schema") or "{}")
    frame = result("success", is_error=False, result=text)
    if schema.get("title") in CANNED:
        frame["structured_output"] = CANNED[schema["title"]]
    send(frame)
    # The CLI exits once the SDK closes its stdin.
    for _ in incoming:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
