"""The credential proxy, Caddy with src/corvo/agents/Caddyfile, puts the
credential in place of a session's placeholder and forwards nothing else
(U5, KTD22).

It runs from claude-proxy's image in compose.yaml, once for each credential
kind, in front of the scripted API, on a network of its own. The tests send
what a session's engine sends, and read what reached the scripted API.
"""

import http.client
import itertools
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from corvo.worker.agent_runtime.sandbox import PLACEHOLDER

from .conftest import ROOT, TEST_CREDENTIAL, docker_available

CADDYFILE = ROOT / "src" / "corvo" / "agents" / "Caddyfile"
SCRIPTED_API = ROOT / "tests" / "agents" / "scripted_api.py"
UPSTREAM_IMAGE = "python:3.14.7-slim"
OAUTH_BETA = "oauth-2025-04-20"

# A request with no assistant turn gets the first turn; one with an assistant
# turn gets the second, a stream that pauses before each of its six events,
# so it lasts past 60 seconds after the request body.
PAUSE = 13
SCRIPT = [{"text": "quick"}, {"text": "slow", "pause": PAUSE}]
QUICK = {"messages": [{"role": "user", "content": "hi"}]}
SLOW = {
    "messages": [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": [{"type": "text", "text": "hm"}]},
        {"role": "user", "content": "go on"},
    ]
}


@dataclass(frozen=True)
class Proxy:
    """One claude-proxy, for one credential kind, and the scripted API's
    log behind it."""

    container: str
    port: int
    # The scripted API's host and port, and its log.
    upstream: str
    log: Path

    def send(
        self,
        method: str,
        path: str,
        body: bytes | dict[str, Any] = b"",
        headers: Sequence[tuple[str, str]] = (),
    ) -> tuple[int, list[dict[str, Any]]]:
        """The proxy's status, and what reached the scripted API."""
        seen = len(self.entries())
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            data = json.dumps(body).encode() if isinstance(body, dict) else body
            connection.putrequest(method, path)
            for name, value in [("content-length", str(len(data))), *headers]:
                connection.putheader(name, value)
            connection.endheaders(data)
            response = connection.getresponse()
            response.read()
        finally:
            connection.close()
        return response.status, self.entries()[seen:]

    def entries(self) -> list[dict[str, Any]]:
        try:
            text = self.log.read_text()
        except FileNotFoundError:
            return []
        return [json.loads(line) for line in text.splitlines()]

    def logs(self) -> str:
        ran = subprocess.run(
            ["docker", "logs", self.container],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return ran.stdout + ran.stderr


def proxy_image() -> str:
    """claude-proxy's image, as compose.yaml pins it."""
    pinned = re.search(
        r"^ +image: (caddy:\S+)$", (ROOT / "compose.yaml").read_text(), re.M
    )
    assert pinned is not None, "compose.yaml pins no caddy image"
    return pinned[1]


def docker(*args: str) -> str:
    ran = subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=True, timeout=300
    )
    return ran.stdout.strip()


def listening(port: int) -> None:
    for _ in range(50):
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
        try:
            connection.request("GET", "/")
            connection.getresponse().read()
            return
        except OSError:
            time.sleep(0.2)
        finally:
            connection.close()
    raise RuntimeError(f"nothing answered on {port}")


@pytest.fixture(scope="module")
def proxies() -> Iterator[dict[str, Proxy]]:
    if not docker_available():
        if os.environ.get("CI"):
            pytest.fail("Docker is not available on CI")
        pytest.skip("Docker is not available")

    run = uuid.uuid4().hex[:8]
    network = f"corvo-proxy-{run}"
    directory = Path(tempfile.mkdtemp(prefix="corvo-proxy-"))
    (directory / "script.json").write_text(json.dumps(SCRIPT))
    containers: list[str] = []
    docker("network", "create", network)
    try:
        upstream = f"corvo-upstream-{run}"
        docker(
            "run",
            "--detach",
            "--name",
            upstream,
            "--network",
            network,
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--volume",
            f"{SCRIPTED_API}:/scripted/scripted_api.py:ro",
            "--volume",
            f"{directory}:/data",
            UPSTREAM_IMAGE,
            "python",
            "/scripted/scripted_api.py",
            "0.0.0.0",
            "8080",
            "/data/script.json",
            "/data/log.jsonl",
        )
        containers.append(upstream)
        image = proxy_image()
        found = {}
        # One proxy per kind, and one whose upstream refuses connections: its
        # 502 is the request Caddy logs, headers and all, at its default level.
        for key, kind, address in (
            ("api_key", "api_key", f"{upstream}:8080"),
            ("oauth_token", "oauth_token", f"{upstream}:8080"),
            ("unreachable", "api_key", "127.0.0.1:9"),
        ):
            name = f"corvo-proxy-{key}-{run}"
            docker(
                "run",
                "--detach",
                "--name",
                name,
                "--network",
                network,
                "--publish",
                "127.0.0.1::8080",
                "--env",
                f"CORVO_AGENT_CREDENTIAL={TEST_CREDENTIAL}",
                "--env",
                f"CORVO_AGENT_CREDENTIAL_KIND={kind}",
                "--env",
                f"CORVO_AGENT_UPSTREAM=http://{address}",
                "--volume",
                f"{CADDYFILE}:/etc/caddy/Caddyfile:ro",
                image,
            )
            containers.append(name)
            port = int(docker("port", name, "8080/tcp").rsplit(":", 1)[1])
            listening(port)
            found[key] = Proxy(name, port, address, directory / "log.jsonl")
        yield found
    finally:
        for container in containers:
            subprocess.run(["docker", "rm", "--force", container], capture_output=True)
        subprocess.run(["docker", "network", "rm", network], capture_output=True)
        shutil.rmtree(directory, ignore_errors=True)


def headers_of(entry: dict[str, Any]) -> dict[str, str]:
    return {name.lower(): value for name, value in entry["headers"].items()}


def test_an_api_key_replaces_the_placeholder(proxies: dict[str, Proxy]) -> None:
    status, forwarded = proxies["api_key"].send(
        "POST",
        "/v1/messages?beta=true",
        QUICK,
        [
            ("x-api-key", PLACEHOLDER),
            ("authorization", f"Bearer {PLACEHOLDER}"),
            ("anthropic-beta", "interleaved-thinking-2025-05-14"),
        ],
    )

    assert status == 200
    [entry] = forwarded
    assert entry["path"] == "/v1/messages?beta=true"
    assert headers_of(entry) == {
        "x-api-key": TEST_CREDENTIAL,
        "anthropic-beta": "interleaved-thinking-2025-05-14",
        "host": proxies["api_key"].upstream,
    }


def test_an_oauth_token_replaces_the_placeholder(proxies: dict[str, Proxy]) -> None:
    status, forwarded = proxies["oauth_token"].send(
        "POST",
        "/v1/messages/count_tokens",
        QUICK,
        [
            ("authorization", f"Bearer {PLACEHOLDER}"),
            ("x-api-key", PLACEHOLDER),
            ("anthropic-beta", OAUTH_BETA),
        ],
    )

    assert status == 200
    [entry] = forwarded
    headers = headers_of(entry)
    assert headers["authorization"] == f"Bearer {TEST_CREDENTIAL}"
    assert headers["anthropic-beta"] == OAUTH_BETA
    assert "x-api-key" not in headers


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/models"),
        ("HEAD", "/api/hello"),
        ("POST", "/v1/files"),
        ("GET", "/v1/messages"),
        ("POST", "/v1/messages/batches"),
        # Paths that clean to an allowed one, which Caddy would forward as
        # sent: the API may resolve them to another endpoint.
        ("POST", "/v1/files/../messages"),
        ("POST", "/v1/messages/batches//.."),
        ("POST", "/v1/messages/batches/..%2Fx/.."),
        ("POST", "//v1/messages"),
        ("POST", "/V1/MESSAGES"),
        ("POST", "/v1/messages/"),
    ],
)
def test_anything_else_is_not_found(
    proxies: dict[str, Proxy], method: str, path: str
) -> None:
    status, forwarded = proxies["api_key"].send(
        method, path, headers=[("x-api-key", PLACEHOLDER)]
    )

    assert (status, forwarded) == (404, [])


@pytest.mark.parametrize(
    "betas",
    [
        ["mcp-client-2025-04-04"],
        ["WEB-FETCH-2025-09-10"],
        ["interleaved-thinking-2025-05-14,web-fetch-2025-09-10"],
        [OAUTH_BETA, "mcp-client-2025-11-20"],
    ],
)
def test_a_beta_that_fetches_is_refused(
    proxies: dict[str, Proxy], betas: list[str]
) -> None:
    status, forwarded = proxies["oauth_token"].send(
        "POST",
        "/v1/messages",
        QUICK,
        [("authorization", f"Bearer {PLACEHOLDER}")]
        + [("anthropic-beta", beta) for beta in betas],
    )

    assert (status, forwarded) == (403, [])


def test_a_body_past_32_mib_is_refused(proxies: dict[str, Proxy]) -> None:
    body = b"x" * (32 * 1024**2 + 1)

    status, forwarded = proxies["api_key"].send(
        "POST", "/v1/messages", body, [("x-api-key", PLACEHOLDER)]
    )

    assert (status, forwarded) == (413, [])


def test_a_placeholder_in_a_request_is_never_expanded(
    proxies: dict[str, Proxy],
) -> None:
    value = "{env.CORVO_AGENT_CREDENTIAL}"

    status, forwarded = proxies["api_key"].send(
        "POST",
        "/v1/messages",
        QUICK,
        [("x-api-key", PLACEHOLDER), ("anthropic-beta", value)],
    )

    assert status == 200
    [entry] = forwarded
    assert headers_of(entry)["anthropic-beta"] == value


def test_a_long_stream_reaches_the_client_whole_event_by_event(
    proxies: dict[str, Proxy],
) -> None:
    proxy = proxies["api_key"]
    body = json.dumps(SLOW).encode()
    connection = http.client.HTTPConnection("127.0.0.1", proxy.port, timeout=60)
    arrived: list[tuple[str, float]] = []
    try:
        connection.request(
            "POST",
            "/v1/messages",
            body,
            {"x-api-key": PLACEHOLDER, "content-type": "application/json"},
        )
        sent = time.monotonic()
        response = connection.getresponse()
        assert response.status == 200
        for line in response:
            if line.startswith(b"event: "):
                arrived.append((line[7:].decode().strip(), time.monotonic()))
    finally:
        connection.close()

    assert [name for name, _ in arrived] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    times = [sent] + [at for _, at in arrived]
    gaps = [later - earlier for earlier, later in itertools.pairwise(times)]
    assert min(gaps) > PAUSE - 3
    assert times[-1] - sent > 60


def test_its_log_holds_no_header(proxies: dict[str, Proxy]) -> None:
    unreachable = proxies["unreachable"]
    credentials = [
        ("x-api-key", PLACEHOLDER),
        ("authorization", f"Bearer {PLACEHOLDER}"),
    ]

    status, _ = unreachable.send("POST", "/v1/messages", QUICK, credentials)

    assert status == 502
    errors = [
        json.loads(line)
        for line in unreachable.logs().splitlines()
        if '"http.log.error"' in line
    ]
    assert [error["request"]["uri"] for error in errors] == ["/v1/messages"]
    for proxy in proxies.values():
        logs = proxy.logs().lower()
        for secret in (TEST_CREDENTIAL, PLACEHOLDER, "x-api-key", "authorization"):
            assert secret not in logs, proxy.container
