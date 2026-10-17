# Writing tasks and workflows

corvo-worker's tasks live in `corvo.worker.tasks` and its workflows in `corvo.worker.workflows`. The listeners in `corvo.vendors.hatchet.integrations` follow the same rules, except that a listener's logic need not sit at the mirrored path: the GitHub listener's is in `corvo.core.event_gateway`. This document holds the rules for writing one. Agent tasks run on the agent worker, and [Running agents](agents.md) and the agents' own modules cover them.

## Where the code goes

- The logic lives in `corvo.core`, at the mirrored path, and never imports Hatchet. A task, or a workflow's step, is a thin shell: it adapts Hatchet's input and output to the core, and spawns, waits and reads runs. It holds no logic of its own.
- Declare each task, workflow and step at module top level, passing the defaults from `corvo.vendors.hatchet.defaults`. Add each one to the main profile's list in `corvo.worker.profiles.main`: `tests/unit/corvo/worker/test_registration.py` fails, naming the definition, when one is missing.
- Keep Hatchet's by-name stubs out of these areas. A stub is a workflow too, and every workflow in them is one the worker must serve. The stubs of agent tasks live in `corvo.worker.agent_calls`.

## A standalone task

A task passes `RETRIES` and `EXECUTION_TIMEOUT`. A task that is not idempotent raises `NonRetryableException`, or declares `retries=0`.

## A DAG workflow

- Every node of a DAG receives the workflow's input. A DAG reuses a task by spawning it as a child run from one of its own steps.
- A step reads its parent step's output with `ctx.task_output(parent)`.
- The failure handler, declared with `on_failure_task`, runs once when any step has failed. Hatchet appends `-on-failure` to the name it declares. A step that raises `NonRetryableException` is not retried, so the handler runs at once.
- A step that waits on a child run declares `retries=0` and `WAITING_EXECUTION_TIMEOUT`, and every other step passes the defaults. The reasons are in `corvo.vendors.hatchet.defaults`.
- While it waits, the step holds a worker slot its child cannot use. When every slot holds a waiting step, the children never start and fail on Hatchet's scheduling timeout. A step that spawns many children, or waits long, belongs in a durable task, which Hatchet can evict to free its slot while it waits. https://docs.hatchet.run/v1/durable-tasks.md

## A step that spawns an agent

- The main profile reaches an agent only through its stub in `corvo.worker.agent_calls`, never by importing the agent task, which runs on the agent worker alone (KTD26). Declare the stub there, never in `corvo.worker.workflows`, and spawn the agent with the stub's `aio_run`.
- The step declares `retries=0` and `AGENT_WAITING_EXECUTION_TIMEOUT`. A retry would spawn, and pay for, the agent's session again, and the agent's one attempt may queue for its schedule timeout before it runs for its execution timeout. The reasons are in `corvo.worker.defaults`. A step that times out does not cancel its child, whose own execution timeout ends it.
- While it waits, the step holds a slot on the main worker, and none on the agent worker, where its child runs. A waiting step therefore never keeps its child from starting, but a main worker whose slots are full of waiting steps keeps its other tasks queued for as long as the agents take.
- An agent that works in a directory takes a name below `<root>/workdirs`, which the workflow's caller creates before it triggers the workflow and deletes after the run. [Working directories](agents.md#working-directories) has the rules.

## A durable workflow

A durable task composes by spawning: it spawns tasks and workflows, and waits for events or a timeout. Each spawn and each wait is a checkpoint. On a retry or after an eviction, Hatchet replays the task from its event log instead of running those steps again. https://docs.hatchet.run/v1/durable-tasks.md

The code between checkpoints must be deterministic, so that a replay takes every branch the first run took:

- Only spawn children, call the durable context, or call pure functions from `corvo.core`. Push side effects such as database or API calls into a child.
- Decide only on checkpoint outputs and the input, never on wall-clock time, random values or anything read from outside. `ctx.aio_now()` is the clock that replays.
- Changing the order of spawns and waits, or a loop's bound, while runs are in flight fails those runs on replay.

A failed child raises `TaskRunError`, which fails the durable task's run unless it handles the error. A durable task keeps the default `RETRIES`, since its retry spawns nothing twice. Its waits count toward its execution timeout, so the timeout covers the longest wait. Keep a wait below the 15-minute TTL after which Hatchet evicts a waiting task.

A wait for an event, a `UserEventCondition`, matches its event by a key the run's input carries:

- Each request needs a key of its own. With a reused key, an older event within the lookback matches the new run.
- A key that is written into the wait's CEL expression is restricted to characters that cannot break it, such as lowercase letters, digits and hyphens.
- `consider_events_since` lets an event pushed shortly before the wait still count. Take that time from `ctx.aio_now()` before any spawn, so an event pushed while the children ran still counts, however long they took.
- An event pushed after the wait's timeout matches nothing and is lost.

## Tests

- A unit test runs a task or a step with `aio_mock_run`, passing a step's parents' outputs as `parent_outputs`. It replaces each child's `aio_run`, or the agent stub's, with `monkeypatch`, since the real one would spawn a run on Hatchet.
- An integration test triggers the task or workflow by name through a stub, as another service would, on the real Hatchet that `tests/integration` starts.
