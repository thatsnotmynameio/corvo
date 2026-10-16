from datetime import timedelta

from hatchet_sdk import ConcurrencyLimitStrategy

from corvo.worker.defaults import (
    AGENT_CONCURRENCY,
    EXECUTION_TIMEOUT,
    RETRIES,
    WAITING_EXECUTION_TIMEOUT,
)

# Hatchet's default scheduling timeout: how long a child may queue. The
# engine sets it again for each retry.
SCHEDULING_TIMEOUT = timedelta(minutes=5)

# How late Hatchet's timeout poller may notice a timed-out attempt.
DETECTION_LAG = timedelta(seconds=30)


def test_waiting_timeout_covers_every_attempt_of_a_child() -> None:
    attempts = RETRIES + 1
    worst_case = (EXECUTION_TIMEOUT + SCHEDULING_TIMEOUT + DETECTION_LAG) * attempts

    assert WAITING_EXECUTION_TIMEOUT >= worst_case


def test_the_agent_cap_is_one_strategy_for_the_tenant() -> None:
    assert AGENT_CONCURRENCY.name == "corvo-agents"
    assert AGENT_CONCURRENCY.is_tenant_scoped
    assert AGENT_CONCURRENCY.max_runs == 2
    assert (
        AGENT_CONCURRENCY.limit_strategy == ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN
    )
