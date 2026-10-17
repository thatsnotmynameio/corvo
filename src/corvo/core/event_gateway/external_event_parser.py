"""An external event as a corvo event.

The core of `corvo.vendors.hatchet.integrations.github.listener`: the
workflow reads the event Hatchet delivered, and this module decides what corvo
event it becomes.

This module imports only `corvo.core.events` and the standard library.
"""

from collections.abc import Mapping
from typing import Any, Final

from corvo.core.events.event import Event

NAME_PREFIX: Final = "corvo:external_event:"


def parse(
    key: str | None, external_id: str | None, payload: Mapping[str, Any]
) -> Event:
    """The root corvo event for the external event published as `key`, with
    `external_id` as its id in the system that produced it.

    A key with nothing before its first ':', or no id, raises ValueError; an
    event the key or payload makes invalid raises Pydantic's ValidationError.
    """
    source, colon, _ = (key or "").partition(":")
    if not key or not source or not colon:
        raise ValueError(f"the key {key!r} has no source before a ':'")
    if not external_id:
        raise ValueError(f"the event {key!r} has no id")
    return Event(
        name=NAME_PREFIX + key,
        source=source,
        external_id=external_id,
        payload=payload,
    )
