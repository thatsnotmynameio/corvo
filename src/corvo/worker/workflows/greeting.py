"""A DAG workflow, the example to copy for a new one.

Every node of a DAG receives the workflow's input, so the DAG reuses a task
from corvo.worker.tasks by spawning it as a child run from one of its own
steps. A step reads its parent step's output from the context. The failure
handler runs once when any step has failed.

The logic lives in corvo.core, at the mirrored path, and never imports
Hatchet. Each step is a thin shell: it adapts Hatchet's input and output to
the core and spawns or reads runs, holding no logic of its own.

A step that waits on a child run declares retries=0 and
WAITING_EXECUTION_TIMEOUT, and every other step passes the defaults; the
reasons are in corvo.worker.defaults. While it waits, the step holds a
worker slot its child cannot use: when every slot holds a waiting step, the
children never start and fail on Hatchet's scheduling timeout. A step that
spawns many children, or waits long, belongs in a durable task, which
Hatchet can evict to free its slot while it waits.
https://docs.hatchet.run/v1/durable-tasks.md

Declare the workflow and its steps at module top level and add the workflow
to the main profile's list in corvo.worker.profiles.main. Keep Hatchet's
by-name stubs out of this area: a stub is a workflow too, and every workflow
here is one the worker must serve.
"""

from hatchet_sdk import Context, NonRetryableException
from pydantic import BaseModel

from corvo.core.workflows import greeting as core
from corvo.worker.defaults import (
    EXECUTION_TIMEOUT,
    RETRIES,
    WAITING_EXECUTION_TIMEOUT,
)
from corvo.worker.hatchet_client import hatchet
from corvo.worker.tasks.hello import HelloInput, HelloOutput, hello


class GreetingInput(BaseModel):
    name: str
    # Makes shout fail, to show the failure handler at work.
    force_failure: bool = False


class GreetOutput(BaseModel):
    message: str


class ShoutOutput(BaseModel):
    message: str


greeting = hatchet.workflow(name="greeting", input_validator=GreetingInput)


@greeting.task(
    name="greet",
    retries=0,
    execution_timeout=WAITING_EXECUTION_TIMEOUT,
)
async def greet(input: GreetingInput, ctx: Context) -> GreetOutput:
    output = await hello.aio_run(HelloInput(name=input.name))
    return GreetOutput(message=output.message)


@greeting.task(
    name="shout",
    parents=[greet],
    retries=RETRIES,
    execution_timeout=EXECUTION_TIMEOUT,
)
async def shout(input: GreetingInput, ctx: Context) -> ShoutOutput:
    if input.force_failure:
        # Not retried, so the failure handler runs at once.
        raise NonRetryableException("shout was asked to fail")
    return ShoutOutput(message=core.shout(ctx.task_output(greet).message))


@greeting.on_failure_task(
    name="on_failure",
    retries=0,
    execution_timeout=WAITING_EXECUTION_TIMEOUT,
)
async def on_failure(input: GreetingInput, ctx: Context) -> HelloOutput:
    return await hello.aio_run(HelloInput(name="greeting's failure handler"))
