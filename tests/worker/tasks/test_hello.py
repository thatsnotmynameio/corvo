from corvo.worker.tasks.hello import HelloInput, HelloOutput, hello


async def test_hello_greets_by_name() -> None:
    output = await hello.aio_mock_run(HelloInput(name="corvo"))

    assert output == HelloOutput(message="Hello, corvo!")
