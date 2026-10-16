"""A DAG workflow whose steps spawn agents, the example to copy for one.

It follows corvo.worker.workflows.greeting, whose header holds the rules
every DAG keeps. Step summarize spawns the dir-summary agent on the
workflow's working directory, and step judge spawns the tone agent on that
summary and combines both agents' outputs into a review line.

The main profile reaches an agent only through its stub in
corvo.worker.agent_calls, never by importing the agent task, which runs on
the agent worker alone (KTD26). Declare a stub there, never in this area,
and spawn the agent with the stub's aio_run.

A step that waits on an agent declares retries=0 and
AGENT_WAITING_EXECUTION_TIMEOUT: a retry would spawn, and pay for, the
agent's session again, and the agent's one attempt may queue for its
schedule timeout before it runs for its execution timeout; the reasons are
in corvo.worker.defaults. A step that times out does not cancel its child,
whose own execution timeout ends it.

While it waits, the step holds a slot on the main worker, and none on the
agent worker, where its child runs. A waiting step therefore never keeps
its child from starting, but the main worker's slots full of waiting steps
keep its other tasks queued for as long as the agents take.

The workdir names a directory below <root>/workdirs, which the workflow's
caller creates before it triggers the workflow and deletes after the run;
docs/agents.md has its rules.

Declare the workflow and its steps at module top level and add the workflow
to the main profile's list in corvo.worker.profiles.main.
"""

from hatchet_sdk import Context
from pydantic import BaseModel

from corvo.agents.dir_summary.models import DirSummaryOutput
from corvo.agents.tone.models import ToneInput
from corvo.core.workflows import dir_review as core
from corvo.worker import agent_calls
from corvo.worker.agent_calls import DirSummaryTaskInput
from corvo.worker.defaults import AGENT_WAITING_EXECUTION_TIMEOUT
from corvo.worker.hatchet_client import hatchet


class DirReviewInput(BaseModel):
    # The working directory, relative to <root>/workdirs (KTD7).
    workdir: str


class DirReviewOutput(BaseModel):
    review: str


dir_review = hatchet.workflow(name="dir-review", input_validator=DirReviewInput)


@dir_review.task(
    name="summarize",
    retries=0,
    execution_timeout=AGENT_WAITING_EXECUTION_TIMEOUT,
)
async def summarize(input: DirReviewInput, ctx: Context) -> DirSummaryOutput:
    return await agent_calls.dir_summary.aio_run(
        DirSummaryTaskInput(workdir=input.workdir)
    )


@dir_review.task(
    name="judge",
    parents=[summarize],
    retries=0,
    execution_timeout=AGENT_WAITING_EXECUTION_TIMEOUT,
)
async def judge(input: DirReviewInput, ctx: Context) -> DirReviewOutput:
    summary = ctx.task_output(summarize)
    verdict = await agent_calls.tone.aio_run(ToneInput(text=summary.summary))
    return DirReviewOutput(
        review=core.review(tone=verdict.tone, word_count=summary.word_count)
    )
