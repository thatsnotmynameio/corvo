"""The permission profiles corvo-worker serves, one module each.

A profile is what differs between workers: the Hatchet worker's name, the
tasks and workflows it registers, its slots and its start and stop hooks.
corvo-worker imports only the profile CORVO_WORKER_PROFILE names, by its
dotted path here, so the main profile never imports an agent task. This
module imports no profile module.

A new profile is a module with its PROFILE, a line in PROFILES, an area pair
in tests/worker/test_registration.py and a compose service.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from hatchet_sdk.runnables.workflow import BaseWorkflow


@dataclass(frozen=True)
class Profile:
    name: str
    workflows: list[BaseWorkflow[Any]]
    # Hatchet's default when unset.
    slots: int | None = None
    # Runs before the Hatchet worker exists; it exits the process to refuse.
    before_start: Callable[[], None] | None = None
    # Runs on SIGTERM, then hands over to Hatchet's graceful exit.
    on_sigterm: Callable[[], None] | None = None


PROFILES = {
    "main": "corvo.worker.profiles.main",
    "agents": "corvo.worker.profiles.agents",
}
