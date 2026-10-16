"""The dir-summary agent's models, which the worker imports.

This module imports only Pydantic and the standard library, never the SDK:
the worker reads it, and the worker must not reach the SDK (KTD2). Keep here
everything the worker needs to know about the agent.

The agent's task input, this input plus the working directory, lives in
corvo.worker.agent_calls, where the task and its stub share it.
"""

from pydantic import BaseModel, Field

# The session sees its working directory read-only.
WRITES_WORKDIR = False


# The agent needs nothing but its working directory, which the session gives.
class DirSummaryInput(BaseModel):
    pass


# The schema the session's structured output must match, and the agent's
# output: the agent derives nothing from it. Its JSON Schema goes to the
# model, docstrings included, so the comments here are not docstrings.
class DirSummaryOutput(BaseModel):
    summary: str = Field(min_length=1, max_length=2000)
    # As count_words, the agent's custom tool, counted the summary's words.
    word_count: int = Field(ge=0)
