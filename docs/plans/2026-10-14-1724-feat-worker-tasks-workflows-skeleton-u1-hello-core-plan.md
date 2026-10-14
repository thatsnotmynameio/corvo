---
title: Worker Skeleton U1 Hello Over Core - Plan
type: feat
date: 2026-10-14
topic: worker-tasks-workflows-skeleton-u1-hello-core
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md
execution: code
---

# Worker Skeleton U1 Hello Over Core - Plan

## Goal Capsule

- **Objective:** `hello` runs from `src/corvo/worker/tasks/` as a thin shell over a pure function in `src/corvo/core/tasks/`, with its Hatchet name and contract unchanged.
- **Parent:** `docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md` holds the whole plan; this is part 1 of 5. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** nothing; starts from `main`. **Blocks:** U2 and U3 build on this part directly; U4 and U5 through them.
- **Stop conditions:** stop and ask when the SDK behaves differently from this plan on hatchet-sdk 1.42.1 and engine v0.110.5, or when CI's 90% coverage floor cannot be held without excluding code.

## Product Contract

### Summary

Creates the `tasks` area on both sides of the hexagonal split and moves `hello` into it: the worker module adapts Hatchet's input and output, the core module builds the greeting. The test folders become packages so mirrored test names coexist.

### Context

This is the first layer: every later example copies the shell-over-core shape it sets. R12 is completed only by U5, after every example has its core twin; this part builds it for `hello`. R3's header comment on `hello` lands in U2.

### Key Decisions

- **Use Hatchet directly, with no corvo layer hiding it.** Tasks and workflows are declared with Hatchet's own API and live inside `corvo.worker`, so the ruff rule that only `corvo.worker` imports `hatchet_sdk` stays as it is. (session-settled: user-directed — chosen over a corvo layer of abstract base classes that hid Hatchet entirely: that layer had to rebuild DAGs, durable waits, a test executor and not-implemented interfaces Hatchet already provides, and grew too large.) Governs R1, R2.
- **Protect against engine lock-in through the hexagonal split, not a wrapper.** Business logic lives in corvo's core, which never imports Hatchet, and tasks stay thin shells that call it. Changing engines would mean rewriting the shells. The examples demonstrate it: each worker module has a core twin at the mirrored path. (session-settled: user-directed — chosen over examples that keep their logic inside the task and state the rule only as a comment: contributors copy the code, not the comment.) Governs R3, R12.
- **Tasks are reusable building blocks; workflows compose them.** (session-settled: user-directed — chosen over each workflow owning its steps, with a tasks area only for tasks that run alone.) Governs R1, R8, R9.

### Requirements

**Layout and conventions**

- R1. `corvo.worker` holds a `tasks` area for reusable standalone tasks, a `workflows` area for DAG and durable workflows, the shared Hatchet client and the worker entry point.
- R12. Each example's logic lives in a pure function under `corvo.core`, at the path that mirrors its worker module (`corvo.core.tasks` for tasks, `corvo.core.workflows` for workflow steps and decisions); the worker module only adapts Hatchet's input and output to it and orchestrates child runs and waits.

**Living examples**

- R7. `hello` moves into the `tasks` area and keeps its Hatchet name `hello` and its input and output contract.

### Acceptance Examples

- AE5. **Covers R7, R11.** **Given** `hello` in its new place, **when** a client triggers it by the name `hello` with the existing input model, **then** it returns the same output as before the move.

### Scope Boundaries

- The defaults on `hello`'s decorator and its header comment are U2's. The public `WORKFLOWS` list is U3's.

## Planning Contract

### Key Technical Decisions

- KTD11. **`src/corvo/core/` mirrors the worker's areas with pure functions over plain values.**
  - `core/tasks/hello.py` builds the greeting.
  - `core/workflows/greeting.py` shouts a message.
  - `core/workflows/greeting_rounds.py` decides whether another round is needed, from the message, `target_length`, the rounds so far and `max_rounds`.

  The core takes and returns `str`, `int` and `bool`. The Pydantic input and output models stay in the worker, because they are Hatchet's contract. Spawning children, waiting and reading Hatchet's result shapes are orchestration and stay in the worker. The durable example calls only pure core functions between checkpoints, which keeps replay deterministic. Nothing new enforces the boundary: ruff's banned-api rule already stops anything outside `corvo.worker`, `core` included, from importing `hatchet_sdk` or `corvo.worker`. Core tests live in `tests/core/` and call the functions directly, with no mock run. `tests/worker/` and `tests/core/` become packages with `__init__.py`, as `tests/integration/` already is, so mirrored test names such as `test_hello.py` do not collide in pytest or mypy. (session-settled: user-directed — chosen over examples holding their logic inside the task, with the rule stated only in a comment: logic in `core/tasks/` and `core/workflows/`, thin shells in `worker/tasks/` and `worker/workflows/`.) Governs R3, R12.

### Assumptions

- The unsigned-token shim in `tests/conftest.py` keeps working for every new module that declares tasks, since each one imports the client built at import time.

### Sources

- Current repo: `src/corvo/worker/worker.py`, `src/corvo/worker/workflows/hello.py`, `ruff.toml:15-23`, `tests/conftest.py`, `tests/integration/__init__.py`, `tests/integration/worker/test_workflows.py`.

## Implementation Units

### U1. Move hello into the tasks area, over a core function

- **Goal:** `hello` lives in `src/corvo/worker/tasks/` as a thin shell over `src/corvo/core/tasks/hello.py`, with its Hatchet name and contract unchanged.
- **Requirements:** R1, R7, R12, AE5; KTD11.
- **Dependencies:** none.
- **Files:**
  - Create `src/corvo/core/__init__.py` and `src/corvo/core/tasks/__init__.py` (empty, as every `src` package has).
  - Create `src/corvo/core/tasks/hello.py`.
  - Create `src/corvo/worker/tasks/__init__.py`.
  - Move `src/corvo/worker/workflows/hello.py` to `src/corvo/worker/tasks/hello.py`.
  - Modify `src/corvo/worker/worker.py` (import path).
  - Create `tests/core/__init__.py`, `tests/core/tasks/__init__.py` and `tests/core/tasks/test_hello.py`.
  - Create `tests/worker/__init__.py`, `tests/worker/tasks/__init__.py` and `tests/worker/workflows/__init__.py`.
  - Move `tests/worker/workflows/test_hello.py` to `tests/worker/tasks/test_hello.py`.
  - Modify `tests/integration/worker/test_workflows.py` (import path).
- **Approach:**
  1. Add the core function that builds the greeting from a name, over plain `str` (KTD11).
  2. Move the worker module and its test, keeping `name="hello"`, `HelloInput` and `HelloOutput` as they are. The task body becomes: call the core function with the input's name and wrap the result in `HelloOutput`.
  3. Turn `tests/worker/` and `tests/core/` into packages, so `tests/core/tasks/test_hello.py` and `tests/worker/tasks/test_hello.py` coexist (KTD11).
  4. Update the three imports the research found (`worker.py`, the moved unit test, the integration test).
  5. Keep `src/corvo/worker/workflows/__init__.py`; the workflows area gets its examples in U4 and U5.
  6. Leave `ruff.toml` alone: its banned-api rule already keeps `corvo.core` and `tests/core` from importing Hatchet or the worker, and CI reads it from the base commit.
- **Patterns to follow:** the current `src/corvo/worker/workflows/hello.py` and its test; `tests/integration/__init__.py` for test packages.
- **Test scenarios:**
  - The core function given `corvo` returns `Hello, corvo!`, called directly with no Hatchet import.
  - Covers AE5. `hello.aio_mock_run(HelloInput(name="corvo"))` returns `HelloOutput(message="Hello, corvo!")` from the new path.
  - Covers AE5. The existing integration test triggers `hello` by name through `hatchet.stubs.task` and gets the same output.
- **Verification:**
  - No module imports `corvo.worker.workflows.hello`.
  - The worker's `hello` body holds no string building of its own.
  - pytest and mypy collect both `test_hello.py` files.
  - The unit and integration hello tests pass unchanged apart from the import.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict, lockfile.
- `uv run pytest tests/core tests/worker`: unit tests, no Docker.
- `uv run pytest tests/integration/worker`: integration on compose (needs Docker).
- `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `coverage report --fail-under=90` the same way: CI's coverage floor.

## Definition of Done

- Every gate above passes locally and in CI.
- U1 when nothing imports the old path, the worker's `hello` holds no string building of its own, and pytest and mypy collect both `test_hello.py` files.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/worker-tasks-workflows-plan` → `feat/worker-u1-hello-core` → `feat/worker-u2-defaults` → `feat/worker-u3-registration` → `feat/worker-u4-greeting-dag` → `feat/worker-u5-greeting-rounds`.
- **This part:** branch `feat/worker-u1-hello-core`, on top of `docs/worker-tasks-workflows-plan`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
