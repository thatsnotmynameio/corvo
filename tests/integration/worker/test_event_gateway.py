import asyncio
import uuid

import pytest
from hatchet_sdk import Hatchet, V1TaskStatus
from hatchet_sdk.clients.rest.models.v1_event import V1Event
from hatchet_sdk.clients.rest.models.v1_task_summary import V1TaskSummary

from corvo.core.event_gateway.external_event_parser import NAME_PREFIX
from corvo.core.events.event import Event

from .conftest import DONE


def unique(prefix: str) -> str:
    # The session's tests share one stack, so each pushes keys of its own.
    return f"{prefix}:test:{uuid.uuid4().hex}"


async def finished_run(hatchet: Hatchet, event_id: str) -> V1TaskSummary:
    """Polls until the run the event started is done. The caller bounds the
    wait."""
    while True:
        listed = await hatchet.runs.aio_list(triggering_event_external_id=event_id)
        if listed.rows and all(run.status in DONE for run in listed.rows):
            [run] = listed.rows
            return run
        await asyncio.sleep(1)


async def published(hatchet: Hatchet, key: str) -> list[V1Event]:
    listed = await hatchet.event.aio_list(keys=[NAME_PREFIX + key])
    return listed.rows or []


async def first_published(hatchet: Hatchet, key: str) -> V1Event:
    """Polls until the corvo event for key is published. The caller bounds
    the wait."""
    while not (events := await published(hatchet, key)):
        await asyncio.sleep(1)
    return events[0]


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_a_github_event_is_published_again_as_a_corvo_event(
    hatchet: Hatchet,
) -> None:
    # Covers AE1.
    key = unique("github")
    pushed = await hatchet.event.aio_push(key, {"number": 42})

    async with asyncio.timeout(60):
        run = await finished_run(hatchet, pushed.event_id)
        corvo = await first_published(hatchet, key)

    assert run.status == V1TaskStatus.COMPLETED
    assert corvo.payload is not None
    event = Event.model_validate(corvo.payload)
    assert event.name == NAME_PREFIX + key
    assert event.source == "github"
    assert event.payload == {"number": 42}
    assert event.external_id == pushed.event_id
    assert event.parent_id is None
    assert event.root_id == event.id


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_an_event_that_cannot_be_a_corvo_event_fails_once(
    hatchet: Hatchet,
) -> None:
    # Covers AE3. 21 characters of prefix and 235 of key make a 256-character
    # name.
    key = "github:" + "a" * 228
    pushed = await hatchet.event.aio_push(key, {})

    async with asyncio.timeout(60):
        await finished_run(hatchet, pushed.event_id)
        # Long enough for a retry, which Hatchet queues at once, to show.
        await asyncio.sleep(5)
        run = await finished_run(hatchet, pushed.event_id)

    assert run.status == V1TaskStatus.FAILED
    assert run.retry_count == 0
    assert await published(hatchet, key) == []


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_only_a_listed_prefix_starts_the_parser(hatchet: Hatchet) -> None:
    # Covers AE2.
    jira = await hatchet.event.aio_push(unique("jira"), {})
    key = unique("github")
    pushed = await hatchet.event.aio_push(key, {})

    async with asyncio.timeout(60):
        await finished_run(hatchet, pushed.event_id)
        corvo = await first_published(hatchet, key)
        # A run of an event pushed after the corvo event was published: the
        # engine has handled the events before it by then.
        later = await hatchet.event.aio_push(unique("github"), {})
        await finished_run(hatchet, later.event_id)

    # A listed event's id is the one its runs are found by, so the corvo
    # event's id below can find a run if the parser started one.
    received = (await hatchet.event.aio_list(keys=[key])).rows or []
    assert [event.metadata.id for event in received] == [pushed.event_id]
    for event_id in (jira.event_id, corvo.metadata.id):
        listed = await hatchet.runs.aio_list(triggering_event_external_id=event_id)
        assert listed.rows == [], event_id
