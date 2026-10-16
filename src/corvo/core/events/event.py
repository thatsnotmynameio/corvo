"""The event: an immutable record that something happened.

An event is validated when created and never changes after, at any depth.
It carries its own id, its parent's id and its chain's root id, so a chain
of events reads like the spans of a trace. A root event is built through
the constructor, with no parent, and its root id is its own id; every
other event is built by its parent's `child`.

Every invalid event fails with Pydantic's ValidationError.

This module imports only Pydantic and the standard library.
"""

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum
from typing import Annotated, Any, Final, Self
from uuid import UUID

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from corvo.core.events.categories import (
    UNKNOWN,
    Category,
    CategoryField,
    CategorySnapshot,
)
from corvo.core.events.frozen import FrozenDict, JsonRead, Labels, Payload


class Inherit(Enum):
    """The one value that asks a child for its parent's value."""

    INHERIT = "inherit"


INHERIT: Final = Inherit.INHERIT

type Text = Annotated[str, StringConstraints(min_length=1, max_length=255)]


def _in_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _own_id(data: dict[str, Any]) -> Any:
    # A root event's root id; a child is always given its chain's.
    return data["id"]


class Event(BaseModel):
    """An event, its fields in the order of its JSON."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID = Field(default_factory=uuid.uuid7)
    parent_id: UUID | None = None
    root_id: UUID = Field(default_factory=_own_id)
    name: Text
    payload_version: Annotated[int, Field(ge=1, strict=True)] = 1
    source: Text
    subject: Text | None = None
    occurred_at: Annotated[AwareDatetime, AfterValidator(_in_utc)] = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    category: CategoryField = Field(default_factory=UNKNOWN.snapshot)
    labels: Labels = Field(default_factory=FrozenDict)
    payload: Payload = Field(default_factory=FrozenDict)

    @model_validator(mode="after")
    def _chain_holds(self) -> Self:
        if self.parent_id is None:
            if self.root_id != self.id:
                raise ValueError("an event with no parent is its own root")
        elif self.parent_id == self.id:
            raise ValueError("an event cannot be its own parent")
        elif self.root_id == self.id:
            raise ValueError("an event with a parent needs its chain's root_id")
        return self

    def child(
        self,
        *,
        name: str,
        source: str,
        payload_version: int = 1,
        payload: Mapping[str, JsonRead] | None = None,
        occurred_at: datetime | None = None,
        category: Category | CategorySnapshot | Inherit | None = None,
        labels: Mapping[str, str] | Inherit | None = None,
        subject: str | Inherit | None = None,
    ) -> Event:
        """The next event in this one's chain. Category, labels and subject
        are the parent's only when given INHERIT; given nothing, the child
        has none of them, and its category is unknown."""
        given: dict[str, object] = {
            "payload": payload,
            "occurred_at": occurred_at,
            "category": self.category if category is INHERIT else category,
            "labels": self.labels if labels is INHERIT else labels,
            "subject": self.subject if subject is INHERIT else subject,
        }
        # Through the constructor, so every validator runs again; what is
        # not given takes the field's default.
        return Event(
            parent_id=self.id,
            root_id=self.root_id,
            name=name,
            payload_version=payload_version,
            source=source,
            **{field: value for field, value in given.items() if value is not None},
        )
