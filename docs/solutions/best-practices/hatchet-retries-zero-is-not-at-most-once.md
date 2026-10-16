---
title: Hatchet's retries=0 does not make a task run at most once
date: 2026-10-16
category: best-practices
module: worker tasks on Hatchet
problem_type: best_practice
component: background_job
severity: high
applies_when:
  - A Hatchet task is not idempotent, such as one that pays for an API session, charges, sends or spawns
  - A task holds a resource that must be released before its slot is reused, such as a process tree or a cgroup
  - A worker can stop, lose its connection or be redeployed while it runs tasks
retire_when: "Hatchet stops re-queuing a task with retries=0 after a lost worker, or waits for a cancelled task's cleanup before freeing its slot; check the engine's ListTasksToReassign query and MaxInternalRetryCount, and hatchet_sdk/worker/runner/runner.py's handle_cancel_action, at the versions corvo pins"
tags: [hatchet, retries, retry-count, heartbeat, idempotency, cancellation, worker-slots, agent-worker]
---

# Hatchet's retries=0 does not make a task run at most once

## Context

The agents skeleton (stack #31 to #46) runs paid Claude sessions as Hatchet tasks, so a second run of one is money nobody asked to spend. Declaring `retries=0` looked like enough: corvo's defaults say so for every non-idempotent task (`src/corvo/worker/defaults.py:47`, "a retry re-runs and re-pays the whole session"). While the plan was being researched, reading the engine and SDK at the versions corvo pins showed two behaviors that `retries=0` does not cover. The plan records them (`docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md`, Dependencies and KTD8), but they apply to any non-idempotent task in corvo, not only to agents.

1. **The engine re-runs a task after a lost worker, whatever its `retries`.** Engine v0.110.5, the version `compose.yaml` pins, reassigns every task, unless it was evicted, on a worker whose last heartbeat is older than 30 seconds (`ListTasksToReassign` in hatchet-dev/hatchet v0.110.5, `pkg/repository/sqlcv1/tasks.sql`, upstream: `w."lastHeartbeatAt" < NOW() - INTERVAL '30 seconds'`). It counts that as an internal failure, up to `MaxInternalRetryCount`, which defaults to 10 (hatchet-dev/hatchet v0.110.5, `pkg/config/server/server.go`, upstream, overridable with `SERVER_MAX_INTERNAL_RETRY_COUNT`). The re-run has `ctx.retry_count` above zero, and in-process it looks the same as a replay from the dashboard.
2. **A cancel frees the task's slot before its cleanup ends.** In hatchet-sdk 1.42.1, a timeout and a cancel reach the worker as the same `CANCEL_STEP_RUN`. `handle_cancel_action` (`hatchet_sdk/worker/runner/runner.py` in the installed SDK) sets the context's cancellation flag, sleeps one second, cancels the asyncio task, and in its `finally` cleans the run up, which frees the slot. It does not wait for the task's own `finally`, so the next run can take the slot while the last one is still cleaning up.

## Guidance

For a task that must not run twice, `retries=0` is necessary but not enough. Add the three guards below, plus a test that proves them.

1. **Fail a re-run before any side effect.** Check `ctx.retry_count` first, and say in the error how to run the task again on purpose. In `run_agent` (`src/corvo/worker/agent_runtime/sessions.py:209`):

   ```python
   if ctx.retry_count > 0:
       raise AgentFailed(
           f"agent {agent}: this is a re-run (retry {ctx.retry_count}), which "
           "fails rather than pay for the session again. Trigger a new run, "
           "or replay the parent step, which spawns a fresh child."
       )
   ```

   A failure here is a failed run, so the engine does not retry it again. corvo chose to fail every re-run over accepting them, because in-process a re-queue after a lost worker and a deliberate replay cannot be told apart.
2. **Release what outlives the task before the first `await` of its end.** Once a cancel arrives, assume the slot is reused within about a second. `run_agent` writes the run cgroup's `cgroup.kill` before anything else on every way a session ends, then lets the SDK close its transport, which can take up to 15 seconds. It does that cleanup shielded and bounded by `CLEANUP_TIMEOUT` (`sessions.py:80`, `:257-277` and `:280-326`). Cleanup that only sits in a `finally` behind an `await` may still be running when the next run starts.
3. **On a graceful stop, fail the in-flight runs while the worker still sends heartbeats.** If a stopping worker just exits, its runs miss heartbeats and are re-queued. The agent worker's `on_sigterm` (`src/corvo/worker/agent_runtime/startup.py:310`) refuses new runs and kills every in-flight session's cgroup before Hatchet's graceful exit. Those runs fail while the worker still answers, so the engine records a failure and re-queues nothing (`startup.py:28-32`).
4. **Prove it across the heartbeat window.** `test_a_sigterm_fails_the_running_session_for_good` (`tests/integration/worker/test_agents.py:214-235`) stops the agent worker during a run, starts it again, and waits 35 seconds, past the 30-second window. It then asserts that the task is `FAILED` with `worker stopping` and that `retry_count == 0`. A test that checks the status right after the stop would pass even if the run were re-queued a few seconds later.

## Why This Matters

Without guard 1, a worker lost for 30 seconds can run the same paid session up to 10 more times. Without guard 2, a cancelled session's process tree can still be running in the slot the next run was given. Without guard 3, every redeploy turns its in-flight runs into re-queued runs, so with guard 1 in place each redeploy shows up as unexplained re-run failures instead of `worker stopping`. Operators see the guards' messages documented in `docs/agents.md`, under "Re-runs fail" and "What a failed run's log shows".

## When to Apply

- Any new Hatchet task whose body has an effect that must not happen twice: paying, charging, sending, writing outside its own state, or spawning a child that does one of these.
- Any task that starts processes, opens long-lived resources or holds a lock that must be gone before the next run on that worker starts.
- Any worker profile that a redeploy stops while runs are in flight.

A durable task whose effects sit behind checkpoints is the exception: its retry replays from its event log (`src/corvo/worker/defaults.py:21-28`).

## Examples

- The `tone` and `dir-summary` agent tasks declare `retries=0` and go through `run_agent`, which holds guards 1 and 2. The agent worker's start holds guard 3. The guards came in #41 and #43.
- `docs/agents.md`, "Re-runs fail", tells an operator what to do with the failure: trigger a new run, or replay the parent step, which starts a fresh child.

## Related

- `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md`: Dependencies (the engine's re-queue and the SDK's cancel) and KTD8 (why re-runs fail and why the kill comes first).
- [Seccomp socket filter bypassed by high argument bits and 32-bit socketcall](../security-issues/seccomp-socket-filter-bypassed-by-high-bits-and-32-bit-socketcall.md): the agent worker's other learning, on a different problem.
