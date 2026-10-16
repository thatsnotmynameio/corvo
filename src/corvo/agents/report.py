"""What a session reported about itself, and the failure that carries it.

An agent's run returns a RunReport with its output, or raises AgentRunFailed
with one. The worker imports this module, so it imports only Pydantic and
the standard library, never the SDK.
"""

from pydantic import BaseModel


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
