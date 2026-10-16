"""An agent task with a working directory, the example to copy for one.

It follows corvo.worker.agents.tone, whose header holds the rules every
agent task keeps. A task whose agent works in a directory takes its input
from corvo.worker.agent_calls, the agent's input plus workdir, and hands
run_agent the workdir it names, which run_agent checks before anything
exists (KTD7). The caller creates that directory and deletes it after the
run: docs/agents.md has its rules.
"""

from hatchet_sdk import Context

from corvo.agents.dir_summary import agent
from corvo.agents.dir_summary.models import WRITES_WORKDIR, DirSummaryOutput
from corvo.worker.agent_calls import DirSummaryTaskInput
from corvo.worker.agent_runtime.sessions import run_agent
from corvo.worker.defaults import (
    AGENT_CONCURRENCY,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_SCHEDULE_TIMEOUT,
)
from corvo.worker.hatchet_client import hatchet


@hatchet.task(
    name="dir-summary",
    input_validator=DirSummaryTaskInput,
    retries=0,
    execution_timeout=AGENT_EXECUTION_TIMEOUT,
    schedule_timeout=AGENT_SCHEDULE_TIMEOUT,
    concurrency=AGENT_CONCURRENCY,
)
async def dir_summary(input: DirSummaryTaskInput, ctx: Context) -> DirSummaryOutput:
    return await run_agent(
        agent.run, input, ctx, workdir=input.workdir, writes_workdir=WRITES_WORKDIR
    )
