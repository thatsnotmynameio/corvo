from datetime import timedelta

from corvo.worker.defaults import (
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
