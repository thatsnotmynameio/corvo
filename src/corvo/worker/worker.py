from typing import Any

from hatchet_sdk import Worker
from hatchet_sdk.runnables.workflow import BaseWorkflow

from corvo.worker.hatchet_client import hatchet
from corvo.worker.tasks.hello import hello
from corvo.worker.workflows.greeting import greeting

# Every task and workflow corvo-worker serves, one line each.
# tests/worker/test_registration.py fails, naming the definition, when one in
# corvo.worker.tasks or corvo.worker.workflows is missing here.
WORKFLOWS: list[BaseWorkflow[Any]] = [
    hello,
    greeting,
]


def create_worker() -> Worker:
    return hatchet.worker("corvo-worker", workflows=WORKFLOWS)


def main() -> None:
    create_worker().start()
