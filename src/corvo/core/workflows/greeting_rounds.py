def needs_another_round(
    message: str, target_length: int, rounds: int, max_rounds: int
) -> bool:
    return len(message) < target_length and rounds < max_rounds
