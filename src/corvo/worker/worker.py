import asyncio
import logging
from typing import Any

from hatchet_sdk import Worker
from hatchet_sdk.runnables.workflow import BaseWorkflow

from corvo.settings import get_settings
from corvo.worker.agent_runtime.spec import deployment_label
from corvo.worker.agent_runtime.startup import (
    hatchet_status,
    install_sigterm_hook,
    prepare_until_stopped,
)
from corvo.worker.agents.tone import tone
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
    tone,
]


def create_worker() -> Worker:
    return hatchet.worker("corvo-worker", workflows=WORKFLOWS)


def main() -> None:
    # corvo's own lines, such as the agents' preparation; Hatchet logs
    # through a handler of its own.
    logging.basicConfig(
        level=logging.INFO, format="[%(levelname)s]\t%(name)s -- %(message)s"
    )
    # Before the worker serves anything, so no agent run finds agents
    # unprepared. A SIGTERM meanwhile stops the worker before it starts.
    deployment = deployment_label(hatchet.config.tenant_id, hatchet.config.server_url)
    settings = get_settings()
    if asyncio.run(
        prepare_until_stopped(settings, deployment, hatchet_status(hatchet))
    ):
        return
    worker = create_worker()
    # After the worker installs its own handler, which the hook hands over to.
    install_sigterm_hook()
    worker.start()
