from hatchet_sdk import Context
from pydantic import BaseModel

from corvo.core.tasks.hello import greet
from corvo.worker.hatchet_client import hatchet


class HelloInput(BaseModel):
    name: str


class HelloOutput(BaseModel):
    message: str


@hatchet.task(name="hello", input_validator=HelloInput)
async def hello(input: HelloInput, ctx: Context) -> HelloOutput:
    return HelloOutput(message=greet(input.name))
