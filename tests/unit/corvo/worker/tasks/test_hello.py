from corvo.worker.defaults import EXECUTION_TIMEOUT, RETRIES
from corvo.worker.tasks.hello import HelloInput, HelloOutput, hello


async def test_hello_greets_by_name() -> None:
    output = await hello.aio_mock_run(HelloInput(name="corvo"))

    assert output == HelloOutput(message="Hello, corvo!")


def test_hello_declares_the_defaults() -> None:
    [task] = hello.tasks

    assert task.retries == RETRIES
    assert task.execution_timeout == EXECUTION_TIMEOUT
