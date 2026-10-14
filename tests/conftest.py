import base64
import json
import os


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
