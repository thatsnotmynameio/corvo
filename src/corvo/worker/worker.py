from typing import Any

from hatchet_sdk import Worker
from hatchet_sdk.runnables.workflow import BaseWorkflow

from corvo.worker.hatchet_client import hatchet
from corvo.worker.tasks.hello import hello
from corvo.worker.workflows.greeting import greeting
from corvo.worker.workflows.greeting_rounds import greeting_rounds

# Every task and workflow corvo-worker serves, one line each.
# tests/worker/test_registration.py fails, naming the definition, when one in
# corvo.worker.tasks, corvo.worker.workflows or corvo.worker.agents is missing
# here.
WORKFLOWS: list[BaseWorkflow[Any]] = [
    hello,
    greeting,
    greeting_rounds,
]


def create_worker() -> Worker:
    return hatchet.worker("corvo-worker", workflows=WORKFLOWS)


def main() -> None:
    create_worker().start()
