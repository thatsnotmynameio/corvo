import pytest

from corvo.core.agents.tone import is_friendly


def test_a_friendly_tone_is_friendly() -> None:
    assert is_friendly("friendly")


@pytest.mark.parametrize("tone", ["neutral", "unfriendly"])
def test_any_other_tone_is_not_friendly(tone: str) -> None:
    assert not is_friendly(tone)
