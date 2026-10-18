import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

from corvo.core.events.categories import UNKNOWN, Category
from corvo.core.events.event import Event

ROOT_ID = UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a10")
CHILD_ID = UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a11")
NOON_UTC = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

BILLING = Category(id=UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a01"), name="billing")
INVOICES = Category(
    id=UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a02"), name="invoices", parent=BILLING
)


def full_event() -> Event:
    return Event(
        id=CHILD_ID,
        parent_id=ROOT_ID,
        root_id=ROOT_ID,
        external_id="evt-1",
        name="issue.opened",
        payload_version=2,
        source="corvo.worker",
        subject="issue/42",
        occurred_at=NOON_UTC,
        category=INVOICES,
        labels={"repo": "corvo"},
        payload={"t": True, "i": 1, "f": 1.0, "nested": {"a": [1, {"b": None}]}},
    )


def test_a_root_event_given_only_a_name_and_source_has_the_defaults() -> None:
    before = datetime.now(UTC)
    event = Event(name="issue.opened", source="corvo.worker")

    assert event.id.version == 7
    assert event.parent_id is None
    assert event.root_id == event.id
    assert event.external_id is None
    assert event.payload_version == 1
    assert event.subject is None
    assert event.occurred_at.tzinfo is UTC
    assert before <= event.occurred_at <= datetime.now(UTC)
    assert event.labels == {}
    assert event.payload == {}


def test_an_event_keeps_its_external_id() -> None:
    event = Event(name="issue.opened", source="corvo.worker", external_id="abc")

    assert event.external_id == "abc"


def test_an_external_id_of_255_characters_passes() -> None:
    event = Event(name="issue.opened", source="corvo.worker", external_id="a" * 255)

    assert event.external_id == "a" * 255


def test_an_event_without_a_category_is_unknown() -> None:
    # Covers AE3.
    event = Event(name="issue.opened", source="corvo.worker")

    assert event.category.id == UNKNOWN.id
    assert event.category.path == ("unknown",)


def test_an_event_records_its_category_id_and_path() -> None:
    event = Event(name="invoice.paid", source="corvo.worker", category=INVOICES)

    assert event.category.id == INVOICES.id
    assert event.category.path == ("billing", "invoices")


def test_occurred_at_is_held_in_utc() -> None:
    # Covers AE10.
    brasilia = timezone(timedelta(hours=-3))

    event = Event(
        name="issue.opened",
        source="corvo.worker",
        occurred_at=datetime(2026, 10, 16, 12, 0, tzinfo=brasilia),
    )

    assert event.occurred_at == datetime(2026, 10, 16, 15, 0, tzinfo=UTC)
    assert event.occurred_at.tzinfo is UTC


def test_a_naive_occurred_at_fails() -> None:
    with pytest.raises(ValidationError):
        Event(
            name="issue.opened",
            source="corvo.worker",
            occurred_at=datetime(2026, 10, 16, 12, 0),
        )


@pytest.mark.parametrize(
    "occurred_at",
    ["0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-12:00"],
    ids=["before the first instant in utc", "after the last instant in utc"],
)
def test_an_occurred_at_outside_utcs_range_fails(occurred_at: str) -> None:
    with pytest.raises(ValidationError):
        Event(name="issue.opened", source="corvo.worker", occurred_at=occurred_at)


@pytest.mark.parametrize(
    "chain",
    [
        {"id": CHILD_ID, "root_id": ROOT_ID},
        {"id": CHILD_ID, "parent_id": ROOT_ID, "root_id": CHILD_ID},
        {"id": CHILD_ID, "parent_id": CHILD_ID, "root_id": ROOT_ID},
        {"id": CHILD_ID, "parent_id": ROOT_ID},
    ],
    ids=[
        "no parent with a foreign root id",
        "a parent with its own id as root id",
        "its own parent",
        "a parent with no root id",
    ],
)
def test_a_broken_chain_fails(chain: dict[str, UUID]) -> None:
    # Covers AE7.
    with pytest.raises(ValidationError):
        Event(name="issue.opened", source="corvo.worker", **chain)


def test_a_child_built_through_the_constructor_passes() -> None:
    event = Event(
        name="issue.labeled",
        source="corvo.worker",
        id=CHILD_ID,
        parent_id=ROOT_ID,
        root_id=ROOT_ID,
    )

    assert (event.parent_id, event.root_id) == (ROOT_ID, ROOT_ID)


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "a" * 256},
        {"source": ""},
        {"subject": ""},
        {"external_id": ""},
        {"external_id": "a" * 256},
        {"payload_version": 0},
        {"payload_version": True},
        {"payload_version": "1"},
        {"payload_version": 1.0},
        {"kind": "issue"},
    ],
    ids=[
        "an empty name",
        "a long name",
        "an empty source",
        "an empty subject",
        "an empty external id",
        "a long external id",
        "version 0",
        "version True",
        "version as text",
        "version as a float",
        "an unknown keyword",
    ],
)
def test_an_invalid_field_fails(fields: dict[str, Any]) -> None:
    # Covers AE5.
    with pytest.raises(ValidationError):
        Event(**{"name": "issue.opened", "source": "corvo.worker", **fields})


def test_no_part_of_an_event_can_change() -> None:
    # Covers AE4.
    event = full_event()
    before = full_event()
    labels: Any = event.labels
    nested: Any = event.payload["nested"]

    with pytest.raises(ValidationError):
        event.name = "issue.closed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        labels["step"] = "review"
    with pytest.raises(TypeError):
        nested["a"] = 2
    with pytest.raises(AttributeError):
        nested["a"].append(2)
    assert event == before


def test_an_event_survives_a_json_round_trip() -> None:
    # Covers AE6.
    event = full_event()
    text = event.model_dump_json()

    read = Event.model_validate_json(text)

    assert read == event
    assert read.model_dump_json() == text


def test_an_event_survives_a_round_trip_through_a_json_dict() -> None:
    # Covers AE6.
    event = full_event()
    data = event.model_dump(mode="json")

    read = Event.model_validate(data)

    assert read == event
    assert read.model_dump_json() == event.model_dump_json()


def test_a_json_dict_of_an_event_holds_plain_objects_and_arrays() -> None:
    data = full_event().model_dump(mode="json")

    assert json.loads(json.dumps(data)) == data
    assert data["external_id"] == "evt-1"
    keys = list(data)
    assert keys.index("external_id") == keys.index("root_id") + 1
    assert data["labels"] == {"repo": "corvo"}
    assert data["payload"]["nested"] == {"a": [1, {"b": None}]}
    assert data["category"] == {
        "id": str(INVOICES.id),
        "path": ["billing", "invoices"],
    }


def test_a_stored_event_reads_back_with_its_category_as_stored() -> None:
    # Covers AE9.
    data = full_event().model_dump(mode="json")
    data["category"] = {
        "id": "0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a09",
        "path": ["billing", "invoices"],
    }

    event = Event.model_validate_json(json.dumps(data))

    assert event.category.id == UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a09")
    assert event.category.path == ("billing", "invoices")
    with pytest.raises(ValidationError):
        Event.model_validate_json(json.dumps({**data, "kind": "issue"}))


def test_a_stored_payload_with_nan_fails_to_read_back() -> None:
    # Covers AE8.
    text = full_event().model_dump_json().replace('"f":1.0', '"f":NaN')
    assert "NaN" in text

    with pytest.raises(ValidationError):
        Event.model_validate_json(text)


def test_equal_events_hash_equally() -> None:
    assert full_event() == full_event()
    assert hash(full_event()) == hash(full_event())
