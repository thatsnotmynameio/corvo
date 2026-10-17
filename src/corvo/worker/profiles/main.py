from corvo.vendors.hatchet.integrations.github.listener import (
    external_event_parser,
)
from corvo.worker.profiles import Profile

# Every task and workflow corvo-worker serves, one line each.
# tests/unit/corvo/worker/test_registration.py fails, naming the definition,
# when one in corvo.worker.tasks, corvo.worker.workflows or
# corvo.vendors.hatchet.integrations is missing here. Workflows spawn agents through
# corvo.worker.agent_calls' stubs, never an agent task.
PROFILE = Profile(
    name="corvo-worker",
    workflows=[
        external_event_parser,
    ],
)
