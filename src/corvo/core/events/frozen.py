"""The immutable containers that hold an event's labels and payload.

An event is immutable at every depth, and Pydantic's frozen models are
immutable only at the top: a dict or list in a field can still change. So
labels become a FrozenDict, and a payload becomes FrozenDicts and tuples at
every depth. Both turn back into plain dicts and lists when serialized, so
an event's JSON is plain JSON.

Fields are typed as read-only Mappings and Sequences, never as FrozenDict:
mypy then rejects a write and accepts a plain dict or list as input. A
payload reader narrows a value with Mapping and Sequence, checking str
first, since isinstance(value, dict) or isinstance(value, list) never
matches.

The event's modules import this one, so it imports only Pydantic and the
standard library.
"""

import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Annotated, Any, Self, override

from pydantic import (
    AfterValidator,
    GetPydanticSchema,
    JsonValue,
    PlainSerializer,
    StringConstraints,
)
from pydantic_core import core_schema


class FrozenDict[K, V](Mapping[K, V]):
    """A mapping that refuses every write, and hashes and pickles."""

    __slots__ = ("_data", "_hash")

    def __init__(self, data: Mapping[K, V] | None = None) -> None:
        self._data: dict[K, V] = dict(data) if data is not None else {}
        self._hash: int | None = None

    @override
    def __getitem__(self, key: K) -> V:
        return self._data[key]

    @override
    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    @override
    def __len__(self) -> int:
        return len(self._data)

    # Mapping's own versions copy both sides, or catch a KeyError on a miss.
    @override
    def __eq__(self, other: object) -> bool:
        if isinstance(other, FrozenDict):
            return self._data == other._data
        if isinstance(other, Mapping):
            return self._data == dict(other.items())
        return NotImplemented

    @override
    def __contains__(self, key: object) -> bool:
        return key in self._data

    @override
    def __hash__(self) -> int:
        if self._hash is None:
            self._hash = hash(frozenset(self._data.items()))
        return self._hash

    @override
    def __repr__(self) -> str:
        return f"FrozenDict({self._data!r})"

    def __reduce__(self) -> tuple[type[Self], tuple[dict[K, V]]]:
        return (type(self), (self._data,))


# What a payload holds once frozen, as its readers see it.
type JsonRead = (
    Mapping[str, JsonRead] | Sequence[JsonRead] | str | int | float | bool | None
)


def freeze(value: JsonValue) -> JsonRead:
    """Plain JSON as FrozenDicts and tuples at every depth. A NaN or an
    infinity fails: JSON has neither, and Pydantic would write them as
    null, so the event would not read back equal (KTD4)."""
    if isinstance(value, dict):
        return FrozenDict({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(freeze(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("a payload number must be finite")
    return value


def thaw(value: object) -> object:
    """FrozenDicts and tuples as plain dicts and lists at every depth, and
    everything else as it is."""
    if isinstance(value, FrozenDict | dict):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | list):
        return [thaw(item) for item in value]
    return value


def _thaw_input(value: object) -> object:
    # A Python payload nested past the interpreter's recursion limit fails
    # like any other invalid payload, as a ValidationError (KTD10).
    try:
        return thaw(value)
    except RecursionError:
        raise ValueError("a payload must not nest this deeply") from None


def _payload_schema(
    _source: object, handler: Callable[[Any], core_schema.CoreSchema]
) -> core_schema.CoreSchema:
    # Thawed first, so a payload may hold another event's payload or any
    # part of it; then validated as plain JSON, and frozen.
    plain = handler(dict[str, JsonValue])
    return core_schema.no_info_before_validator_function(
        _thaw_input,
        core_schema.no_info_after_validator_function(freeze, plain),
        serialization=core_schema.plain_serializer_function_ser_schema(
            thaw, return_schema=plain
        ),
    )


# A JSON object, frozen at every depth.
type Payload = Annotated[Mapping[str, JsonRead], GetPydanticSchema(_payload_schema)]

# Prometheus' label names; strict, so bytes and numbers fail.
type LabelKey = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$", strict=True)
]
type LabelValue = Annotated[str, StringConstraints(min_length=1, strict=True)]


type Labels = Annotated[
    Mapping[LabelKey, LabelValue],
    AfterValidator(FrozenDict),
    PlainSerializer(dict, return_type=dict[str, str]),
]
