---
title: Worker Skeleton U3 Registration List and Test - Plan
type: feat
date: 2026-10-14
topic: worker-tasks-workflows-skeleton-u3-registration
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md
execution: code
---

# Worker Skeleton U3 Registration List and Test - Plan

## Goal Capsule

- **Objective:** A definition left off the worker, listed twice, or sharing a name fails the test suite with its name in the message.
- **Parent:** `docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md` holds the whole plan; this is part 3 of 5. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** U1. **Blocks:** U4 builds on this part directly; U5 through U4.
- **Stop conditions:** stop and ask when the SDK behaves differently from this plan on hatchet-sdk 1.42.1 and engine v0.110.5, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U1: `hello` in `src/corvo/worker/tasks/`, the area the registration test walks; test folders are packages.

## Product Contract

### Summary

Makes the worker's list a public module constant, `WORKFLOWS`, and adds `tests/worker/test_registration.py`, which checks it against every definition in the `tasks` and `workflows` areas.

### Context

Hatchet starts a worker without complaint when a definition is missing from its list, and lets a duplicate name win silently. This guard makes both fail in the test suite before the examples multiply.

### Key Decisions

- **Explicit registration, guarded by a test.** (session-settled: user-approved — chosen over automatic discovery and over thin corvo decorators: no magic, one line per definition, the same pattern as Hatchet's own examples.) Governs R4.

### Requirements

**Registration**

- R4. The worker registers its tasks and workflows by explicit list, and a test fails, naming the definition, when a task or workflow in the `tasks` or `workflows` areas is registered on no worker or shares its name with another.
- R5. corvo runs one worker, `corvo-worker`, which registers every task and workflow.

### Acceptance Examples

- AE1. **Covers R4.** **Given** a new task file in the `tasks` area, **when** its line is missing from the worker's list, **then** the registration test fails and names that task.
- AE2. **Covers R4.** **Given** two definitions declared with the same `name`, **when** the tests run, **then** the registration test fails and names both.

### Scope Boundaries

- `greeting` and `greeting-rounds` join `WORKFLOWS` in U4 and U5; this part registers only `hello`.

## Planning Contract

### Key Technical Decisions

- KTD3. **`worker.py` exposes the list as a module constant `WORKFLOWS`, and `tests/worker/test_registration.py` checks it against what the two areas define.** Hatchet's `Worker` keeps its list private and fills its registry only at `start()`, so a public constant is the only engine-free view. The test walks `corvo.worker.tasks` and `corvo.worker.workflows` with `pkgutil`, collects module-level `BaseWorkflow` objects deduplicated by identity, and fails, naming each culprit, when:
  1. a defined object is missing from `WORKFLOWS`;
  2. one object appears twice in `WORKFLOWS`;
  3. two objects share a name, compared lowercased as Hatchet's `service_name` does;
  4. a directory in the areas holding Python files has no `__init__.py`, which `pkgutil` would skip silently;
  5. a module in the areas fails to import, instead of being swallowed by `walk_packages`.

  The checks run as a pure function inside the test module, which its own tests feed with definitions declared in the test. Hatchet itself lets a duplicate name win silently, which is why the test exists. (session-settled: user-approved — chosen over checking only the two cases R4 names: the extra cases are cheap, and each one would hide a definition the worker never registers.) Governs R4, R5.

### Deferred to Implementation

- The mypy-clean annotation for `WORKFLOWS`, importing `BaseWorkflow` from `hatchet_sdk.runnables.workflow` as `hatchet.worker` does, since `hatchet_sdk` does not export it.

### Sources

- hatchet-sdk 1.42.1 source: the worker keeps its list private at `worker/worker.py:150`; `Standalone` subclasses `BaseWorkflow` at `runnables/workflow.py:2040`; `service_name` lowercases names at `runnables/workflow.py:183-187`.
- Hatchet example `sdks/python/examples/worker.py` (explicit registration list).
- Current repo: `src/corvo/worker/worker.py`, `tests/worker/test_worker.py`.

## Implementation Units

### U3. Public registration list and registration test

- **Goal:** a definition left off the worker, listed twice, or sharing a name fails the test suite with its name in the message.
- **Requirements:** R4, R5, AE1, AE2; KTD3.
- **Dependencies:** U1.
- **Files:**
  - Modify `src/corvo/worker/worker.py`.
  - Create `tests/worker/test_registration.py`.
  - Modify `tests/worker/test_worker.py` (its comment says the worker's list is private; point it at the registration test instead).
- **Approach:**
  1. `worker.py` defines `WORKFLOWS` holding `hello`, and `create_worker()` passes it to `hatchet.worker("corvo-worker", workflows=WORKFLOWS)`.
  2. The test module holds a pure checker taking the discovered definitions (object plus `module.attribute` label) and the registered list, and returning one message per problem (KTD3, cases 1 to 3).
  3. A discovery helper walks the two areas, re-raises import errors and checks every directory for `__init__.py` (KTD3, cases 4 and 5).
  4. One test runs the checker against the real areas and `WORKFLOWS` and asserts no problems; the others feed it definitions declared in the test module.
- **Patterns to follow:** test names as sentences and arrange/act/assert spacing, as in `tests/worker/test_worker.py`.
- **Test scenarios:**
  - The real areas and `WORKFLOWS` produce no problems.
  - Covers AE1. A definition missing from the registered list yields a message naming its `module.attribute` and Hatchet name.
  - Covers AE2. Two definitions declared as `dup` yield a message naming both.
  - Two definitions named `Dup` and `dup` count as a duplicate.
  - The same object listed twice yields a message naming it.
  - A definition imported into a second module (a workflow importing `hello`) is counted once, not as a duplicate.
  - A DAG step (`Task`) inside a workflow is not treated as a definition of its own.
  - A directory in the areas with Python files and no `__init__.py` fails with its path.
- **Verification:** removing `hello` from `WORKFLOWS` makes the real-areas test fail with `hello` in the message; restoring it passes.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict, lockfile.
- `uv run pytest tests/core tests/worker`: unit tests, no Docker.
- `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `coverage report --fail-under=90` the same way: CI's coverage floor.

## Definition of Done

- Every gate above passes locally and in CI.
- U3 when removing a line from `WORKFLOWS` fails the suite by name.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/worker-tasks-workflows-plan` → `feat/worker-u1-hello-core` → `feat/worker-u2-defaults` → `feat/worker-u3-registration` → `feat/worker-u4-greeting-dag` → `feat/worker-u5-greeting-rounds`.
- **This part:** branch `feat/worker-u3-registration`, on top of `feat/worker-u2-defaults`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
- U3 needs only U1; it sits above U2 because a stack is linear.
