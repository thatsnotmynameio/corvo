---
title: Worker Skeleton U2 Operation Defaults - Plan
type: feat
date: 2026-10-14
topic: worker-tasks-workflows-skeleton-u2-defaults
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md
execution: code
---

# Worker Skeleton U2 Operation Defaults - Plan

## Goal Capsule

- **Objective:** corvo's retries and execution-timeout defaults live in one module, and `hello` declares them and opens with the header rules a copier needs.
- **Parent:** `docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md` holds the whole plan; this is part 2 of 5. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** U1. **Blocks:** U4 builds on this part directly; U5 through U4.
- **Stop conditions:** stop and ask when the SDK behaves differently from this plan on hatchet-sdk 1.42.1 and engine v0.110.5, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U1: `hello` in `src/corvo/worker/tasks/hello.py` over `src/corvo/core/tasks/hello.py`; test folders are packages.

## Product Contract

### Summary

Adds `src/corvo/worker/defaults.py` with `RETRIES`, `EXECUTION_TIMEOUT` and `WAITING_EXECUTION_TIMEOUT`, has `hello` pass them, and gives `hello.py` the header comment every example carries.

### Context

Every later declaration passes these constants, so they must exist before the DAG and durable examples. R6 and R3 are completed only by U5, the last example to apply them; this part builds them for `hello`.

### Key Decisions

- **Protect against engine lock-in through the hexagonal split, not a wrapper.** Business logic lives in corvo's core, which never imports Hatchet, and tasks stay thin shells that call it. Changing engines would mean rewriting the shells. The examples demonstrate it: each worker module has a core twin at the mirrored path. (session-settled: user-directed — chosen over examples that keep their logic inside the task and state the rule only as a comment: contributors copy the code, not the comment.) Governs R3, R12.

### Requirements

**Layout and conventions**

- R3. The rule that business logic lives in the core and tasks stay thin shells is written at the top of each example file a contributor copies.

**Operation defaults**

- R6. corvo-wide defaults for retries and execution timeout are defined once and applied by every task and workflow declaration, which may override them.

### Scope Boundaries

- `WAITING_EXECUTION_TIMEOUT` is defined here but first used by U4's spawning steps.

## Planning Contract

### Key Technical Decisions

- KTD1. **Defaults are plain constants in `src/corvo/worker/defaults.py`, passed as keyword arguments on every declaration.** Hatchet's `TaskDefaults` does not fit: it reaches only `hatchet.workflow` steps, never standalone tasks or failure handlers, and its fallback treats a value equal to Hatchet's own default as unset, so a step cannot override back to 0 retries. Plain kwargs work the same on every decorator, and an override is just a different value. The values are `RETRIES = 3` and `EXECUTION_TIMEOUT = 10 minutes`, on the premise that a corvo task is idempotent. A task that is not raises `NonRetryableException` or declares `retries=0`, as Hatchet's retry docs prescribe. (session-settled: user-approved — chosen over one retries and timeout pair for every declaration: retrying a non-durable parent duplicates its child run.) Governs R6.
- KTD2. **A non-durable step that waits on a child run declares `retries=0` and `WAITING_EXECUTION_TIMEOUT`, and a durable task keeps `RETRIES`.** A non-durable step has no checkpoint, so its retry spawns a second child while the first may still run. A durable task's retry replays from its checkpoints and spawns nothing twice. `WAITING_EXECUTION_TIMEOUT` lives in `defaults.py` and covers one child declared with the defaults: each of its `RETRIES + 1` attempts may queue up to Hatchet's 5-minute scheduling timeout, which the engine sets again on every retry, then run for `EXECUTION_TIMEOUT`, so 4 × 15 minutes plus a margin for the engine noticing each timeout, 65 minutes in all. (session-settled: user-approved — chosen over the same defaults on parents and children: a parent's clock would run out before a retried child finishes.) Governs R6, R8.
- KTD10. **Each example's header comment carries the rules a copier needs.** Every example states the thin-shell rule and the top-level declaration rule. Every example also says not to put by-name stubs in the two areas, since a stub is a `BaseWorkflow` the registration test would flag. The durable example adds the determinism rule from Hatchet's durable-tasks doc, the approval-key rule (KTD6) and the child-failure rule (KTD8). `defaults.py` states KTD1 and KTD2 in prose. Governs R3, R6.

### Sources

- Retry policies: https://docs.hatchet.run/v1/retry-policies.md. Retries only for idempotent tasks; `NonRetryableException` skips them.
- Timeouts: https://docs.hatchet.run/v1/timeouts.md. Execution timeout defaults to 60 s, scheduling timeout to 5 min.
- hatchet-sdk 1.42.1 source: `TaskDefaults` fallback at `runnables/workflow.py:96-146`; standalone decorators build their workflow without `task_defaults` at `hatchet.py:611-626` and `hatchet.py:1107-1122`; `on_failure_task` ignores `task_defaults` at `runnables/workflow.py:1866-1886`.

## Implementation Units

### U2. Operation defaults

- **Goal:** one module holds corvo's retries and timeout defaults, and `hello` uses them.
- **Requirements:** R3, R6; KTD1, KTD2, KTD10.
- **Dependencies:** U1.
- **Files:**
  - Create `src/corvo/worker/defaults.py`.
  - Modify `src/corvo/worker/tasks/hello.py`.
  - Modify `tests/worker/tasks/test_hello.py`.
- **Approach:**
  1. `defaults.py` defines `RETRIES`, `EXECUTION_TIMEOUT` and `WAITING_EXECUTION_TIMEOUT` as `timedelta` values (KTD1, KTD2), with prose comments stating when to override and citing Hatchet's retry and timeout docs.
  2. `hello` passes `retries=RETRIES` and `execution_timeout=EXECUTION_TIMEOUT`.
  3. `hello.py` gets the header comment (KTD10): logic belongs in the core, the task is a thin shell, declare at module top level, no stubs in this area.
- **Patterns to follow:** `src/corvo/settings.py` for module-level comment density; Hatchet's `examples/timeout/worker.py` for explicit `timedelta` timeouts.
- **Test scenarios:**
  - `hello`'s single task carries `retries == RETRIES` and `execution_timeout == EXECUTION_TIMEOUT`, read through the public `BaseWorkflow.tasks`.
  - `WAITING_EXECUTION_TIMEOUT` equals `EXECUTION_TIMEOUT × (RETRIES + 1)` plus five minutes, so a change to either default keeps parents covering their children.
- **Verification:** `hello` declares no literal retries or timeout values; the defaults module is the only place the numbers appear.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict, lockfile.
- `uv run pytest tests/core tests/worker`: unit tests, no Docker.
- `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `coverage report --fail-under=90` the same way: CI's coverage floor.

## Definition of Done

- Every gate above passes locally and in CI.
- U2 when `hello` reads its values from `defaults.py`.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/worker-tasks-workflows-plan` → `feat/worker-u1-hello-core` → `feat/worker-u2-defaults` → `feat/worker-u3-registration` → `feat/worker-u4-greeting-dag` → `feat/worker-u5-greeting-rounds`.
- **This part:** branch `feat/worker-u2-defaults`, on top of `feat/worker-u1-hello-core`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
