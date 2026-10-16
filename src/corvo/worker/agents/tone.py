"""An agent task, the example to copy for a new one.

The agent itself lives in corvo.agents, in a package that never imports
Hatchet. The task is a thin shell: it names the agent's package once, hands
the agent's run and its input to run_agent, and returns the agent's output,
holding no logic of its own. run_agent, in corvo.worker.agent_runtime, runs
the session in the run's own sandbox and cgroup, and removes them after it.

An agent task declares retries=0 with the AGENT_ defaults, and a step that
waits on one declares AGENT_WAITING_EXECUTION_TIMEOUT; the reasons are in
corvo.worker.defaults. A retry would re-run and re-pay the whole session,
and the SDK already retries the API's errors itself.

Declare the task at module top level and add it to the agents profile's list
in corvo.worker.profiles.agents, which serves agent tasks and nothing else.
Keep Hatchet's by-name stubs out of this area: a stub is a workflow too, and
every workflow here is one the agent worker must serve.
"""

from hatchet_sdk import Context

from corvo.agents.tone import agent
from corvo.agents.tone.models import WRITES_WORKDIR, ToneInput, ToneOutput
from corvo.worker.agent_runtime.sessions import run_agent
from corvo.worker.defaults import (
    AGENT_CONCURRENCY,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_SCHEDULE_TIMEOUT,
)
from corvo.worker.hatchet_client import hatchet


@hatchet.task(
    name="tone",
    input_validator=ToneInput,
    retries=0,
    execution_timeout=AGENT_EXECUTION_TIMEOUT,
    schedule_timeout=AGENT_SCHEDULE_TIMEOUT,
    concurrency=AGENT_CONCURRENCY,
)
async def tone(input: ToneInput, ctx: Context) -> ToneOutput:
    return await run_agent(agent.run, input, ctx, writes_workdir=WRITES_WORKDIR)
