from datetime import timedelta

from corvo.worker.defaults import (
    EXECUTION_TIMEOUT,
    RETRIES,
    WAITING_EXECUTION_TIMEOUT,
)

# Hatchet's default scheduling timeout: how long a child may queue.
SCHEDULING_TIMEOUT = timedelta(minutes=5)


def test_waiting_timeout_covers_a_retried_child() -> None:
    assert WAITING_EXECUTION_TIMEOUT == (
        EXECUTION_TIMEOUT * (RETRIES + 1) + SCHEDULING_TIMEOUT
    )
