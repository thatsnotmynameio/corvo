from typing import Any

import pytest
from hatchet_sdk import Worker

from corvo.worker.hatchet_client import hatchet
from corvo.worker.worker import WORKFLOWS, create_worker


def test_worker_is_named() -> None:
    assert create_worker().name == "corvo-worker"


def test_worker_serves_the_registration_list(monkeypatch: pytest.MonkeyPatch) -> None:
    # Worker keeps its list private, so this reads what corvo hands Hatchet.
    # test_registration.py checks WORKFLOWS against the three areas.
    received: dict[str, Any] = {}
    build = hatchet.worker

    def spy(name: str, **options: Any) -> Worker:
        received.update(options)
        return build(name, **options)

    monkeypatch.setattr(hatchet, "worker", spy)

    create_worker()

    assert received["workflows"] == WORKFLOWS
