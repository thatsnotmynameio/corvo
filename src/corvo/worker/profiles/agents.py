from corvo.worker.defaults import AGENT_MAX_RUNS
from corvo.worker.profiles import Profile

# Every agent task the agent worker serves, and nothing else, one line each.
# tests/worker/test_registration.py fails, naming the definition, when one in
# corvo.worker.agents is missing here. It takes as many runs as the cap lets
# run at once.
PROFILE = Profile(
    name="corvo-agent-worker",
    workflows=[],
    slots=AGENT_MAX_RUNS,
)
