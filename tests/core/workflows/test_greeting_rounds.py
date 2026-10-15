from corvo.core.workflows.greeting_rounds import needs_another_round


def test_another_round_while_the_message_is_short_and_rounds_remain() -> None:
    assert needs_another_round("Hello!", target_length=7, rounds=1, max_rounds=2)


def test_no_round_once_the_message_reaches_its_target_length() -> None:
    assert not needs_another_round("Hello!", target_length=6, rounds=1, max_rounds=2)


def test_no_round_at_max_rounds_with_the_message_still_short() -> None:
    assert not needs_another_round("Hello!", target_length=7, rounds=2, max_rounds=2)
