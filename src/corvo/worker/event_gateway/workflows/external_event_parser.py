"""The external event parser: each event another system pushes to Hatchet,
published again as a corvo event.

corvo.worker.event_gateway is where events cross into corvo. Its workflows
and tasks follow the rules of corvo.worker.workflows and corvo.worker.tasks:
the logic lives in corvo.core, at the mirrored path, and never imports
Hatchet; each task is a thin shell that adapts Hatchet's event to the core
and publishes what the core returns. Every definition here goes on the main
profile's list in corvo.worker.profiles.main.

The workflow listens to EXTERNAL_PREFIXES, each as `prefix:*`. The engine
matches that as an anchored SQL LIKE, so the parser never receives its own
`corvo:external_event:` events. A prefix added here reaches Hatchet when the
worker restarts, since the worker registers its triggers when it starts.

The task is not idempotent: a retry after a publish that succeeded
publishes a second corvo event, with a new id and the same external_id. It
keeps RETRIES all the same, so that a publish the engine refused is tried
again; those duplicates are the accepted cost. An event that cannot become a
corvo event fails at once with NonRetryableException, since a retry would
fail the same way. The input is Hatchet's permissive EmptyModel for the same
reason: a stricter input_validator fails inside the task, where Hatchet
retries it like any error.
"""

import logging
from typing import Final
from uuid import UUID

from hatchet_sdk import Context, EmptyModel, NonRetryableException
from pydantic import BaseModel

from corvo.core.event_gateway.external_event_parser import parse
from corvo.vendors.hatchet.client import hatchet
from corvo.worker.defaults import EVENT_SCHEDULE_TIMEOUT, EXECUTION_TIMEOUT, RETRIES

logger = logging.getLogger(__name__)

# The sources whose events become corvo events, each the part of an event's
# key before its first ':'.
EXTERNAL_PREFIXES: Final = ("github",)


class ParsedOutput(BaseModel):
    # The corvo event's id, and the Hatchet id of the event it was published as.
    event_id: UUID
    published_id: str


external_event_parser = hatchet.workflow(
    name="external-event-parser",
    on_events=[f"{prefix}:*" for prefix in EXTERNAL_PREFIXES],
)


@external_event_parser.task(
    name="external_event_parser",
    retries=RETRIES,
    execution_timeout=EXECUTION_TIMEOUT,
    schedule_timeout=EVENT_SCHEDULE_TIMEOUT,
)
async def parse_external_event(input: EmptyModel, ctx: Context) -> ParsedOutput:
    key, external_id = ctx.triggering_event_key, ctx.triggering_event_id
    payload = input.model_dump()
    logger.info("received %s, Hatchet id %s", key, external_id)
    logger.debug("payload of %s, Hatchet id %s: %s", key, external_id, payload)
    try:
        event = parse(key, external_id, payload)
    except ValueError as e:
        # Pydantic's ValidationError is a ValueError too.
        logger.error("%s, Hatchet id %s, is no corvo event: %s", key, external_id, e)
        raise NonRetryableException(f"{key!r} is no corvo event") from e
    try:
        published = await hatchet.event.aio_push(
            event.name, event.model_dump(mode="json")
        )
    except Exception:
        logger.exception(
            "publishing %s for %s, Hatchet id %s, failed", event.name, key, external_id
        )
        raise
    logger.info("published %s, corvo id %s", event.name, event.id)
    return ParsedOutput(event_id=event.id, published_id=published.event_id)
