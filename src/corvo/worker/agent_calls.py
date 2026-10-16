"""What the main profile needs to call the agent tasks, without them.

The agent tasks run on the agent worker alone, and the main profile never
imports one (KTD26). This module holds what both sides share: the task
input of each agent that works in a directory, which is the agent's input
plus the working directory. The task imports it from here, so a caller and
the task validate the same class.

It imports only the agents' models, which import no SDK.
"""

from corvo.agents.dir_summary.models import DirSummaryInput


class DirSummaryTaskInput(DirSummaryInput):
    # The working directory, relative to <root>/workdirs, which the caller
    # has created (KTD7). The task refuses any other before a session starts.
    workdir: str
