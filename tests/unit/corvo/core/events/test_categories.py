from uuid import UUID

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from corvo.core.events.categories import (
    UNKNOWN,
    Category,
    CategoryField,
    CategorySnapshot,
)

BILLING = Category(id=UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a01"), name="billing")
INVOICES = Category(
    id=UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a02"), name="invoices", parent=BILLING
)


class Holder(BaseModel):
    """A model with the event's category field, and nothing else."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: CategoryField = Field(default_factory=UNKNOWN.snapshot)


def test_a_nested_category_has_the_names_from_the_top_down() -> None:
    assert INVOICES.path == ("billing", "invoices")


def test_unknown_is_a_fixed_category_with_no_parent() -> None:
    assert UNKNOWN.id == UUID("01a144e8-0c89-7152-85f8-52e3da44f2e4")
    assert UNKNOWN.name == "unknown"
    assert UNKNOWN.parent is None
    assert UNKNOWN.path == ("unknown",)


def test_a_snapshot_carries_the_category_id_and_path() -> None:
    assert INVOICES.snapshot() == CategorySnapshot(
        id=INVOICES.id, path=("billing", "invoices")
    )


@pytest.mark.parametrize(
    "name",
    ["bill.ing", "bill ing", "bill/ing", "", "a" * 256],
    ids=["a dot", "a space", "a slash", "empty", "too long"],
)
def test_a_category_name_outside_the_alphabet_fails(name: str) -> None:
    with pytest.raises(ValidationError):
        Category(id=BILLING.id, name=name)


def test_a_name_with_letters_digits_underscores_and_hyphens_passes() -> None:
    assert Category(id=BILLING.id, name="bill-ing_2").name == "bill-ing_2"


def test_a_name_of_255_characters_passes() -> None:
    assert Category(id=BILLING.id, name="a" * 255).name == "a" * 255


def test_a_snapshot_with_an_empty_path_fails() -> None:
    with pytest.raises(ValidationError):
        CategorySnapshot(id=BILLING.id, path=())


def test_a_snapshot_path_outside_the_alphabet_fails() -> None:
    with pytest.raises(ValidationError):
        CategorySnapshot(id=BILLING.id, path=("billing", "in voices"))


def test_assigning_to_a_category_fails() -> None:
    with pytest.raises(ValidationError):
        INVOICES.name = "bills"  # type: ignore[misc]
    assert INVOICES.name == "invoices"


def test_assigning_to_a_snapshot_fails() -> None:
    snapshot = INVOICES.snapshot()

    with pytest.raises(ValidationError):
        snapshot.path = ("bills",)  # type: ignore[misc]
    assert snapshot.path == ("billing", "invoices")


def test_a_field_the_category_models_do_not_define_fails() -> None:
    with pytest.raises(ValidationError):
        Category.model_validate({"id": BILLING.id, "name": "billing", "kind": "x"})
    with pytest.raises(ValidationError):
        CategorySnapshot.model_validate(
            {"id": BILLING.id, "path": ["billing"], "kind": "x"}
        )


def test_a_category_field_keeps_the_snapshot_of_a_category() -> None:
    assert Holder(category=INVOICES).category == INVOICES.snapshot()
    assert Holder(category=INVOICES.snapshot()).category == INVOICES.snapshot()


def test_a_category_field_defaults_to_unknown() -> None:
    assert Holder().category == UNKNOWN.snapshot()


def test_a_category_field_reads_back_a_category_no_code_holds() -> None:
    text = (
        '{"category": {"id": "0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a09",'
        ' "path": ["sales", "leads"]}}'
    )

    category = Holder.model_validate_json(text).category

    assert category.id == UUID("0199f2a4-6c1e-7a3b-9d10-5e2f8c7b4a09")
    assert category.path == ("sales", "leads")
    assert Holder.model_validate_json(Holder(category=category).model_dump_json()) == (
        Holder(category=category)
    )
