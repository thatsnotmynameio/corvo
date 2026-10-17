"""A stand-in for the Messages API that answers a session with scripted turns.

The real engine talks to it as it would to the Claude API, through
ANTHROPIC_BASE_URL, so a test drives a whole session without calling Claude.
The script is a JSON list of turns, picked by how many assistant turns the
request already holds:

- {"tool_use": [{"name": "Bash", "input": {...}}, ...]} asks for those calls;
- {"text": "..."} ends the session with that text, where {tool_results}
  becomes the text of the results the request carries, in order.

A turn with "pause": <seconds> waits that long before each of its stream
events, as a slow stream does. Past the script's end, the session ends with
the tool results. Each request's method, path, credential headers, Host and
tool results are appended to the log as a JSON line.

Usage: python scripted_api.py <host> <port> <script.json> <log.jsonl>
"""

import json
import sys
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

RECORDED_HEADERS = ("x-api-key", "authorization", "anthropic-beta", "host")


def tool_results(body: dict[str, Any]) -> list[str]:
    """The text of each tool result since the last assistant turn. The engine
    may follow its user messages with system ones."""
    messages = body.get("messages", [])
    assistant = [
        i for i, message in enumerate(messages) if message["role"] == "assistant"
    ]
    results = []
    for message in messages[assistant[-1] + 1 :] if assistant else []:
        content = message.get("content")
        if message["role"] != "user" or not isinstance(content, list):
            continue
        for block in content:
            if block.get("type") != "tool_result":
                continue
            text = block.get("content") or ""
            if isinstance(text, list):
                text = "".join(part.get("text", "") for part in text)
            results.append(text)
    return results


def reply(turn: dict[str, Any], results: list[str]) -> tuple[list[Any], str]:
    """The turn's content blocks, each as its start and its one delta, and its
    stop reason."""
    if "tool_use" in turn:
        blocks = [
            (
                {
                    "type": "tool_use",
                    "id": f"toolu_{index}",
                    "name": call["name"],
                    "input": {},
                },
                {"type": "input_json_delta", "partial_json": json.dumps(call["input"])},
            )
            for index, call in enumerate(turn["tool_use"])
        ]
        return blocks, "tool_use"
    text = turn["text"].replace("{tool_results}", "\n".join(results))
    block = ({"type": "text", "text": ""}, {"type": "text_delta", "text": text})
    return [block], "end_turn"


def events(blocks: list[Any], stop: str) -> Iterator[tuple[str, dict[str, Any]]]:
    """The Messages API's stream events for one assistant message."""
    usage = {"input_tokens": 1, "output_tokens": 1}
    yield (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_scripted",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-5-5",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": usage,
            },
        },
    )
    for index, (start, delta) in enumerate(blocks):
        yield (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": index,
                "content_block": start,
            },
        )
        yield (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": index,
                "delta": delta,
            },
        )
        yield "content_block_stop", {"type": "content_block_stop", "index": index}
    yield (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop, "stop_sequence": None},
            "usage": {"output_tokens": 1},
        },
    )
    yield "message_stop", {"type": "message_stop"}


def handler(script: list[dict[str, Any]], log: Path) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def record(self, results: list[str], turn: int | None = None) -> None:
            entry = {
                "method": self.command,
                "path": self.path,
                "turn": turn,
                "headers": {
                    name: value
                    for name, value in self.headers.items()
                    if name.lower() in RECORDED_HEADERS
                },
                "tool_results": results,
            }
            with log.open("a") as f:
                f.write(json.dumps(entry) + "\n")

        def do_GET(self) -> None:
            self.record([])
            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", 0))
            body: dict[str, Any] = json.loads(self.rfile.read(length) or b"{}")
            results = tool_results(body)
            if self.path.split("?")[0] != "/v1/messages":
                self.record(results)
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"input_tokens": 1}')
                return
            done = sum(1 for m in body.get("messages", []) if m["role"] == "assistant")
            self.record(results, done)
            turn = script[done] if done < len(script) else {"text": "{tool_results}"}
            blocks, stop = reply(turn, results)
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.end_headers()
            pause = float(turn.get("pause", 0))
            for name, data in events(blocks, stop):
                if pause:
                    time.sleep(pause)
                self.wfile.write(
                    f"event: {name}\ndata: {json.dumps(data)}\n\n".encode()
                )
            self.wfile.flush()

    return Handler


def main() -> None:
    host, port, script, log = sys.argv[1:]
    turns = json.loads(Path(script).read_text())
    server = ThreadingHTTPServer((host, int(port)), handler(turns, Path(log)))
    server.serve_forever()


if __name__ == "__main__":
    main()
