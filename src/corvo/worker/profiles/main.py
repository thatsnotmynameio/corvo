from corvo.worker.profiles import Profile
from corvo.worker.tasks.hello import hello
from corvo.worker.workflows.dir_review import dir_review
from corvo.worker.workflows.greeting import greeting
from corvo.worker.workflows.greeting_rounds import greeting_rounds

# Every task and workflow corvo-worker serves, one line each.
# tests/worker/test_registration.py fails, naming the definition, when one in
# corvo.worker.tasks or corvo.worker.workflows is missing here. Workflows
# spawn agents through corvo.worker.agent_calls' stubs, never an agent task.
PROFILE = Profile(
    name="corvo-worker",
    workflows=[
        hello,
        greeting,
        greeting_rounds,
        dir_review,
    ],
)
