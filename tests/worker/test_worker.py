from corvo.worker.worker import create_worker


def test_worker_is_named() -> None:
    # Which tasks it runs, the integration tests show: Worker keeps them
    # private.
    assert create_worker().name == "corvo-worker"
