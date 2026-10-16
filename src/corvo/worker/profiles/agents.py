from corvo.worker.agent_runtime import startup
from corvo.worker.agents.tone import tone
from corvo.worker.defaults import AGENT_MAX_RUNS
from corvo.worker.profiles import Profile

# Every agent task the agent worker serves, and nothing else, one line each.
# tests/worker/test_registration.py fails, naming the definition, when one in
# corvo.worker.agents is missing here. It takes as many runs as the cap lets
# run at once. It registers them only once its isolation checks pass, and on
# SIGTERM it ends its sessions before Hatchet's graceful exit.
PROFILE = Profile(
    name="corvo-agent-worker",
    workflows=[
        tone,
    ],
    slots=AGENT_MAX_RUNS,
    before_start=startup.before_start,
    on_sigterm=startup.on_sigterm,
)
