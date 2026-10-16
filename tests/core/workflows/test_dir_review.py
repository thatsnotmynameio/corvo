from corvo.core.workflows.dir_review import review


def test_the_review_names_the_tone_and_the_word_count() -> None:
    assert review(tone="friendly", word_count=12) == (
        "A friendly summary, 12 words long."
    )
