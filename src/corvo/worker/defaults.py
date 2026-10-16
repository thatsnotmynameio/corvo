"""corvo's retries, timeouts and agent limits, which every task and agent passes.

Each declaration passes these as keyword arguments, and overrides one by
passing a different value. Hatchet's TaskDefaults does not fit: it reaches
only a workflow's steps, never standalone tasks or failure handlers.
"""

from datetime import timedelta

from hatchet_sdk import ConcurrencyExpression, ConcurrencyLimitStrategy

# A corvo task is idempotent, so a failed attempt is retried. A task that is
# not raises NonRetryableException or declares retries=0.
# https://docs.hatchet.run/v1/retry-policies.md
RETRIES = 3

# Hatchet's own default is 60 seconds.
# https://docs.hatchet.run/v1/timeouts.md
EXECUTION_TIMEOUT = timedelta(minutes=10)

# For a non-durable step that waits on a child run, which declares retries=0
# with this timeout: retrying it would spawn a second child while the first
# may still run. It covers one child declared with the defaults: each of its
# attempts may queue up to Hatchet's 5-minute scheduling timeout, which the
# engine sets again on every retry, then run for EXECUTION_TIMEOUT, so
# 4 x 15 minutes, plus a margin for the engine noticing each timeout. A
# durable task keeps RETRIES, since its retry replays from checkpoints and
# spawns nothing twice.
WAITING_EXECUTION_TIMEOUT = timedelta(minutes=65)

# How many agent runs execute at once across the worker pool. The strategy
# is named and scoped to the tenant, so every agent task shares the one
# limit, and so does every deployment on the tenant. CANCEL_IN_PROGRESS
# would kill paid runs, so the runs over the cap queue in turn. The agents
# profile takes AGENT_MAX_RUNS slots.
# https://docs.hatchet.run/v1/concurrency.md
AGENT_MAX_RUNS = 2
AGENT_CONCURRENCY = ConcurrencyExpression(
    expression="'corvo-agents'",
    max_runs=AGENT_MAX_RUNS,
    limit_strategy=ConcurrencyLimitStrategy.GROUP_ROUND_ROBIN,
    name="corvo-agents",
    is_tenant_scoped=True,
)

# An agent task declares retries=0 with the AGENT_ values below: a retry
# re-runs and re-pays the whole session, and the SDK already retries the
# API's errors itself.

# The longest example session, plus starting its sandbox.
AGENT_EXECUTION_TIMEOUT = timedelta(minutes=15)

# The session budget ends this long before Hatchet's timeout, which leaves
# the worker time to report and clean up. Hatchet's timer starts at
# assignment, so a budget equal to the timeout would never end first.
AGENT_DEADLINE_MARGIN = timedelta(seconds=60)

# How long an agent run may queue behind AGENT_CONCURRENCY's cap, or for an
# agent worker that can isolate it, which the engine counts against the
# schedule timeout.
AGENT_SCHEDULE_TIMEOUT = timedelta(minutes=60)

# For a step that waits on an agent child, in place of
# WAITING_EXECUTION_TIMEOUT: the child's one attempt may queue for
# AGENT_SCHEDULE_TIMEOUT, then run for AGENT_EXECUTION_TIMEOUT, so 75
# minutes, plus a margin for the engine noticing the timeout.
AGENT_WAITING_EXECUTION_TIMEOUT = timedelta(minutes=80)

# Each session's cgroup limits. Anthropic's hardened example starts at 1 GiB
# and one CPU; the memory is doubled for the engine and its tools, with no
# swap. The process limit sits above the engine's threads.
AGENT_MEMORY = 2 * 1024**3
AGENT_CPUS = 1
AGENT_PIDS_LIMIT = 256

# The size of each of a session's two tmpfs, its /tmp and its home, which
# its cgroup's memory counts.
AGENT_TMPFS_SIZE = 512 * 1024**2
