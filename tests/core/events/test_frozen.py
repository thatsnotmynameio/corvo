import copy
import math
import pickle
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from corvo.core.events.frozen import FrozenDict, Labels, Payload


class Holder(BaseModel):
    """A model with the event's two frozen fields, and nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    labels: Labels = Field(default_factory=FrozenDict)
    payload: Payload = Field(default_factory=FrozenDict)


NESTED = {"a": [1, {"b": [2, 3]}], "c": None}


def test_a_frozen_dict_equals_its_dict_and_hashes() -> None:
    frozen = FrozenDict({"a": "b"})

    assert frozen == {"a": "b"}
    assert list(frozen) == ["a"]
    assert len(frozen) == 1
    assert hash(frozen) == hash(FrozenDict({"a": "b"}))


def test_a_frozen_dict_refuses_writes() -> None:
    frozen: Any = FrozenDict({"a": "b"})

    with pytest.raises(TypeError):
        frozen["a"] = "c"
    with pytest.raises(TypeError):
        del frozen["a"]
    assert frozen == {"a": "b"}


def test_a_frozen_dict_survives_pickle_and_deepcopy() -> None:
    frozen = FrozenDict({"a": (1, FrozenDict({"b": "c"}))})

    assert pickle.loads(pickle.dumps(frozen)) == frozen
    assert copy.deepcopy(frozen) == frozen


def test_a_nested_payload_freezes_at_every_depth_and_thaws_back() -> None:
    holder = Holder(payload=NESTED)

    a = holder.payload["a"]
    assert isinstance(holder.payload, FrozenDict)
    assert isinstance(a, tuple)
    assert isinstance(a[1], FrozenDict)
    assert isinstance(a[1]["b"], tuple)
    assert holder.model_dump()["payload"] == NESTED
    assert holder.model_dump(mode="json")["payload"] == NESTED


@pytest.mark.parametrize(
    "payload",
    [[1, 2], {"a": math.nan}, {"a": [{"b": math.inf}]}, {"a": -math.inf}],
    ids=["a list", "NaN", "nested infinity", "minus infinity"],
)
def test_a_payload_that_is_not_a_json_object_fails(payload: object) -> None:
    # Covers AE8.
    with pytest.raises(ValidationError):
        Holder(payload=payload)


@pytest.mark.parametrize(
    "text",
    ['{"payload": {"a": NaN}}', '{"payload": {"a": [Infinity]}}'],
    ids=["NaN", "nested infinity"],
)
def test_a_payload_with_a_non_finite_number_fails_from_json(text: str) -> None:
    # Covers AE8.
    with pytest.raises(ValidationError):
        Holder.model_validate_json(text)


@pytest.mark.parametrize(
    "payload",
    [{"a": b"x"}, {1: "x"}],
    ids=["bytes", "a non-string key"],
)
def test_a_payload_that_is_not_json_fails(payload: object) -> None:
    with pytest.raises(ValidationError):
        Holder(payload=payload)


def test_a_payload_holding_another_payload_freezes_as_plain_data() -> None:
    other = Holder(payload=NESTED).payload
    a = other["a"]
    assert isinstance(a, tuple)

    spread = Holder(payload={**other, "d": a[1], "e": a})

    assert spread == Holder(payload={**NESTED, "d": {"b": [2, 3]}, "e": NESTED["a"]})


@pytest.mark.parametrize(
    "labels",
    [{"repo": 1}, {"1abc": "x"}, {"repo": ""}, {b"repo": "x"}, {"repo": b"x"}],
    ids=[
        "a number value",
        "a key with a digit first",
        "an empty value",
        "a bytes key",
        "a bytes value",
    ],
)
def test_an_invalid_label_fails(labels: object) -> None:
    # Covers AE5.
    with pytest.raises(ValidationError):
        Holder(labels=labels)


def test_labels_freeze_and_turn_back_into_a_dict() -> None:
    holder = Holder(labels={"repo_name": "corvo", "_step": "review"})

    assert isinstance(holder.labels, FrozenDict)
    assert holder.model_dump() == {
        "labels": {"repo_name": "corvo", "_step": "review"},
        "payload": {},
    }


def test_writing_into_labels_or_payload_fails() -> None:
    # Covers AE4.
    holder = Holder(labels={"repo": "corvo"}, payload=NESTED)
    labels: Any = holder.labels
    a: Any = holder.payload["a"]

    with pytest.raises(TypeError):
        labels["step"] = "review"
    with pytest.raises(AttributeError):
        a.append(4)
    with pytest.raises(TypeError):
        a[1]["b"] = 2
    assert holder == Holder(labels={"repo": "corvo"}, payload=NESTED)


def test_frozen_fields_survive_a_json_round_trip() -> None:
    holder = Holder(
        labels={"repo": "corvo"}, payload={"t": True, "i": 1, "f": 1.0, **NESTED}
    )

    text = holder.model_dump_json()

    assert Holder.model_validate_json(text) == holder
    assert Holder.model_validate_json(text).model_dump_json() == text
    assert hash(holder) == hash(Holder.model_validate_json(text))
