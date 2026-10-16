def count_words(text: str) -> int:
    """The words in text: its runs of non-whitespace."""
    return len(text.split())
