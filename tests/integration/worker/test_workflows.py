import asyncio
import uuid

import pytest
from hatchet_sdk import Hatchet, V1TaskStatus
from hatchet_sdk.clients.admin import TaskRunDetail
from hatchet_sdk.runnables.workflow import Standalone

from corvo.worker.tasks.hello import HelloInput, HelloOutput
from corvo.worker.workflows.greeting import GreetingInput, ShoutOutput
from corvo.worker.workflows.greeting_rounds import (
    APPROVAL_EVENT,
    GreetingRoundsInput,
    GreetingRoundsOutput,
)

DONE = {V1TaskStatus.COMPLETED, V1TaskStatus.FAILED, V1TaskStatus.CANCELLED}


async def finished_tasks(
    hatchet: Hatchet, run_id: str, count: int
) -> dict[str, TaskRunDetail]:
    """Polls the run's details until its `count` tasks are done, keyed by
    name, as Hatchet's on_failure test does. The caller bounds the wait."""
    while True:
        details = await hatchet.runs.aio_get_details(run_id)
        tasks = {task.readable_id: task for task in details.task_runs.values()}
        if len(tasks) == count and all(task.status in DONE for task in tasks.values()):
            return tasks
        await asyncio.sleep(1)


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_hello_runs_on_the_worker(hatchet: Hatchet) -> None:
    # A stub, as Hatchet's docs trigger a task from another service: by its
    # name and schemas, without its code.
    hello = hatchet.stubs.task(
        name="hello", input_validator=HelloInput, output_validator=HelloOutput
    )

    async with asyncio.timeout(30):
        output = await hello.aio_run(HelloInput(name="corvo"))

    assert output == HelloOutput(message="Hello, corvo!")


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_greeting_shouts_hellos_greeting(hatchet: Hatchet) -> None:
    greeting = hatchet.stubs.workflow(name="greeting", input_validator=GreetingInput)

    async with asyncio.timeout(30):
        result = await greeting.aio_run(GreetingInput(name="corvo"))

    assert ShoutOutput.model_validate(result["shout"]) == ShoutOutput(
        message="HELLO, CORVO!"
    )


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_greeting_hands_a_failure_to_its_handler(hatchet: Hatchet) -> None:
    greeting = hatchet.stubs.workflow(name="greeting", input_validator=GreetingInput)

    async with asyncio.timeout(30):
        run = await greeting.aio_run(
            GreetingInput(name="corvo", force_failure=True), wait_for_result=False
        )
        with pytest.raises(Exception, match="shout was asked to fail"):
            await run.aio_result()
        tasks = await finished_tasks(hatchet, run.workflow_run_id, count=3)

    # Hatchet appends -on-failure to the name a failure handler declares.
    handler = tasks["on_failure-on-failure"]
    assert tasks["greet"].status == V1TaskStatus.COMPLETED
    assert tasks["shout"].status == V1TaskStatus.FAILED
    assert handler.status == V1TaskStatus.COMPLETED
    # hello's message, so the child the handler spawned ran.
    assert HelloOutput.model_validate(handler.output) == HelloOutput(
        message="Hello, greeting's failure handler!"
    )


def greeting_rounds_stub(
    hatchet: Hatchet,
) -> Standalone[GreetingRoundsInput, GreetingRoundsOutput]:
    return hatchet.stubs.task(
        name="greeting-rounds",
        input_validator=GreetingRoundsInput,
        output_validator=GreetingRoundsOutput,
    )


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_greeting_rounds_takes_the_approved_path(hatchet: Hatchet) -> None:
    key = f"approved-{uuid.uuid4().hex[:8]}"
    # Pushed before the run starts, so only the wait's lookback can match it.
    await hatchet.event.aio_push(
        APPROVAL_EVENT, {"approval_key": key}, scope=f"approval_key:{key}"
    )

    async with asyncio.timeout(60):
        output = await greeting_rounds_stub(hatchet).aio_run(
            GreetingRoundsInput(
                name="corvo",
                approval_key=key,
                # hello's first reply has 13 characters, so a second round runs.
                target_length=20,
                max_rounds=5,
                approval_timeout_seconds=30,
            )
        )

    assert output == GreetingRoundsOutput(
        rounds=2,
        message="Hello, Hello, corvo!!",
        shout="HELLO, HELLO, HELLO, CORVO!!!",
        outcome="approved",
    )


@pytest.mark.usefixtures("worker")
@pytest.mark.asyncio(loop_scope="session")
async def test_greeting_rounds_times_out_without_an_approval(hatchet: Hatchet) -> None:
    async with asyncio.timeout(60):
        output = await greeting_rounds_stub(hatchet).aio_run(
            GreetingRoundsInput(
                name="corvo",
                approval_key=f"unapproved-{uuid.uuid4().hex[:8]}",
                target_length=1,
                max_rounds=1,
                approval_timeout_seconds=3,
            )
        )

    assert output.outcome == "timed_out"
