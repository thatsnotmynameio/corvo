import pytest
from hatchet_sdk import Hatchet

from corvo.worker.workflows.hello import HelloInput, HelloOutput


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_hello_runs_on_the_worker(hatchet: Hatchet) -> None:
    # A stub, as Hatchet's docs trigger a task from another service: by its
    # name and schemas, without its code.
    hello = hatchet.stubs.task(
        name="hello", input_validator=HelloInput, output_validator=HelloOutput
    )

    output = await hello.aio_run(HelloInput(name="corvo"))

    assert output == HelloOutput(message="Hello, corvo!")
