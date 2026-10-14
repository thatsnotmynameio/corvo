"""A standalone Hatchet task, the example to copy for a new one.

The logic lives in corvo.core, at the mirrored path, and never imports
Hatchet. The task is a thin shell: it adapts Hatchet's input and output to
the core and holds no logic of its own.

Declare each task at module top level, passing the defaults from
corvo.worker.defaults. Keep Hatchet's by-name stubs out of this area: a stub
is a workflow too, and the worker registers every one declared here.
"""

from hatchet_sdk import Context
from pydantic import BaseModel

from corvo.core.tasks.hello import greet
from corvo.worker.defaults import EXECUTION_TIMEOUT, RETRIES
from corvo.worker.hatchet_client import hatchet


class HelloInput(BaseModel):
    name: str


class HelloOutput(BaseModel):
    message: str


@hatchet.task(
    name="hello",
    input_validator=HelloInput,
    retries=RETRIES,
    execution_timeout=EXECUTION_TIMEOUT,
)
async def hello(input: HelloInput, ctx: Context) -> HelloOutput:
    return HelloOutput(message=greet(input.name))
