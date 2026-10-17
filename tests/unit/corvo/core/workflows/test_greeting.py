from corvo.core.workflows.greeting import shout


def test_shout_upper_cases_the_message() -> None:
    assert shout("Hello, corvo!") == "HELLO, CORVO!"
