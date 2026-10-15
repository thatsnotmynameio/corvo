"""What the worker hands an agent's container, and what the container hands back.

The worker writes an AgentRequest to request.json in the run directory, and
the container's entrypoint (corvo.agents.runner) writes the envelope, a
Succeeded or a Failed, to result.json. The worker imports this module, so it
imports only Pydantic and the standard library, never the SDK. The worker
treats every file the container wrote as untrusted, and validates it here.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, JsonValue, TypeAdapter


class RunReport(BaseModel):
    """What a session reported about itself, under the SDK's names: None
    where it reported nothing."""

    subtype: str | None = None
    num_turns: int | None = None
    total_cost_usd: float | None = None
    session_id: str | None = None


class AgentRunFailed(Exception):
    """A session that ended without valid structured output."""

    def __init__(self, reason: str, report: RunReport) -> None:
        super().__init__(reason)
        self.reason = reason
        self.report = report


class AgentRequest(BaseModel):
    protocol: Literal[1] = 1
    # A package directly under corvo.agents, such as tone.
    agent: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    input: dict[str, JsonValue]
    # The session's budget: past it, the run fails with reason "deadline".
    budget_seconds: float = Field(gt=0)


class Succeeded(BaseModel):
    protocol: Literal[1] = 1
    status: Literal["ok"] = "ok"
    output: dict[str, JsonValue]
    report: RunReport


class Failed(BaseModel):
    protocol: Literal[1] = 1
    status: Literal["failed"] = "failed"
    reason: str
    report: RunReport


ENVELOPE: TypeAdapter[Succeeded | Failed] = TypeAdapter(
    Annotated[Succeeded | Failed, Field(discriminator="status")]
)
