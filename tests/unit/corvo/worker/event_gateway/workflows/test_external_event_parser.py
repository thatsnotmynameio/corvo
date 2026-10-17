import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from hatchet_sdk import Context, EmptyModel, NonRetryableException

from corvo.core.events.event import Event
from corvo.vendors.hatchet.client import hatchet
from corvo.worker.defaults import EVENT_SCHEDULE_TIMEOUT, EXECUTION_TIMEOUT, RETRIES
from corvo.worker.event_gateway.workflows import external_event_parser as module
from corvo.worker.event_gateway.workflows.external_event_parser import (
    ParsedOutput,
    external_event_parser,
    parse_external_event,
)

KEY = "github:issue:opened"
NAME = "corvo:external_event:github:issue:opened"
HATCHET_ID = "evt-1"
PAYLOAD = {"number": 42}


@dataclass(frozen=True)
class Published:
    """The one part of Hatchet's pushed Event the task reads."""

    event_id: str


class PushReplacement:
    """Stands in for hatchet.event.aio_push, which would reach the engine."""

    def __init__(self) -> None:
        self.pushed: list[tuple[str, dict[str, Any]]] = []
        self.error: Exception | None = None

    async def __call__(self, event_key: str, payload: dict[str, Any]) -> Published:
        if self.error is not None:
            raise self.error
        self.pushed.append((event_key, payload))
        return Published(event_id=f"published-{len(self.pushed)}")

    def events(self) -> list[Event]:
        return [Event.model_validate(payload) for _, payload in self.pushed]


@pytest.fixture
def push(monkeypatch: pytest.MonkeyPatch) -> PushReplacement:
    replacement = PushReplacement()
    monkeypatch.setattr(hatchet.event, "aio_push", replacement)
    return replacement


type Trigger = Callable[[str | None, str | None], None]


@pytest.fixture
def triggered_by(monkeypatch: pytest.MonkeyPatch) -> Trigger:
    """Sets the triggering event's key and id, which a mock run cannot."""

    def trigger(key: str | None, event_id: str | None) -> None:
        monkeypatch.setattr(Context, "triggering_event_key", property(lambda _: key))
        monkeypatch.setattr(
            Context, "triggering_event_id", property(lambda _: event_id)
        )

    trigger(KEY, HATCHET_ID)
    return trigger


def records(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == module.logger.name and record.levelno == level
    ]


async def run(payload: dict[str, Any] = PAYLOAD) -> ParsedOutput:
    # A plain dict would reach the task as {}.
    return await parse_external_event.aio_mock_run(EmptyModel(**payload))


async def test_an_external_event_is_published_as_a_corvo_event(
    push: PushReplacement, triggered_by: Trigger
) -> None:
    # Covers AE1.
    output = await run()

    [(key, _)] = push.pushed
    [event] = push.events()
    assert key == NAME
    assert event.name == NAME
    assert event.source == "github"
    assert event.payload == PAYLOAD
    assert event.external_id == HATCHET_ID
    assert output == ParsedOutput(event_id=event.id, published_id="published-1")


async def test_info_names_the_received_and_the_published_event(
    push: PushReplacement, triggered_by: Trigger, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    await run()

    [event] = push.events()
    received, published = records(caplog, logging.INFO)
    assert KEY in received
    assert HATCHET_ID in received
    assert NAME in published
    assert str(event.id) in published


async def test_debug_holds_the_payload(
    push: PushReplacement, triggered_by: Trigger, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)

    await run()

    [debug] = records(caplog, logging.DEBUG)
    assert str(PAYLOAD) in debug
    assert KEY in debug


async def test_info_leaves_the_payload_out(
    push: PushReplacement, triggered_by: Trigger, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    await run()

    assert len(records(caplog, logging.INFO)) == 2
    assert records(caplog, logging.DEBUG) == []


async def test_a_name_too_long_fails_without_retry_or_publish(
    push: PushReplacement, triggered_by: Trigger, caplog: pytest.LogCaptureFixture
) -> None:
    # Covers AE3. 21 characters of prefix and 235 of key make 256.
    key = "github:" + "a" * 228
    triggered_by(key, HATCHET_ID)

    with pytest.raises(NonRetryableException):
        await run()

    [error] = records(caplog, logging.ERROR)
    assert key in error
    assert HATCHET_ID in error
    assert push.pushed == []


@pytest.mark.parametrize(
    ("key", "event_id"),
    [("", HATCHET_ID), (None, HATCHET_ID), (KEY, ""), (KEY, None)],
    ids=["an empty key", "no key", "an empty id", "no id"],
)
async def test_a_run_without_its_event_fails_without_retry_or_publish(
    push: PushReplacement,
    triggered_by: Trigger,
    caplog: pytest.LogCaptureFixture,
    key: str | None,
    event_id: str | None,
) -> None:
    triggered_by(key, event_id)

    with pytest.raises(NonRetryableException):
        await run()

    assert len(records(caplog, logging.ERROR)) == 1
    assert push.pushed == []


@pytest.mark.parametrize(
    "error",
    [ValueError("Error encoding payload"), ConnectionError("engine unreachable")],
    ids=["an encoding error", "a transport error"],
)
async def test_a_failed_publish_is_raised_as_it_is_so_hatchet_retries_it(
    push: PushReplacement,
    triggered_by: Trigger,
    caplog: pytest.LogCaptureFixture,
    error: Exception,
) -> None:
    # Covers R16: only NonRetryableException stops Hatchet's retries.
    push.error = error

    with pytest.raises(type(error)) as raised:
        await run()

    assert raised.value is error
    [logged] = records(caplog, logging.ERROR)
    assert KEY in logged
    assert HATCHET_ID in logged


async def test_each_run_of_one_event_publishes_a_new_corvo_event(
    push: PushReplacement, triggered_by: Trigger
) -> None:
    # Covers AE4: a retry runs the task again for the same event.
    await run()
    await run()

    first, second = push.events()
    assert first.id != second.id
    assert first.external_id == second.external_id == HATCHET_ID


def test_the_workflow_listens_to_the_external_prefixes() -> None:
    assert external_event_parser.name == "external-event-parser"
    assert external_event_parser.config.on_events == ["github:*"]


def test_the_task_declares_the_defaults_and_waits_a_day_for_a_worker() -> None:
    assert parse_external_event.name == "external_event_parser"
    assert parse_external_event.retries == RETRIES
    assert parse_external_event.execution_timeout == EXECUTION_TIMEOUT
    assert parse_external_event.schedule_timeout == EVENT_SCHEDULE_TIMEOUT
