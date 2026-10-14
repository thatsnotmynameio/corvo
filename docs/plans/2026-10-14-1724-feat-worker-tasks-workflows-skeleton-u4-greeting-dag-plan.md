---
title: Worker Skeleton U4 Greeting DAG Example - Plan
type: feat
date: 2026-10-14
topic: worker-tasks-workflows-skeleton-u4-greeting-dag
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md
execution: code
---

# Worker Skeleton U4 Greeting DAG Example - Plan

## Goal Capsule

- **Objective:** A contributor can copy a DAG whose steps spawn reusable tasks, read a parent's output and hand failures to a handler that spawns a task, with the step logic in its core twin.
- **Parent:** `docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md` holds the whole plan; this is part 4 of 5. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** U2, U3. **Blocks:** U5 builds on this part.
- **Stop conditions:** stop and ask when the SDK behaves differently from this plan on hatchet-sdk 1.42.1 and engine v0.110.5, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U2: `RETRIES`, `EXECUTION_TIMEOUT` and `WAITING_EXECUTION_TIMEOUT` in `src/corvo/worker/defaults.py`; `hello` with its header comment.
- U3: the public `WORKFLOWS` list in `src/corvo/worker/worker.py` and the registration test that will check `greeting`.

## Product Contract

### Summary

Adds the DAG example `greeting`: `greet` spawns `hello`, `shout` reads `greet`'s output and shouts it through `src/corvo/core/workflows/greeting.py`, and a failure handler spawns `hello` when the DAG fails.

### Context

corvo's fixed sub-pipelines fit a DAG; without an example, every first use reinvents the shape. R2, R3, R10, R11 and R12 are completed only by U5, the last example; this part builds them for `greeting`. R8 is completed here.

### Key Decisions

- **Use Hatchet directly, with no corvo layer hiding it.** Tasks and workflows are declared with Hatchet's own API and live inside `corvo.worker`, so the ruff rule that only `corvo.worker` imports `hatchet_sdk` stays as it is. (session-settled: user-directed — chosen over a corvo layer of abstract base classes that hid Hatchet entirely: that layer had to rebuild DAGs, durable waits, a test executor and not-implemented interfaces Hatchet already provides, and grew too large.) Governs R1, R2.
- **Protect against engine lock-in through the hexagonal split, not a wrapper.** Business logic lives in corvo's core, which never imports Hatchet, and tasks stay thin shells that call it. Changing engines would mean rewriting the shells. The examples demonstrate it: each worker module has a core twin at the mirrored path. (session-settled: user-directed — chosen over examples that keep their logic inside the task and state the rule only as a comment: contributors copy the code, not the comment.) Governs R3, R12.
- **Tasks are reusable building blocks; workflows compose them.** (session-settled: user-directed — chosen over each workflow owning its steps, with a tasks area only for tasks that run alone.) Governs R1, R8, R9.
- **Both composition models from the start, each with an example, plus one example of mixing them.** (session-settled: user-directed — chosen over durable workflows now and DAGs added when the first fixed pipeline appears.) Governs R8, R9.
- **Every task and workflow declares its name explicitly.** A name derived from a class or module would change on a rename and break in-flight durable runs, registered triggers and by-name callers. (session-settled: user-directed — chosen over derived names guarded by a snapshot test.) Governs R2.
- **Tests use what Hatchet provides.** Every example body runs in-process under Hatchet's mock runs, with child runs and durable waits replaced in the test where they would need an engine, and workflow behavior is proven against the real Hatchet in compose. corvo builds no in-memory executor. (session-settled: user-approved — chosen over excluding the spawning and waiting bodies from coverage: CI's 90% coverage floor counts only in-process code.) Governs R10, R11.

### Requirements

**Layout and conventions**

- R2. Every task and workflow is declared with Hatchet's own API, with an explicit `name` and Pydantic input and output models.
- R3. The rule that business logic lives in the core and tasks stay thin shells is written at the top of each example file a contributor copies.
- R12. Each example's logic lives in a pure function under `corvo.core`, at the path that mirrors its worker module (`corvo.core.tasks` for tasks, `corvo.core.workflows` for workflow steps and decisions); the worker module only adapts Hatchet's input and output to it and orchestrates child runs and waits.

**Living examples**

- R8. A DAG example workflow uses reusable tasks from the `tasks` area by spawning them as child runs from its own steps: one step reads its parent step's output, and a failure handler triggers another task or workflow when the DAG fails.

**Tests**

- R10. Each example task, DAG step, failure handler and durable workflow has a unit test that runs without a Hatchet engine, with child runs and durable waits replaced in the test; R11 proves that the composition works.
- R11. The integration suite runs every example on the real Hatchet in compose, including both paths of the durable example's wait.

### Acceptance Examples

- AE3. **Covers R8, R11.** **Given** the DAG example with a node forced to fail, **when** it runs on Hatchet, **then** the failure handler runs and the task or workflow it triggers is observed running.

### Scope Boundaries

- The durable example that spawns `greeting` is U5's.

## Planning Contract

### Key Technical Decisions

- KTD2. **A non-durable step that waits on a child run declares `retries=0` and `WAITING_EXECUTION_TIMEOUT`, and a durable task keeps `RETRIES`.** A non-durable step has no checkpoint, so its retry spawns a second child while the first may still run. A durable task's retry replays from its checkpoints and spawns nothing twice. `WAITING_EXECUTION_TIMEOUT` lives in `defaults.py` and covers one child declared with the defaults: each of its `RETRIES + 1` attempts may queue up to Hatchet's 5-minute scheduling timeout, which the engine sets again on every retry, then run for `EXECUTION_TIMEOUT`, so 4 × 15 minutes plus a margin for the engine noticing each timeout, 65 minutes in all. (session-settled: user-approved — chosen over the same defaults on parents and children: a parent's clock would run out before a retried child finishes.) Governs R6, R8.
- KTD4. **Unit tests replace child runs and the durable wait with pytest's `monkeypatch`, and use Hatchet's `aio_mock_run` for everything else.** A child's `aio_run` is replaced on the corvo object (`hello`, `greeting`). The durable wait is replaced on `DurableContext.aio_wait_for`, because the mock run builds its context internally. The replacement returns Hatchet's wait-result shape (`{"CREATE": {<readable_data_key>: [payload]}}`), which the integration suite proves against the engine. Governs R10.
- KTD5. **The DAG example is `greeting`.** Its step `greet` spawns `hello` and returns its message. Its step `shout`, with parent `greet`, reads that output and shouts it through its core twin (KTD11), or raises `NonRetryableException` when the input's `force_failure` is true. Its failure handler spawns `hello` and returns that output without reading the failed task's error (engine v0.110.5 returns it empty). `NonRetryableException` keeps the forced failure from being retried, so the handler runs at once. Governs R8.
- KTD9. **Integration tests trigger every example by name through `hatchet.stubs`, as the existing hello test does.** Each await runs under `asyncio.timeout`, so a stuck run fails the test instead of the 20-minute CI job. The event-path test pushes the event with its scope before triggering, so the lookback is proven on purpose. Each durable test uses its own `approval_key`. The failure path polls the run's details with a deadline until the failure handler completes, as Hatchet's `on_failure/test_on_failure.py` does. Governs R11.
- KTD10. **Each example's header comment carries the rules a copier needs.** Every example states the thin-shell rule and the top-level declaration rule. Every example also says not to put by-name stubs in the two areas, since a stub is a `BaseWorkflow` the registration test would flag. The durable example adds the determinism rule from Hatchet's durable-tasks doc, the approval-key rule (KTD6) and the child-failure rule (KTD8). `defaults.py` states KTD1 and KTD2 in prose. Governs R3, R6.
- KTD11. **`src/corvo/core/` mirrors the worker's areas with pure functions over plain values.**
  - `core/tasks/hello.py` builds the greeting.
  - `core/workflows/greeting.py` shouts a message.
  - `core/workflows/greeting_rounds.py` decides whether another round is needed, from the message, `target_length`, the rounds so far and `max_rounds`.

  The core takes and returns `str`, `int` and `bool`. The Pydantic input and output models stay in the worker, because they are Hatchet's contract. Spawning children, waiting and reading Hatchet's result shapes are orchestration and stay in the worker. The durable example calls only pure core functions between checkpoints, which keeps replay deterministic. Nothing new enforces the boundary: ruff's banned-api rule already stops anything outside `corvo.worker`, `core` included, from importing `hatchet_sdk` or `corvo.worker`. Core tests live in `tests/core/` and call the functions directly, with no mock run. `tests/worker/` and `tests/core/` become packages with `__init__.py`, as `tests/integration/` already is, so mirrored test names such as `test_hello.py` do not collide in pytest or mypy. (session-settled: user-directed — chosen over examples holding their logic inside the task, with the rule stated only in a comment: logic in `core/tasks/` and `core/workflows/`, thin shells in `worker/tasks/` and `worker/workflows/`.) Governs R3, R12.

### Assumptions

- hatchet-sdk 1.42.1, as pinned in `uv.lock`, supports everything R8 and R9 need: `wf.task(parents=...)`, `wf.on_failure_task()`, `hatchet.durable_task()`, child spawning and event waits with an or-group timeout.
- The unsigned-token shim in `tests/conftest.py` keeps working for every new module that declares tasks, since each one imports the client built at import time.
- In hatchet-sdk 1.42.1 every DAG node receives the workflow's input, and `wf.add_task` attaches a standalone task only as a node with no parents. A workflow therefore reuses a task by spawning it as a child run from one of its own steps, which reads its parent step's output through the step's context.
- Hatchet's mock runs execute a task body without an engine, but a child spawn inside one makes a real gRPC call, and a durable wait raises `ValueError("Durable task client is not available")`. Unit tests replace both (KTD4); only integration (R11) proves the composition.

### Risks

- **The integration suite grows inside a 20-minute CI job.** The new tests are short (sub-10-second waits, children that return at once) and bounded by `asyncio.timeout` (KTD9).

### Deferred to Implementation

- How the failure-path test gets the run id it polls: `aio_run(wait_for_result=False)` on the stub, or the exception's run id.
- The exact `asyncio.timeout` values, sized to each test's inputs.

### Sources

- Child spawning: https://docs.hatchet.run/v1/child-spawning.md. Any task, durable or not, can spawn children.
- Durable tasks vs DAGs: https://docs.hatchet.run/cookbooks/durable-tasks-vs-dags.md.
- Hatchet examples in hatchet-dev/hatchet: `sdks/python/examples/dag/`, `on_failure/` (worker and test), `unit_testing/`.

## Implementation Units

### U4. DAG example: greeting

- **Goal:** a contributor can copy a DAG whose steps spawn reusable tasks, read a parent's output and hand failures to a handler that spawns a task.
- **Requirements:** R2, R3, R8, R10, R11, R12, AE3; KTD2, KTD4, KTD5, KTD9, KTD10, KTD11.
- **Dependencies:** U2, U3.
- **Files:**
  - Create `src/corvo/core/workflows/__init__.py` and `src/corvo/core/workflows/greeting.py`.
  - Create `src/corvo/worker/workflows/greeting.py`.
  - Modify `src/corvo/worker/worker.py` (add to `WORKFLOWS`).
  - Create `tests/core/workflows/__init__.py` and `tests/core/workflows/test_greeting.py`.
  - Create `tests/worker/workflows/test_greeting.py`.
  - Modify `tests/integration/worker/test_workflows.py`.
- **Approach:**
  1. Add the core function that shouts a message, over plain `str` (KTD11).
  2. Declare `hatchet.workflow(name="greeting", input_validator=GreetingInput)`, where `GreetingInput` holds `name` and `force_failure: bool = False`.
  3. `greet` spawns `hello` and returns `GreetOutput(message)`, declared with `retries=0` and `WAITING_EXECUTION_TIMEOUT` (KTD2).
  4. `shout` declares `parents=[greet]`, reads `ctx.task_output(greet)`, passes the message to the core function and returns `ShoutOutput(message)`, raising `NonRetryableException` when `force_failure` is set. It is declared with the defaults.
  5. The failure handler spawns `hello` with a fixed name and returns its output, declared like `greet` (KTD2, KTD5).
  6. Header comment per KTD10.
- **Patterns to follow:** Hatchet's `examples/dag/worker.py` and `examples/on_failure/worker.py`; `hello.py` and its core twin from U1 for model, naming and the shell-over-core split.
- **Test scenarios:**
  - The core function given `Hello, corvo!` returns `HELLO, CORVO!`.
  - `shout` mock-run with `parent_outputs={"greet": {"message": "Hello, corvo!"}}` returns `HELLO, CORVO!`.
  - `shout` mock-run with `force_failure=True` raises `NonRetryableException`.
  - `greet` mock-run with `hello.aio_run` replaced returns the replacement's message and passed the workflow's `name` to it.
  - The failure handler mock-run with `hello.aio_run` replaced returns the replacement's output.
  - Integration: `greeting` triggered by name with `name="corvo"` returns a `shout` output of `HELLO, CORVO!`.
  - Covers AE3. Integration: `greeting` with `force_failure=True` fails, and the run's details show `shout` failed and the failure handler completed with `hello`'s output, so the spawned child ran.
- **Verification:** both `greeting` integration tests pass on compose; the registration test passes with `greeting` in `WORKFLOWS`.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict, lockfile.
- `uv run pytest tests/core tests/worker`: unit tests, no Docker.
- `uv run pytest tests/integration/worker`: integration on compose (needs Docker).
- `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `coverage report --fail-under=90` the same way: CI's coverage floor.

## Definition of Done

- Every gate above passes locally and in CI.
- U4 when its integration tests pass on compose.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/worker-tasks-workflows-plan` → `feat/worker-u1-hello-core` → `feat/worker-u2-defaults` → `feat/worker-u3-registration` → `feat/worker-u4-greeting-dag` → `feat/worker-u5-greeting-rounds`.
- **This part:** branch `feat/worker-u4-greeting-dag`, on top of `feat/worker-u3-registration`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
