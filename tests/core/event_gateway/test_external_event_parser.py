from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from corvo.core.event_gateway.external_event_parser import parse
from corvo.core.events.categories import UNKNOWN
from corvo.core.events.frozen import thaw

# "corvo:external_event:" is 21 characters, so a 234-character key makes a
# 255-character name.
LONGEST_KEY = "github:" + "a" * 227


def test_an_external_event_becomes_a_root_corvo_event() -> None:
    # Covers AE1.
    event = parse("github:issue:opened", "evt-1", {"number": 42})

    assert event.name == "corvo:external_event:github:issue:opened"
    assert event.source == "github"
    assert event.payload == {"number": 42}
    assert event.external_id == "evt-1"
    assert event.parent_id is None
    assert event.root_id == event.id
    assert event.category == UNKNOWN.snapshot()
    assert event.labels == {}
    assert event.subject is None
    assert event.payload_version == 1


def test_a_key_with_more_segments_keeps_its_first_as_source() -> None:
    event = parse("github:pull_request:review:submitted", "evt-1", {})

    assert event.name == "corvo:external_event:github:pull_request:review:submitted"
    assert event.source == "github"


def test_each_call_builds_a_new_event_for_the_same_external_id() -> None:
    first = parse("github:issue:opened", "evt-1", {})
    second = parse("github:issue:opened", "evt-1", {})

    assert first.id != second.id
    assert first.external_id == second.external_id == "evt-1"


def test_the_event_occurs_when_it_is_built() -> None:
    before = datetime.now(UTC)
    event = parse("github:issue:opened", "evt-1", {})

    assert before <= event.occurred_at <= datetime.now(UTC)
    assert event.occurred_at.tzinfo is UTC


def test_a_nested_payload_reads_back_equal() -> None:
    payload: dict[str, Any] = {"issue": {"labels": [{"name": "bug"}], "draft": None}}

    event = parse("github:issue:opened", "evt-1", payload)

    assert thaw(event.payload) == payload


def test_a_key_that_makes_the_longest_name_passes() -> None:
    event = parse(LONGEST_KEY, "evt-1", {})

    assert len(event.name) == 255


def test_a_key_that_makes_the_name_too_long_fails() -> None:
    # Covers AE3.
    with pytest.raises(ValidationError):
        parse(LONGEST_KEY + "a", "evt-1", {})


@pytest.mark.parametrize(
    "key",
    ["", None, "github", ":issue:opened"],
    ids=["an empty key", "no key", "a key with no colon", "nothing before the colon"],
)
def test_a_key_without_a_source_fails(key: str | None) -> None:
    with pytest.raises(ValueError, match="no source"):
        parse(key, "evt-1", {})


@pytest.mark.parametrize("external_id", ["", None], ids=["an empty id", "no id"])
def test_an_event_without_an_external_id_fails(external_id: str | None) -> None:
    with pytest.raises(ValueError, match="no id"):
        parse("github:issue:opened", external_id, {})


def test_a_payload_with_an_infinity_fails() -> None:
    with pytest.raises(ValidationError):
        parse("github:issue:opened", "evt-1", {"n": float("inf")})
