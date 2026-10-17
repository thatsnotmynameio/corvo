import dataclasses
import logging
import signal
from collections.abc import Iterator
from types import FrameType
from typing import Any

import pytest
from hatchet_sdk import Worker

import corvo.worker.profiles.agents
import corvo.worker.profiles.main
from corvo.settings import get_settings
from corvo.vendors.hatchet.client import hatchet
from corvo.worker.profiles import Profile
from corvo.worker.worker import main, serve


class Started(Exception):
    """Raised in place of Worker.start, which would connect to Hatchet."""


@pytest.fixture
def events(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[tuple[str, dict[str, Any]]]]:
    # Worker keeps its list and slots private, so this reads what corvo hands
    # Hatchet, and stops at start.
    recorded: list[tuple[str, dict[str, Any]]] = []
    build = hatchet.worker

    def spy(name: str, **options: Any) -> Worker:
        recorded.append((name, options))
        return build(name, **options)

    def start(self: Worker) -> None:
        recorded.append(("start", {}))
        raise Started

    monkeypatch.setattr(hatchet, "worker", spy)
    monkeypatch.setattr(Worker, "start", start)
    # Hatchet's Worker installs its own handlers; put them back after.
    signals = (signal.SIGTERM, signal.SIGINT, signal.SIGQUIT)
    previous = {signum: signal.getsignal(signum) for signum in signals}
    yield recorded
    for signum, handler in previous.items():
        signal.signal(signum, handler)


@pytest.fixture(autouse=True)
def fresh_settings() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def root_level() -> Iterator[logging.Logger]:
    # main() sets the root logger's level; put it back, so a DEBUG root
    # does not reach later tests.
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.WARNING)
    yield root
    root.setLevel(level)


@pytest.mark.parametrize(
    ("variable", "level"),
    [("DEBUG", logging.DEBUG), (None, logging.INFO)],
    ids=["its variable's", "info by default"],
)
def test_main_sets_the_root_level_before_the_worker_starts(
    events: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    root_level: logging.Logger,
    variable: str | None,
    level: int,
) -> None:
    monkeypatch.delenv("CORVO_WORKER_PROFILE", raising=False)
    if variable is None:
        monkeypatch.delenv("CORVO_LOG_LEVEL", raising=False)
    else:
        monkeypatch.setenv("CORVO_LOG_LEVEL", variable)
    seen: list[int] = []
    monkeypatch.setattr(Worker, "start", lambda self: seen.append(root_level.level))
    assert root_level.level != level

    main()

    assert seen == [level]


def test_main_serves_the_main_profile_by_default(
    events: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CORVO_WORKER_PROFILE", raising=False)
    monkeypatch.delenv("CORVO_WORKER_NAME", raising=False)
    profile = corvo.worker.profiles.main.PROFILE

    with pytest.raises(Started):
        main()

    assert events == [
        ("corvo-worker", {"slots": None, "workflows": profile.workflows}),
        ("start", {}),
    ]


def test_main_serves_the_profile_its_variable_names(
    events: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORVO_WORKER_PROFILE", "agents")
    # Without its start checks, which need the agent worker's container.
    profile = dataclasses.replace(
        corvo.worker.profiles.agents.PROFILE, before_start=None
    )
    monkeypatch.setattr(corvo.worker.profiles.agents, "PROFILE", profile)

    with pytest.raises(Started):
        main()

    assert events == [
        (
            "corvo-agent-worker",
            {"slots": profile.slots, "workflows": profile.workflows},
        ),
        ("start", {}),
    ]


def test_main_registers_under_the_name_its_variable_sets(
    events: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CORVO_WORKER_PROFILE", raising=False)
    monkeypatch.setenv("CORVO_WORKER_NAME", "corvo-worker-a")
    profile = corvo.worker.profiles.main.PROFILE

    with pytest.raises(Started):
        main()

    assert events == [
        ("corvo-worker-a", {"slots": None, "workflows": profile.workflows}),
        ("start", {}),
    ]


def test_the_name_keeps_the_agents_profiles_slots_and_workflows(
    events: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CORVO_WORKER_PROFILE", "agents")
    monkeypatch.setenv("CORVO_WORKER_NAME", "corvo-agent-worker-b")
    profile = dataclasses.replace(
        corvo.worker.profiles.agents.PROFILE, before_start=None
    )
    monkeypatch.setattr(corvo.worker.profiles.agents, "PROFILE", profile)

    with pytest.raises(Started):
        main()

    assert events == [
        (
            "corvo-agent-worker-b",
            {"slots": profile.slots, "workflows": profile.workflows},
        ),
        ("start", {}),
    ]


@pytest.mark.parametrize("blank", ["", "  "])
def test_a_blank_name_keeps_the_profiles_name(
    events: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    blank: str,
) -> None:
    monkeypatch.delenv("CORVO_WORKER_PROFILE", raising=False)
    monkeypatch.setenv("CORVO_WORKER_NAME", blank)

    with pytest.raises(Started):
        main()

    assert events[0][0] == "corvo-worker"


def test_main_exits_on_an_unknown_profile_before_any_worker(
    events: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("CORVO_WORKER_PROFILE", "database")

    with pytest.raises(SystemExit) as exited:
        main()

    assert exited.value.code == 1
    assert caplog.messages == [
        "unknown worker profile 'database': the profiles are agents, main"
    ]
    assert events == []


def test_a_refused_agents_start_exits_before_any_worker(
    events: list[tuple[str, dict[str, Any]]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("CORVO_WORKER_PROFILE", "agents")
    monkeypatch.setenv("CORVO_AGENT_ROOT", "")

    with pytest.raises(SystemExit) as exited:
        main()

    assert exited.value.code == 1
    assert caplog.messages[-1] == (
        "agents refused: settings: CORVO_AGENT_ROOT is not set"
    )
    assert events == []


def test_serve_runs_before_start_before_creating_the_worker(
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    profile = Profile(
        name="hooked",
        workflows=[],
        before_start=lambda: events.append(("before_start", {})),
    )

    with pytest.raises(Started):
        serve(profile)

    assert [name for name, _ in events] == ["before_start", "hooked", "start"]


def test_the_sigterm_hook_hands_over_to_hatchets_handler(
    events: list[tuple[str, dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def exit_signal(self: Worker, signum: int, frame: FrameType | None) -> None:
        calls.append("hatchet")

    monkeypatch.setattr(Worker, "_handle_exit_signal", exit_signal)
    profile = Profile(
        name="hooked", workflows=[], on_sigterm=lambda: calls.append("on_sigterm")
    )

    with pytest.raises(Started):
        serve(profile)
    handler = signal.getsignal(signal.SIGTERM)
    assert callable(handler)
    handler(signal.SIGTERM, None)

    assert calls == ["on_sigterm", "hatchet"]


def test_serve_without_hooks_leaves_hatchets_handler(
    events: list[tuple[str, dict[str, Any]]],
) -> None:
    with pytest.raises(Started):
        serve(Profile(name="plain", workflows=[]))

    handler = signal.getsignal(signal.SIGTERM)
    assert isinstance(getattr(handler, "__self__", None), Worker)
