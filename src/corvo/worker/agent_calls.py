"""What the main profile needs to call the agent tasks, without them.

The agent tasks run on the agent worker alone, and the main profile never
imports one (KTD26). This module holds what both sides share: a by-name stub
of each agent task, which a workflow spawns the task through, and the task
input of each agent that works in a directory, which is the agent's input
plus the working directory. The task imports that input from here, so a
caller and the task validate the same class.

A stub has its task's name and its task's input and output classes, and
belongs on no profile's list: a worker serving it would take the task's runs
and raise. tests/unit/corvo/worker/test_registration.py checks both.

It imports only the agents' models, which import no SDK, and the Hatchet
client.
"""

from corvo.agents.dir_summary.models import DirSummaryInput, DirSummaryOutput
from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.vendors.hatchet.client import hatchet


class DirSummaryTaskInput(DirSummaryInput):
    # The working directory, relative to <root>/workdirs, which the caller
    # has created (KTD7). The task refuses any other before a session starts.
    workdir: str


tone = hatchet.stubs.task(
    name="tone", input_validator=ToneInput, output_validator=ToneOutput
)
dir_summary = hatchet.stubs.task(
    name="dir-summary",
    input_validator=DirSummaryTaskInput,
    output_validator=DirSummaryOutput,
)
