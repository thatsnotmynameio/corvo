"""A durable workflow, the example to copy for a new one.

A durable task composes by spawning: here it spawns the task hello in a loop,
then the DAG greeting, then waits for an approval event or a timeout. Each
spawn and each wait is a checkpoint: on a retry or after an eviction, Hatchet
replays the task from its event log instead of running those steps again.
https://docs.hatchet.run/v1/durable-tasks.md

The code between checkpoints must be deterministic, so that a replay takes
every branch the first run took:
- Only spawn children, call the durable context, or call pure functions from
  corvo.core. Push side effects such as database or API calls into a child.
- Decide only on checkpoint outputs and the input, never on wall-clock time,
  random values or anything read from outside. ctx.aio_now() is the clock
  that replays.
- Changing the order of spawns and waits, or a loop's bound, while runs are
  in flight fails those runs on replay.

The logic lives in corvo.core, at the mirrored path, and never imports
Hatchet. The task is a thin shell: it adapts Hatchet's input and output to
the core and spawns, waits and reads results, holding no logic of its own.

A failed child raises TaskRunError, which fails this run; handling it is the
caller's decision, not this example's. A durable task keeps the default
RETRIES, since its retry spawns nothing twice. Its waits count toward its
execution timeout, so the timeout covers the longest wait.

The approval matches its event by the run's approval_key, so each approval
request needs a key of its own: with a reused key, an older approval within
the lookback approves the new run. An approval pushed after the timeout
matches nothing and is lost.

Declare the task at module top level and add it to WORKFLOWS in
corvo.worker.worker. Keep Hatchet's by-name stubs out of this area: a stub is
a workflow too, and every workflow here is one the worker must serve.
"""

from datetime import timedelta
from typing import Literal

from hatchet_sdk import DurableContext, SleepCondition, UserEventCondition, or_
from pydantic import BaseModel, Field

from corvo.core.workflows import greeting_rounds as core
from corvo.worker.defaults import RETRIES
from corvo.worker.hatchet_client import hatchet
from corvo.worker.tasks.hello import HelloInput, hello
from corvo.worker.workflows.greeting import GreetingInput, ShoutOutput, greeting

APPROVAL_EVENT = "greeting:approved"

# An approval pushed this long before the wait began still counts, so one
# pushed while the rounds ran is not lost.
APPROVAL_LOOKBACK = timedelta(minutes=5)


class GreetingRoundsInput(BaseModel):
    name: str
    # Lowercase letters, digits and hyphens only, since the key is written
    # into the wait's CEL expression.
    approval_key: str = Field(pattern=r"^[a-z0-9-]+$")
    target_length: int = Field(ge=1, le=200)
    # Counts every spawn of hello, the first one included.
    max_rounds: int = Field(ge=1, le=10)
    # Below the 15-minute TTL after which Hatchet evicts a waiting task.
    approval_timeout_seconds: int = Field(ge=1, le=600)


class GreetingRoundsOutput(BaseModel):
    rounds: int
    message: str
    shout: str
    outcome: Literal["approved", "timed_out"]


@hatchet.durable_task(
    name="greeting-rounds",
    input_validator=GreetingRoundsInput,
    retries=RETRIES,
    # The longest wait, 10 minutes, plus children that succeed at once.
    execution_timeout=timedelta(minutes=30),
)
async def greeting_rounds(
    input: GreetingRoundsInput, ctx: DurableContext
) -> GreetingRoundsOutput:
    message = (await hello.aio_run(HelloInput(name=input.name))).message
    rounds = 1
    while core.needs_another_round(
        message, input.target_length, rounds, input.max_rounds
    ):
        message = (await hello.aio_run(HelloInput(name=message))).message
        rounds += 1

    result = await greeting.aio_run(GreetingInput(name=message))
    shout = ShoutOutput.model_validate(result["shout"])

    since = await ctx.aio_now() - APPROVAL_LOOKBACK
    matched = await ctx.aio_wait_for(
        "approval",
        or_(
            UserEventCondition(
                event_key=APPROVAL_EVENT,
                expression=f"input.approval_key == '{input.approval_key}'",
                readable_data_key="approved",
                scope=f"approval_key:{input.approval_key}",
                consider_events_since=since,
            ),
            SleepCondition(
                timedelta(seconds=input.approval_timeout_seconds),
                readable_data_key="timeout",
            ),
        ),
    )

    return GreetingRoundsOutput(
        rounds=rounds,
        message=message,
        shout=shout.message,
        outcome="approved" if "approved" in matched["CREATE"] else "timed_out",
    )
