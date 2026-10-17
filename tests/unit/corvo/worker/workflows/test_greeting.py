import pytest
from hatchet_sdk import NonRetryableException

from corvo.worker.defaults import (
    EXECUTION_TIMEOUT,
    RETRIES,
    WAITING_EXECUTION_TIMEOUT,
)
from corvo.worker.tasks.hello import HelloInput, HelloOutput, hello
from corvo.worker.workflows.greeting import (
    GreetingInput,
    GreetOutput,
    ShoutOutput,
    greet,
    on_failure,
    shout,
)


class HelloReplacement:
    """Stands in for hello.aio_run, which would spawn a child run on Hatchet."""

    def __init__(self) -> None:
        self.received: list[HelloInput] = []

    async def __call__(self, input: HelloInput) -> HelloOutput:
        self.received.append(input)
        return HelloOutput(message=f"Hi, {input.name}.")


@pytest.fixture
def replaced_hello(monkeypatch: pytest.MonkeyPatch) -> HelloReplacement:
    replacement = HelloReplacement()
    monkeypatch.setattr(hello, "aio_run", replacement)
    return replacement


async def test_greet_returns_hellos_message(replaced_hello: HelloReplacement) -> None:
    output = await greet.aio_mock_run(GreetingInput(name="corvo"))

    assert output == GreetOutput(message="Hi, corvo.")
    assert replaced_hello.received == [HelloInput(name="corvo")]


async def test_shout_shouts_greets_message() -> None:
    output = await shout.aio_mock_run(
        GreetingInput(name="corvo"),
        parent_outputs={"greet": {"message": "Hello, corvo!"}},
    )

    assert output == ShoutOutput(message="HELLO, CORVO!")


async def test_shout_fails_without_retrying_when_forced() -> None:
    with pytest.raises(NonRetryableException):
        await shout.aio_mock_run(
            GreetingInput(name="corvo", force_failure=True),
            parent_outputs={"greet": {"message": "Hello, corvo!"}},
        )


async def test_on_failure_returns_hellos_output(
    replaced_hello: HelloReplacement,
) -> None:
    output = await on_failure.aio_mock_run(
        GreetingInput(name="corvo", force_failure=True)
    )

    assert output == HelloOutput(message="Hi, greeting's failure handler.")
    assert replaced_hello.received == [HelloInput(name="greeting's failure handler")]


def test_steps_that_wait_on_a_child_do_not_retry() -> None:
    for step in (greet, on_failure):
        assert step.retries == 0
        assert step.execution_timeout == WAITING_EXECUTION_TIMEOUT


def test_shout_declares_the_defaults() -> None:
    assert shout.retries == RETRIES
    assert shout.execution_timeout == EXECUTION_TIMEOUT
