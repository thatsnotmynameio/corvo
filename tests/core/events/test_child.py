from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from corvo.core.events.categories import UNKNOWN, Category
from corvo.core.events.event import INHERIT, Event

NOON_UTC = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)

BILLING = Category(id=UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a01"), name="billing")
INVOICES = Category(
    id=UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a02"), name="invoices", parent=BILLING
)


def labeled_root() -> Event:
    return Event(
        name="issue.opened",
        source="corvo.server",
        subject="issue/42",
        occurred_at=NOON_UTC,
        category=INVOICES,
        labels={"repo": "corvo"},
        payload={"number": 42},
    )


def test_a_chain_of_three_shares_the_root_id() -> None:
    # Covers AE1.
    a = Event(name="issue.opened", source="corvo.server")

    b = a.child(name="issue.triaged", source="corvo.worker")
    c = b.child(name="issue.labeled", source="corvo.worker")

    assert b.parent_id == a.id
    assert c.parent_id == b.id
    assert a.root_id == b.root_id == c.root_id == a.id
    assert len({a.id, b.id, c.id}) == 3


def test_a_child_inherits_only_what_it_asks_for() -> None:
    # Covers AE2.
    child = labeled_root().child(
        name="issue.triaged", source="corvo.worker", labels=INHERIT
    )

    assert child.labels == {"repo": "corvo"}
    assert child.subject is None
    assert child.category == UNKNOWN.snapshot()


def test_a_child_with_nothing_inherited_gets_none_of_its_parent() -> None:
    child = labeled_root().child(name="issue.triaged", source="corvo.worker")

    assert child.category == UNKNOWN.snapshot()
    assert child.labels == {}
    assert child.subject is None
    assert child.payload == {}
    assert child.payload_version == 1


def test_a_child_inherits_everything_it_asks_for() -> None:
    parent = labeled_root()

    child = parent.child(
        name="issue.triaged",
        source="corvo.worker",
        category=INHERIT,
        labels=INHERIT,
        subject=INHERIT,
    )

    assert child.category == parent.category
    assert child.labels == parent.labels
    assert child.subject == "issue/42"


def test_a_child_of_a_read_back_parent_inherits_its_stored_category() -> None:
    data = labeled_root().model_dump(mode="json")
    data["category"] = {
        "id": "0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a09",
        "path": ["shipping", "parcels"],
    }
    parent = Event.model_validate(data)

    child = parent.child(name="parcel.sent", source="corvo.worker", category=INHERIT)

    assert child.category.id == UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a09")
    assert child.category.path == ("shipping", "parcels")


def test_a_child_given_its_own_labels_has_only_those() -> None:
    child = labeled_root().child(
        name="issue.triaged", source="corvo.worker", labels={"step": "review"}
    )

    assert child.labels == {"step": "review"}


def test_a_child_given_its_parents_labels_and_more_has_both() -> None:
    parent = labeled_root()

    child = parent.child(
        name="issue.triaged",
        source="corvo.worker",
        labels={**parent.labels, "step": "review"},
    )

    assert child.labels == {"repo": "corvo", "step": "review"}


def test_a_child_carries_what_it_is_given() -> None:
    parent = labeled_root()
    before = datetime.now(UTC)

    child = parent.child(
        name="invoice.paid",
        source="corvo.worker",
        payload_version=2,
        category=BILLING,
        subject="invoice/7",
        payload={"issue": parent.payload, "paid": True},
    )

    assert child.category == BILLING.snapshot()
    assert child.subject == "invoice/7"
    assert child.payload_version == 2
    assert child.payload == {"issue": {"number": 42}, "paid": True}
    assert before <= child.occurred_at <= datetime.now(UTC)


def test_a_child_given_occurred_at_keeps_it_in_utc() -> None:
    brasilia = timezone(timedelta(hours=-3))

    child = labeled_root().child(
        name="issue.triaged",
        source="corvo.worker",
        occurred_at=datetime(2026, 10, 16, 12, 0, tzinfo=brasilia),
    )

    assert child.occurred_at == datetime(2026, 10, 16, 15, 0, tzinfo=UTC)
    assert child.occurred_at.tzinfo is UTC


@pytest.mark.parametrize(
    "labels",
    [{"step": ""}, {"1step": "review"}],
    ids=["an empty value", "a key starting with a digit"],
)
def test_a_child_given_an_invalid_label_fails(labels: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        labeled_root().child(name="issue.triaged", source="corvo.worker", labels=labels)
