---
title: An event-triggered Hatchet task reads its event from the context, validates in its body, and is tested past the mock run
date: 2026-10-16
category: best-practices
module: worker event gateway on Hatchet
problem_type: best_practice
component: background_job
severity: medium
applies_when:
  - A Hatchet workflow or task starts from on_events, as in corvo.worker.event_gateway
  - A task's input comes from outside corvo and can be malformed
  - A task republishes or pushes Hatchet events of its own
  - A unit test needs a task to see a triggering event's key or id
  - An integration test must prove that an event started no run
retire_when: "hatchet-sdk lets aio_mock_run set the triggering event key and id, or stops retrying a failed input_validator; check hatchet_sdk/runnables/task.py's _create_mock_context and hatchet_sdk/runnables/workflow.py's _get_workflow_input at the version uv.lock pins"
tags: [hatchet, events, on-events, triggers, non-retryable, mock-run, log-level, integration-tests]
---

# An event-triggered Hatchet task reads its event from the context, validates in its body, and is tested past the mock run

## Context

The external event parser (`src/corvo/worker/event_gateway/workflows/external_event_parser.py`) is corvo's first task started by a Hatchet event rather than by a run. Its plan (`docs/plans/2026-10-16-1323-feat-external-event-parser-plan.md`, Sources / Research and KTD2 to KTD10) needed seven facts about hatchet-sdk 1.42.1 and engine v0.110.5. Hatchet's docs do not state them; they came from the SDK and engine source. Missing most of them gives a task or a test that looks right and misbehaves. The parser's module docstring records the ones that shaped that task. The next event-triggered task, such as a consumer of `corvo:external_event:*`, needs all of them again.

Paths under `hatchet_sdk/` below are in the installed hatchet-sdk 1.42.1, the version `uv.lock` pins. Paths under `pkg/` are in the engine's upstream repository.

## Guidance

1. **A `prefix:*` trigger matches from the start of the key.** The engine turns each `*` into a SQL `LIKE` wildcard: `k.event_key LIKE REPLACE(eventRef."eventKey", '*', '%')`. This is in `pkg/repository/sqlcv1/triggers.sql` of hatchet-dev/hatchet at v0.110.5, read upstream while planning. So `github:*` never matches `corvo:external_event:github:issue:opened`, and a task that republishes under `corvo:` cannot loop back into itself. Triggers are registered when the worker starts, so a new prefix needs a restart.

2. **Read the event from the context, and guard both values with `not`.** The key is `ctx.triggering_event_key` and the event's Hatchet id is `ctx.triggering_event_id` (`hatchet_sdk/context/context.py:718-724`). Both are typed `str | None`. A run that no event started, such as a manual trigger from the dashboard, arrives without them. The SDK defaults both to `None` (`hatchet_sdk/runnables/action.py:110-111`), and the plan's KTD5 expects `""` from the engine as well. The parser's core function rejects both with `ValueError` (`src/corvo/core/event_gateway/external_event_parser.py`).

3. **Take `EmptyModel`, validate inside the body, and turn only that validation into `NonRetryableException`.**
   - A typed input does not avoid retries. Hatchet validates it inside the task call (`_get_workflow_input`, `hatchet_sdk/runnables/workflow.py:285-291`), and the runner retries every exception that is not a `NonRetryableException` (`hatchet_sdk/worker/runner/runner.py:316-331`). So a strict `input_validator` that rejects a bad event is retried `RETRIES` times, failing the same way each time.
   - The parser therefore takes `EmptyModel` and builds its event from `input.model_dump()`. Only that build sits in a `try` that converts `ValueError` to `NonRetryableException`. Pydantic's `ValidationError` is a `ValueError`, so it is converted too.
   - The publish, `hatchet.event.aio_push`, sits outside that `try`, so its failures keep the default retries. This matters because an encoding error from `aio_push` is also a `ValueError`. Put it inside the `try` and a refused publish would never be retried.

   ```python
   try:
       event = parse(key, external_id, payload)
   except ValueError as e:
       # Pydantic's ValidationError is a ValueError too.
       logger.error("%s, Hatchet id %s, is no corvo event: %s", key, external_id, e)
       raise NonRetryableException(f"{key!r} is no corvo event") from e
   try:
       published = await hatchet.event.aio_push(event.name, event.model_dump(mode="json"))
   except Exception:
       logger.exception(...)
       raise
   ```

4. **Give an event task more than Hatchet's 5-minute schedule timeout.** `schedule_timeout` defaults to `timedelta(minutes=5)` (`hatchet_sdk/hatchet.py:460`). Any event that arrives while no worker is up longer than that is dropped, and corvo logs nothing. Event tasks use `EVENT_SCHEDULE_TIMEOUT`, which is 24 hours (`src/corvo/worker/defaults.py:35`).

5. **In unit tests, replace the context's properties and the publish, and pass the payload as a model.**
   - `aio_mock_run` cannot set the triggering event. Its `_create_mock_context` builds the `Action` without `triggering_event_key` or `triggering_event_external_id` (`hatchet_sdk/runnables/task.py:605-625`), and both default to `None` (`hatchet_sdk/runnables/action.py:110-111`).
   - It also serializes only a dataclass or a `BaseModel` input (`task.py:596-601`), so a plain `dict` reaches the task as `{}`. That fails silently: a test passing a dict sees an empty payload.
   - The parser's tests use two fixtures. `triggered_by` monkeypatches `Context.triggering_event_key` and `Context.triggering_event_id` with properties. `push` replaces `hatchet.event.aio_push` on the shared client and records each push. They pass the payload as `EmptyModel(**payload)` (`tests/unit/corvo/worker/event_gateway/workflows/test_external_event_parser.py:49-83`).
   - `aio_push` returns a protobuf `Event`, which mypy could not type in this session, since it found no stubs for it. A frozen dataclass holding only `event_id` stands in for it.

6. **To see a task's debug lines, set the root logger's level before the worker starts.**
   - Hatchet forwards Python log records from inside a task to the run's log. The forwarder is a handler on the root logger (the config's `logger: Logger = getLogger()`, `hatchet_sdk/config.py:249`).
   - The handler is created once, when the worker's action runner starts (`hatchet_sdk/worker/runner/run_loop_manager.py:73-80`). It copies the root logger's level at that moment (`hatchet_sdk/worker/runner/utils/capture_logs.py:200-202`).
   - `logging.basicConfig(level=...)` would not help, since it does nothing once the root logger has a handler, and under pytest it already has one.
   - `worker.main()` keeps `basicConfig()` for stdout and then sets `CORVO_LOG_LEVEL` on the root logger itself, before `start` (`src/corvo/worker/worker.py:40-45`). `test_main_sets_the_root_level_before_the_worker_starts` (`tests/unit/corvo/worker/test_worker.py:73`) patches `Worker.start` to record the root level at that moment.
   - Use `logging.getLogger(__name__)` rather than `ctx.log`, because `ctx.log` sends every line as INFO.

7. **In integration tests, find runs by the push id. To prove that nothing ran, push a barrier event and check your lookup first.**
   - `hatchet.runs.aio_list(triggering_event_external_id=pushed.event_id)` lists the runs an event started.
   - `hatchet.event.aio_list(keys=[key])` lists the events published under a key.
   - An absence check, such as "the republished event started no run", needs two things before it asserts an empty list:
     - A later event of a listed prefix whose run has finished. Once it has, the engine has handled the events pushed before it.
     - Proof that a listed event's `metadata.id` is the id runs are filtered by.

   Without that proof, the check on a republished event, whose id comes from the event list and not from a push, can pass whatever the engine did. `test_only_a_listed_prefix_starts_the_parser` (`tests/integration/corvo/worker/test_event_gateway.py:91-111`) does both.

## Why This Matters

Each point stands for a failure that is easy to miss:

- **Strict `input_validator` (point 3).** A malformed GitHub event burns every retry and fills the run log with the same error.
- **`aio_push` inside the `try` (point 3).** A refused publish is never retried.
- **Default schedule timeout (point 4).** Every event that arrives during a worker outage longer than 5 minutes is lost.
- **Plain `dict` in the mock run (point 5).** The test sees an empty payload.
- **No property patch (point 5).** Every unit test sees a `None` key, so all of them exercise the "no event" branch.
- **`basicConfig(level=...)` (point 6).** `CORVO_LOG_LEVEL=DEBUG` changes stdout in some setups and never reaches the run log.
- **Absence check without the barrier and id check (point 7).** The test cannot fail.

## When to Apply

- When adding a workflow or task with `on_events`, in `corvo.worker.event_gateway` or elsewhere.
- When adding a prefix to `EXTERNAL_PREFIXES`. That also needs the worker restarted.
- When a task's input comes from a system outside corvo.
- When writing a test that must show that an event did not trigger something.

## Examples

- **The parser task.** `parse_external_event` (`src/corvo/worker/event_gateway/workflows/external_event_parser.py`) applies points 1 to 4 and 6. Its module docstring states why the task keeps `RETRIES` although it is not idempotent: a retry after a successful publish publishes a second corvo event. That is the accepted cost of retrying a refused publish.
- **Its unit tests.** Each protection was removed in turn while the tests ran:
  - turning a failed publish into `NonRetryableException` breaks 2 unit tests;
  - letting an invalid event be retried makes the integration test see 3 retries instead of 0.

## Related

- [Hatchet's retries=0 does not make a task run at most once](hatchet-retries-zero-is-not-at-most-once.md): the other way Hatchet re-runs a task without being asked. Point 3 here is its counterpart for input that will never become valid.
- [A negative test must fail when the protection it proves is removed](negative-tests-must-fail-without-their-protection.md): point 7 applies its "assert the evidence exists first" rule to Hatchet's event and run lists.
- `docs/plans/2026-10-16-1323-feat-external-event-parser-plan.md`: Sources / Research lists the SDK and engine lines above; KTD4, KTD8, KTD9 and KTD10 apply them.
