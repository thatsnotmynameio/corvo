from corvo.worker.worker import create_worker


def test_worker_is_named() -> None:
    # Which tasks it runs, test_registration.py checks against WORKFLOWS:
    # Worker keeps its own list private.
    assert create_worker().name == "corvo-worker"
