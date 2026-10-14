from corvo.core.tasks.hello import greet


def test_greet_by_name() -> None:
    assert greet("corvo") == "Hello, corvo!"
