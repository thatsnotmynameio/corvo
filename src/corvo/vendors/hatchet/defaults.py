"""Hatchet's retries and timeouts for corvo, which every task passes.

Each declaration passes these as keyword arguments, and overrides one by
passing a different value. Hatchet's TaskDefaults does not fit: it reaches
only a workflow's steps, never standalone tasks or failure handlers.
"""

from datetime import timedelta

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

# How long a run an outside event started waits for a worker, in place of
# Hatchet's 5 minutes. The engine cancels a run that waits longer, so every
# event that arrives while the main worker is down past it would be lost,
# with no log from corvo. A day covers an outage noticed the next morning.
EVENT_SCHEDULE_TIMEOUT = timedelta(hours=24)
