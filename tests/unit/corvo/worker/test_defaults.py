from datetime import timedelta

from hatchet_sdk import ConcurrencyLimitStrategy

from corvo.worker.defaults import (
    AGENT_CONCURRENCY,
    AGENT_DEADLINE_MARGIN,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_SCHEDULE_TIMEOUT,
    AGENT_WAITING_EXECUTION_TIMEOUT,
)

# How late Hatchet's timeout poller may notice a timed-out attempt.
DETECTION_LAG = timedelta(seconds=30)


def test_an_agent_waiting_timeout_covers_its_one_attempt() -> None:
    # retries=0: one attempt, queued behind the cap, then run.
    worst_case = AGENT_SCHEDULE_TIMEOUT + AGENT_EXECUTION_TIMEOUT + DETECTION_LAG

    assert AGENT_WAITING_EXECUTION_TIMEOUT >= worst_case


def test_the_session_budget_ends_before_hatchets_timeout() -> None:
    assert timedelta(0) < AGENT_DEADLINE_MARGIN < AGENT_EXECUTION_TIMEOUT


def test_the_agent_cap_is_one_strategy_for_the_tenant() -> None:
    assert AGENT_CONCURRENCY.name == "corvo-agents"
    assert AGENT_CONCURRENCY.is_tenant_scoped
    assert AGENT_CONCURRENCY.max_runs == 2
    assert (
        AGENT_CONCURRENCY.limit_strategy == ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN
    )
