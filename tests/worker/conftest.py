from collections.abc import Iterator
from pathlib import Path

import pytest

from corvo.settings import get_settings
from corvo.worker.agent_runtime import cgroups, sessions

from .agent_runtime.fake_cgroups import Tree


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Tree]:
    """The agent worker's settings, with each run's cgroup made in a Tree."""
    (tmp_path / "root" / "workdirs").mkdir(parents=True)
    (tmp_path / "cgroup").mkdir()
    monkeypatch.setenv("CORVO_AGENT_ROOT", str(tmp_path / "root"))
    monkeypatch.setenv("CORVO_AGENT_CGROUP_ROOT", str(tmp_path / "cgroup"))
    monkeypatch.setenv("CORVO_AGENT_ENGINE", "/opt/corvo/engine/claude")
    monkeypatch.setenv("CORVO_AGENT_PROXY_URL", "http://proxy:8080")
    monkeypatch.delenv("CORVO_AGENT_CREDENTIAL_KIND", raising=False)
    get_settings.cache_clear()
    replaced = Tree(tmp_path / "cgroup")
    monkeypatch.setattr(cgroups, "create", replaced.create)
    monkeypatch.setattr(sessions, "refusal", None)
    yield replaced
    get_settings.cache_clear()
    sessions.in_flight.clear()
