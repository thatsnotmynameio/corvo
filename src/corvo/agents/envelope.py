"""What the worker hands an agent's container, and what the container hands back.

The worker writes an AgentRequest to the container's stdin, and the
container's entrypoint (corvo.agents.runner) writes the envelope, a
Succeeded or a Failed, to its stdout; the startup probe writes its
ProbeReport there too, each framed by corvo.agents.frame. The worker
imports this module, so it imports only Pydantic and the standard library,
never the SDK. The worker treats everything the container wrote as
untrusted, and validates it here.
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


class ProbeReport(BaseModel):
    """What corvo-agent probe read inside its container, framed on its stdout.

    The worker compares it with the container spec it asked for and with its
    own fingerprint before it serves any agent (KTD10).
    """

    protocol: Literal[1] = 1
    fingerprint: str
    # The cgroup's limits, as their files read: "max" when unlimited.
    memory_max: str
    cpu_max: str
    pids_max: str
    # The effective capabilities, the hex mask /proc/self/status gives.
    cap_eff: str
    env_names: list[str]
    root_read_only: bool
    # The options of the /tmp and /home/agent mounts.
    mounts: dict[str, list[str]]
    # The default gateway, None without a default route.
    gateway: str | None
    # Whether a one-second TCP connect reached it, or the metadata address.
    gateway_reachable: bool | None
    metadata_reachable: bool
