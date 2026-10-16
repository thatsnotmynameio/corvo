"""The categories that classify events, and the snapshot an event keeps.

Categories nest: each has an optional parent, and its path is the names
from the top category down to it. They are data that will live in the
database and grow there; no code declares one, except `UNKNOWN`, the one
category this contract defines, which an event without a category has.

An event never holds a Category. It keeps a CategorySnapshot, the
category's id and its path at the moment of creation, so it reads back
from JSON when the category no longer exists.

The event's modules import this one, so it imports only Pydantic and the
standard library.
"""

from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StringConstraints

# The alphabet of Postgres' ltree labels since Postgres 16, so a path
# becomes an ltree without loss.
type CategoryName = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,255}$")]


class Category(BaseModel):
    """A category, with its parent when it has one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    name: CategoryName
    parent: Category | None = None

    @property
    def path(self) -> tuple[str, ...]:
        """The names from the top category down to this one."""
        if self.parent is None:
            return (self.name,)
        return (*self.parent.path, self.name)

    def snapshot(self) -> CategorySnapshot:
        return CategorySnapshot(id=self.id, path=self.path)


class CategorySnapshot(BaseModel):
    """A category's id and its path when the snapshot was taken."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    path: Annotated[tuple[CategoryName, ...], Field(min_length=1)]


UNKNOWN = Category(id=UUID("01a144e8-0c89-7152-85f8-52e3da44f2e4"), name="unknown")


def _snapshot_of(value: object) -> object:
    return value.snapshot() if isinstance(value, Category) else value


# A field that takes a Category or a snapshot, and keeps a snapshot.
type CategoryField = Annotated[CategorySnapshot, BeforeValidator(_snapshot_of)]
