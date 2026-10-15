"""The tone agent's models, which the worker imports.

This module imports only Pydantic and the standard library, never the SDK:
the worker reads it, and the worker must not reach the SDK (KTD2). Keep here
everything the worker needs to know about the agent.
"""

from typing import Literal

from pydantic import BaseModel, Field

type Tone = Literal["friendly", "neutral", "unfriendly"]

# The agent works in no directory, so the container mounts none.
WRITES_WORKDIR = False


class ToneInput(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ToneVerdict(BaseModel):
    """The schema the session's structured output must match."""

    tone: Tone


class ToneOutput(BaseModel):
    tone: Tone
    # Derived by the core twin, corvo.core.agents.tone, not by the session.
    friendly: bool
