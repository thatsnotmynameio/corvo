"""The fingerprint of the agents' code, which the worker and the image compare.

The worker and the agent image each compute it over their own installed copy.
A stale image, built before the agents' code or the SDK changed, then gives
a different fingerprint, and the worker refuses it (KTD10). The worker
imports this module, so it uses the standard library alone.
"""

import hashlib
from importlib.metadata import version
from pathlib import Path

# The corvo package directory this module is installed in.
CORVO = Path(__file__).parents[1]

AREAS = ("agents", "core/agents")


def counted(path: Path, area: Path) -> bool:
    parts = path.relative_to(area).parts
    if "__pycache__" in parts or path.suffix == ".pyc":
        return False
    return path.suffix == ".py" or "prompts" in parts[:-1]


def fingerprint(corvo: Path = CORVO) -> str:
    """A SHA-256 over the agents' *.py and prompts/** files, sorted by path
    under corvo, and the installed claude-agent-sdk version."""
    files = sorted(
        path
        for area in AREAS
        for path in (corvo / area).rglob("*")
        if path.is_file() and counted(path, corvo / area)
    )
    digest = hashlib.sha256()
    for path in files:
        content = path.read_bytes()
        name = path.relative_to(corvo).as_posix().encode()
        # Each length first, so no two trees give the same stream of bytes.
        for part in (name, content):
            digest.update(len(part).to_bytes(8, "big"))
            digest.update(part)
    digest.update(version("claude-agent-sdk").encode())
    return digest.hexdigest()
