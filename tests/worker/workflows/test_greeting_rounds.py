from datetime import timedelta
from typing import Any

import pytest
from hatchet_sdk import (
    DurableContext,
    SleepCondition,
    TaskRunError,
    UserEventCondition,
)
from hatchet_sdk.conditions import OrGroup
from pydantic import ValidationError

from corvo.worker.defaults import RETRIES
from corvo.worker.tasks.hello import HelloInput, HelloOutput, hello
from corvo.worker.workflows.greeting import GreetingInput, greeting
from corvo.worker.workflows.greeting_rounds import (
    APPROVAL_EVENT,
    GreetingRoundsInput,
    GreetingRoundsOutput,
    greeting_rounds,
)


class HelloReplacement:
    """Stands in for hello.aio_run, which would spawn a child run on Hatchet.
    Each reply is five characters longer than the name it gets."""

    def __init__(self) -> None:
        self.received: list[HelloInput] = []

    async def __call__(self, input: HelloInput) -> HelloOutput:
        self.received.append(input)
        return HelloOutput(message=f"Hi, {input.name}.")


class GreetingReplacement:
    """Stands in for greeting.aio_run, returning the DAG's result keyed by
    step name, as the greeting-rounds integration test finds it."""

    def __init__(self) -> None:
        self.received: list[GreetingInput] = []

    async def __call__(self, input: GreetingInput) -> dict[str, Any]:
        self.received.append(input)
        return {
            "greet": {"message": input.name},
            "shout": {"message": input.name.upper()},
        }


class WaitReplacement:
    """Stands in for DurableContext.aio_wait_for, which needs an engine. It
    answers with Hatchet's wait-result shape, keyed by the matched condition."""

    def __init__(self, matched: str) -> None:
        self.matched = matched
        self.conditions: list[Any] = []

    # An instance set on the class is not bound, so it gets no context.
    async def __call__(
        self, signal_key: str, *conditions: Any, **_: Any
    ) -> dict[str, Any]:
        self.conditions.extend(conditions)
        return {"CREATE": {self.matched: [{}]}}


@pytest.fixture
def replaced_hello(monkeypatch: pytest.MonkeyPatch) -> HelloReplacement:
    replacement = HelloReplacement()
    monkeypatch.setattr(hello, "aio_run", replacement)
    return replacement


@pytest.fixture
def replaced_greeting(monkeypatch: pytest.MonkeyPatch) -> GreetingReplacement:
    replacement = GreetingReplacement()
    monkeypatch.setattr(greeting, "aio_run", replacement)
    return replacement


def replace_wait(monkeypatch: pytest.MonkeyPatch, matched: str) -> WaitReplacement:
    replacement = WaitReplacement(matched)
    monkeypatch.setattr(DurableContext, "aio_wait_for", replacement)
    return replacement


def rounds_input(**overrides: Any) -> GreetingRoundsInput:
    fields: dict[str, Any] = {
        "name": "corvo",
        "approval_key": "run-1",
        "target_length": 200,
        "max_rounds": 1,
        "approval_timeout_seconds": 60,
    }
    return GreetingRoundsInput(**(fields | overrides))


@pytest.mark.usefixtures("replaced_hello")
async def test_an_approval_takes_the_approved_path(
    monkeypatch: pytest.MonkeyPatch, replaced_greeting: GreetingReplacement
) -> None:
    replace_wait(monkeypatch, matched="approved")

    output = await greeting_rounds.aio_mock_run(rounds_input(max_rounds=2))

    assert output == GreetingRoundsOutput(
        rounds=2,
        message="Hi, Hi, corvo..",
        shout="HI, HI, CORVO..",
        outcome="approved",
    )
    assert replaced_greeting.received == [GreetingInput(name="Hi, Hi, corvo..")]


@pytest.mark.usefixtures("replaced_hello", "replaced_greeting")
async def test_a_timeout_takes_the_timed_out_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replace_wait(monkeypatch, matched="timeout")

    output = await greeting_rounds.aio_mock_run(rounds_input())

    assert output.outcome == "timed_out"


@pytest.mark.usefixtures("replaced_greeting")
@pytest.mark.parametrize(
    ("target_length", "max_rounds", "names"),
    [
        # The message never reaches 200 characters, so max_rounds stops the
        # loop.
        (200, 3, ["corvo", "Hi, corvo.", "Hi, Hi, corvo.."]),
        # The second reply has 15 characters.
        (15, 5, ["corvo", "Hi, corvo."]),
        # The first reply has 10 characters.
        (10, 5, ["corvo"]),
    ],
)
async def test_the_loop_spawns_hello_until_its_exit_condition(
    monkeypatch: pytest.MonkeyPatch,
    replaced_hello: HelloReplacement,
    target_length: int,
    max_rounds: int,
    names: list[str],
) -> None:
    replace_wait(monkeypatch, matched="approved")

    output = await greeting_rounds.aio_mock_run(
        rounds_input(target_length=target_length, max_rounds=max_rounds)
    )

    assert replaced_hello.received == [HelloInput(name=name) for name in names]
    assert output.rounds == len(names)


@pytest.mark.usefixtures("replaced_hello", "replaced_greeting")
async def test_the_wait_matches_the_runs_approval_key_or_sleeps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wait = replace_wait(monkeypatch, matched="approved")

    await greeting_rounds.aio_mock_run(
        rounds_input(approval_key="run-7", approval_timeout_seconds=42)
    )

    [group] = wait.conditions
    assert isinstance(group, OrGroup)
    [event, sleep] = group.conditions
    assert isinstance(event, UserEventCondition)
    assert event.event_key == APPROVAL_EVENT
    assert event.expression == "input.approval_key == 'run-7'"
    assert event.scope == "approval_key:run-7"
    assert event.consider_events_since is not None
    assert isinstance(sleep, SleepCondition)
    assert sleep.duration == timedelta(seconds=42)


@pytest.mark.usefixtures("replaced_greeting")
async def test_a_failed_child_fails_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_hello(input: HelloInput) -> HelloOutput:
        raise TaskRunError("hello failed", "ValueError", "", None)

    monkeypatch.setattr(hello, "aio_run", failing_hello)
    replace_wait(monkeypatch, matched="approved")

    with pytest.raises(TaskRunError):
        await greeting_rounds.aio_mock_run(rounds_input())


@pytest.mark.parametrize(
    "overrides",
    [
        {"approval_key": "run-'1"},
        {"approval_key": "Run-1"},
        {"approval_key": ""},
        {"max_rounds": 0},
        {"max_rounds": 11},
        {"target_length": 0},
        {"target_length": 201},
        {"approval_timeout_seconds": 0},
        {"approval_timeout_seconds": 601},
    ],
)
def test_the_input_rejects_values_outside_its_bounds(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        rounds_input(**overrides)


def test_greeting_rounds_keeps_the_default_retries() -> None:
    [task] = greeting_rounds.tasks

    assert task.retries == RETRIES
    assert task.execution_timeout == timedelta(minutes=30)
