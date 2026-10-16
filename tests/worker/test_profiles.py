import importlib
import subprocess
import sys

import pytest

import corvo.worker.profiles.agents
import corvo.worker.profiles.main
from corvo.worker.agent_runtime import startup
from corvo.worker.agents.dir_summary import dir_summary
from corvo.worker.agents.tone import tone
from corvo.worker.defaults import AGENT_CONCURRENCY
from corvo.worker.profiles import PROFILES, Profile


@pytest.mark.parametrize("name", sorted(PROFILES))
def test_each_profile_module_holds_its_profile(name: str) -> None:
    module = importlib.import_module(PROFILES[name])

    assert isinstance(module.PROFILE, Profile)


def test_the_profiles_import_no_profile_module() -> None:
    # A fresh interpreter: this module has already imported both profiles.
    code = (
        "import sys, corvo.worker.profiles; "
        "print(sorted(m for m in sys.modules "
        "if m.startswith('corvo.worker.profiles.')))"
    )

    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )

    assert result.stdout == "[]\n"


def test_the_main_profile_is_corvo_worker_without_hooks() -> None:
    profile = corvo.worker.profiles.main.PROFILE

    assert profile.name == "corvo-worker"
    assert profile.slots is None
    assert profile.before_start is None
    assert profile.on_sigterm is None


def test_the_agents_profile_takes_as_many_runs_as_the_cap() -> None:
    profile = corvo.worker.profiles.agents.PROFILE

    assert profile.name == "corvo-agent-worker"
    assert profile.workflows == [tone, dir_summary]
    assert profile.slots == AGENT_CONCURRENCY.max_runs


def test_the_agents_profile_checks_its_isolation_and_ends_its_sessions() -> None:
    profile = corvo.worker.profiles.agents.PROFILE

    assert profile.before_start is startup.before_start
    assert profile.on_sigterm is startup.on_sigterm
