import pytest

from corvo.core.agents.dir_summary import count_words


@pytest.mark.parametrize(
    ("text", "count"),
    [("one two  three\n", 3), ("", 0), ("  \n\t ", 0), ("word", 1)],
    ids=["three words", "empty", "only spaces", "one word"],
)
def test_words_are_counted_between_whitespace(text: str, count: int) -> None:
    assert count_words(text) == count
