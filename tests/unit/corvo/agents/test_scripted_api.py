"""The scripted Messages API answers each turn as its script says, in the
API's stream format, and logs what each request carried."""

import itertools
import json
import threading
import time
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from support.scripted_api import handler

SCRIPT: list[dict[str, Any]] = [
    {"tool_use": [{"name": "Bash", "input": {"command": "echo corvo"}}]},
    {"text": "done: {tool_results}"},
]


@pytest.fixture
def api(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    log = tmp_path / "log.jsonl"
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler(SCRIPT, log))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", log
    finally:
        server.shutdown()
        server.server_close()


def post(url: str, body: dict[str, Any], **headers: str) -> tuple[str, str]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        return response.headers["content-type"], response.read().decode()


def stream(text: str) -> list[tuple[str, dict[str, Any]]]:
    """The (event, data) pairs of a server-sent event stream."""
    events = []
    for chunk in text.strip().split("\n\n"):
        name, data = chunk.split("\n")
        events.append((name.removeprefix("event: "), json.loads(data[6:])))
    return events


def tool_use_turn() -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": [{"type": "tool_use", "id": "toolu_0", "name": "Bash"}],
    }


def tool_result(text: str) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_0",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def test_the_first_turn_asks_for_the_scripted_calls(api: tuple[str, Path]) -> None:
    url, _ = api
    body = {"messages": [{"role": "user", "content": "go"}]}

    kind, text = post(f"{url}/v1/messages?beta=true", body)

    events = stream(text)
    assert kind == "text/event-stream"
    assert [name for name, _ in events] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert events[1][1]["content_block"]["name"] == "Bash"
    assert json.loads(events[2][1]["delta"]["partial_json"]) == {
        "command": "echo corvo"
    }
    assert events[4][1]["delta"]["stop_reason"] == "tool_use"


def test_the_last_turn_ends_with_the_tool_results(api: tuple[str, Path]) -> None:
    url, _ = api
    body = {
        "messages": [
            {"role": "user", "content": "go"},
            tool_use_turn(),
            tool_result("corvo"),
            {"role": "system", "content": [{"type": "text", "text": "reminder"}]},
        ]
    }

    _, text = post(f"{url}/v1/messages", body)

    events = stream(text)
    assert events[2][1]["delta"] == {"type": "text_delta", "text": "done: corvo"}
    assert events[4][1]["delta"]["stop_reason"] == "end_turn"


def test_only_the_results_since_the_last_assistant_turn_count(
    api: tuple[str, Path],
) -> None:
    url, _ = api
    body = {
        "messages": [
            {"role": "user", "content": "go"},
            tool_use_turn(),
            tool_result("first"),
            tool_use_turn(),
            tool_result("second"),
        ]
    }

    _, text = post(f"{url}/v1/messages", body)

    assert stream(text)[2][1]["delta"]["text"] == "second"


def test_each_request_is_logged_with_its_credential_headers_and_host_only(
    api: tuple[str, Path],
) -> None:
    url, log = api
    body = {"messages": [{"role": "user", "content": "go"}]}

    post(f"{url}/v1/messages", body, **{"x-api-key": "placeholder", "x-other": "1"})

    (entry,) = [json.loads(line) for line in log.read_text().splitlines()]
    assert entry == {
        "method": "POST",
        "path": "/v1/messages",
        "turn": 0,
        # As urllib sends them; the log keeps the names as they arrived.
        "headers": {"X-Api-Key": "placeholder", "Host": url.removeprefix("http://")},
        "tool_results": [],
    }


def test_a_paused_turn_sends_each_event_after_its_pause(tmp_path: Path) -> None:
    script = [{"text": "slow", "pause": 0.2}]
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), handler(script, tmp_path / "log.jsonl")
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    request = urllib.request.Request(
        f"http://127.0.0.1:{server.server_address[1]}/v1/messages",
        data=json.dumps({"messages": []}).encode(),
        method="POST",
    )
    arrived = []
    try:
        with urllib.request.urlopen(request) as response:
            for line in response:
                if line.startswith(b"event: "):
                    arrived.append(time.monotonic())
    finally:
        server.shutdown()
        server.server_close()

    assert len(arrived) == 6
    gaps = [later - earlier for earlier, later in itertools.pairwise(arrived)]
    assert min(gaps) >= 0.15


def test_token_counts_get_a_fixed_answer(api: tuple[str, Path]) -> None:
    url, _ = api

    kind, text = post(f"{url}/v1/messages/count_tokens", {"messages": []})

    assert kind == "application/json"
    assert json.loads(text) == {"input_tokens": 1}
