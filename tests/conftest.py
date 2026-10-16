import base64
import json
import os

import pytest
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport


def _encode(part: dict[str, str]) -> str:
    return base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")


# corvo.worker's Hatchet client is built as its module is imported, before
# any fixture runs, and refuses to build without a token. Hatchet's SDK only
# checks that the token is a JWT and reads the engine's addresses from its
# claims, without its signature, so an unsigned one does for the tests that
# reach no engine (aio_mock_run). This leans on the SDK's internals
# (hatchet_sdk/config.py, hatchet_sdk/token.py), which Hatchet's docs do not
# document: should it ever check the signature, every test importing
# corvo.worker fails on import. The integration tests trigger tasks with a
# client of their own, on a real token.
os.environ.setdefault(
    "CORVO_HATCHET_TOKEN",
    ".".join(
        [
            _encode({"alg": "none"}),
            _encode(
                {
                    "sub": "tenant",
                    "server_url": "http://localhost:1",
                    "grpc_broadcast_address": "localhost:1",
                }
            ),
            "",
        ]
    ),
)

# No test reaches Claude (R22). The SDK passes the environment on to its CLI,
# so no credential reaches it, and the API's address is a closed port.
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
os.environ["ANTHROPIC_BASE_URL"] = "http://127.0.0.1:9"


@pytest.fixture(autouse=True)
def no_claude(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fails the test that runs the SDK without replacing it, before the SDK
    starts its CLI, which would reach Claude on the developer's own login.

    Both query() and ClaudeSDKClient connect through SubprocessCLITransport,
    which the SDK does not export: this leans on its internals
    (claude_agent_sdk/_internal/transport/subprocess_cli.py). The fake CLI's
    contract test, marked fake_cli, runs the real transport on the fake. Only a
    mark on the test function itself counts, so marking a module or a class
    lets none of its other tests through.
    """
    if not any(mark.name == "fake_cli" for mark in request.node.own_markers):

        async def connect(self: SubprocessCLITransport) -> None:
            pytest.fail(
                f"{request.node.nodeid} runs the Claude Agent SDK unreplaced: "
                "replace query on the agent's module"
            )

        monkeypatch.setattr(SubprocessCLITransport, "connect", connect)
