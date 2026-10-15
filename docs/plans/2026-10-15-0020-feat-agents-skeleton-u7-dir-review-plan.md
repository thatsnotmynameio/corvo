---
title: Agents Skeleton U7 Dir-Review Workflow - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u7-dir-review
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U7 Dir-Review Workflow - Plan

## Goal Capsule

- **Objective:** A contributor can copy a workflow whose steps spawn agents as child runs and combine their outputs, from the main worker.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 9 of 9 in stack order (unit U7). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U6; it sits on `feat/agents-u6-dir-summary` in the stack. **Blocks:** none; this is the stack's top.
- **Stop conditions:** stop and ask when a `hatchet.stubs.task` stub cannot share its task's input and output classes on hatchet-sdk 1.42.1.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U6's `agent_calls` and both agent tasks.
- U2's registration test, which this part extends with the stubs check.
- On `main`: `src/corvo/worker/workflows/greeting.py` and its tests.

## Product Contract

### Summary

Adds the `dir-review` DAG on the main profile, which spawns both agents through stubs and combines their outputs, its core twin, and the stubs' registration check.

### Context

`dir-review` is the third living example (R20). The main profile reaches agent tasks only through stubs, so the main worker never imports an agent (KTD2, KTD26).

### Key Decisions

- **An agent is a Hatchet task that runs one agent session.** Workflows spawn it like any task. (session-settled: user-directed — chosen over an agent outside Hatchet that calls tasks as tools: both will exist, starting with this one.) Governs R6, R20.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.
- **Hatchet does not retry agents.** A retry re-runs and re-pays the whole session, and the SDK already retries API errors itself. (session-settled: user-approved — chosen over corvo's `RETRIES` default, which assumes idempotent tasks.) Governs R7.
- **Three examples cover the four shapes.** Example 2 combines the working directory with a custom tool, as `greeting-rounds` combined spawning and waiting. (session-settled: user-approved — chosen over one example per shape.) Governs R18, R19, R20.

### Requirements

**Hatchet integration**

- R7. Agent tasks declare `retries=0`, an agent execution timeout and an agent schedule timeout sized for the queue behind R9's cap, all defined once in the worker's defaults. A step that waits on an agent child declares a timeout derived from the agent's schedule and execution timeouts, not `WAITING_EXECUTION_TIMEOUT`.

**Living examples**

- R20. A workflow spawns both agents as child runs and uses their outputs.
- R21. Each example file opens with a header comment that carries the rules a copier needs, as the task and workflow examples do.

**Tests**

- R24. The integration suite runs every example on the real Hatchet and real bubblewrap with the SDK's engine replaced, including the end of a run on timeout. It creates its working directories below `<root>/workdirs` (R5), not in pytest's temporary directories.
- R25. Each example is proven once against real Claude Haiku with a small prompt, through a documented manual command whose run is recorded in the pull request.

### Acceptance Examples

- AE7. **Covers R20, R24.** **Given** the workflow example on Hatchet and bubblewrap with the SDK's engine replaced, **when** it runs, **then** it returns outputs derived from both agents' structured outputs.

### Scope Boundaries

Not in this part:

- No agent that calls Hatchet tasks as tools (the plan's Scope Boundaries).

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- hatchet-sdk 1.42.1 cancels a running async task's asyncio task on cancellation and timeout (`hatchet_sdk/worker/runner/runner.py:920-944`). It sets the context's cancellation flag, sleeps one second, cancels the task, and frees the task's slot without waiting for its `finally`. Engine timeout and cancel reach the worker as the same `CANCEL_STEP_RUN` action. The SDK also has an unpinned `claude` extra and `mcp_tool` (`hatchet_sdk/runnables/workflow.py:831`), neither used here.
- Hatchet API tokens are scoped per tenant, with no per-worker or narrower token (Hatchet security docs). A task goes only to workers that registered it, and worker labels attract tasks without keeping others away (Hatchet worker and worker-affinity docs). In hatchet-sdk 1.42.1, `DesiredWorkerLabel.required` defaults to `False` (`hatchet_sdk/types/labels.py:69`), so isolation by registration is the only exclusion this plan relies on.

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD9. **The agent defaults stay in `src/corvo/worker/defaults.py`, with sandbox wording.**

  | Constant | Value | Why |
  |---|---|---|
  | `AGENT_EXECUTION_TIMEOUT` | 15 minutes | The longest example session plus the sandbox's start. |
  | `AGENT_DEADLINE_MARGIN` | 60 seconds | The session budget ends this long before Hatchet's timeout, which leaves time to report and clean up. |
  | `AGENT_SCHEDULE_TIMEOUT` | 60 minutes | Waiting behind the cap, or for an agent worker that can isolate (R28), counts against it. |
  | `AGENT_WAITING_EXECUTION_TIMEOUT` | 80 minutes | One attempt queued and run (`retries=0`), plus a 5-minute detection margin. |
  | `AGENT_CONCURRENCY` | `max_runs=2` | A `ConcurrencyExpression` named `corvo-agents`, constant key, `GROUP_ROUND_ROBIN`, `is_tenant_scoped=True`. |
  | `AGENT_MEMORY` | 2 GiB | Anthropic's 1 GiB floor, doubled for the engine and its tools; swap 0. |
  | `AGENT_CPUS` | 1 | Anthropic's starting point, written to `cpu.max` (renamed from `AGENT_NANO_CPUS`). |
  | `AGENT_PIDS_LIMIT` | 256 | Above the engine's threads. Measured in the Haiku proof. |
  | `AGENT_TMPFS_SIZE` | 512 MiB | Each of a session's `/tmp` and home; charged to its cgroup's memory. |

  - Every agent task passes `retries=0` with these values; `CANCEL_IN_PROGRESS` is avoided because it kills paid runs.
  - The cap is per tenant, so every agent worker and deployment on one tenant shares it. Scaling out means raising it.
  - The `agents` profile's Hatchet slots equal the cap's `max_runs` (KTD26). Because a cancelled run's slot frees before its cleanup ends, a host still holds memory for cap + 1 sessions (`docs/agents.md`).

  Governs R7, R9, R26.
- KTD17. **The examples are `tone`, `dir-summary` and `dir-review`, all on `claude-haiku-5-5`.**
  - **`tone`** (R18) has no tools, `max_turns=3` and `max_budget_usd=0.05`. It classifies a text as `friendly`, `neutral` or `unfriendly`, and its output adds `friendly: bool` from `corvo.core.agents.tone`.
  - **`dir-summary`** (R19) works in its directory read-only, with `Read`, `Glob`, `Grep` and the custom tool `count_words`, at `max_turns=15` and `max_budget_usd=0.25`. Its output is a summary and a word count.
  - `count_words` takes a text and never a path. Custom tools run in the agent worker's process, where a symlink in a working directory resolves against the worker's own files (R30). The tool is async and does no blocking work, because a blocked event loop starves the worker's heartbeats.
  - **`dir-review`** (R20) is a DAG on the main worker. Step `summarize` spawns `dir-summary`, and step `judge`, with parent `summarize`, spawns `tone` on the summary, both through stubs (KTD26). A core twin builds the review line.

  Governs R10, R18, R19, R20, R21, R30.
- KTD26. **One `corvo-worker` serves the permission profile that `CORVO_WORKER_PROFILE` names, and the main profile reaches agent tasks only through stubs.**
  - `corvo.worker.profiles` holds the `Profile` type and `PROFILES`, which maps each profile's name to its module's dotted path: `main` to `corvo.worker.profiles.main`, `agents` to `corvo.worker.profiles.agents`. It imports no profile module.
  - A profile module exposes one `PROFILE`, a frozen `Profile` with the Hatchet worker's name, its `workflows`, its `slots` (Hatchet's default when unset) and two optional hooks, `before_start` and `on_sigterm`:
    - `main`: `corvo-worker`, every task and workflow, no hooks. Its list is today's `WORKFLOWS`, moved out of `corvo.worker.worker`.
    - `agents`: `corvo-agent-worker`, every agent task and nothing else, `slots` equal to the cap's `max_runs` (KTD9), `before_start` running KTD10's checks and sweep, and `on_sigterm` running KTD19's hook.
  - `corvo.worker.worker.main()` runs logging, reads `worker_profile` (`CORVO_WORKER_PROFILE`, default `main`) from the settings, and imports that profile's module by name with `importlib`. An unknown name exits with status 1, naming the known ones. It then calls `serve(profile)`, which runs `before_start`, creates `hatchet.worker(name, slots=…, workflows=…)`, installs `on_sigterm` after Hatchet's own handler, and starts. The console script stays `corvo-worker`, and no second one exists.
  - Because the profile is imported by name, nothing the main profile imports reaches an agent task, and KTD2's fourth rule checks that.
  - `corvo.worker.agent_calls` declares one `hatchet.stubs.task` per agent task, with the same name and the same input and output model classes. The output models come from the agents' `models.py`. A directory agent's task input, its agent input plus `workdir` (KTD7), is declared in `agent_calls` itself, and the task imports it from there, so stub and task share one class. Workflows on the main profile spawn agents through these stubs, so the main profile never imports an agent task.
  - `tests/worker/test_registration.py` maps each area to its profile: tasks and workflows to `main`, agents to `agents`. It walks `PROFILES`, and fails when an area's definition is missing from its profile's list, when a definition sits on two profiles, or when a name repeats across profiles. It collects `agent_calls`' stubs apart from the areas' definitions, so a stub imported into a workflow module counts neither as unregistered nor as a name clash. Each stub must match an agent task's name and its input and output classes, and a stub on any profile's list fails, since it would take runs and raise.
  - A later permission profile, such as one with database access or a GitHub bot's, is a module with its `PROFILE`, a line in `PROFILES`, an area pair in the registration test and a compose service, with no new worker code. #37 adds `CORVO_WORKER_NAME` over the profile's name, and a compose test that every service names a known profile and every profile has a service.
  - (session-settled: user-directed — chosen over a second worker module with its own `main()`, list and console script, which copied the worker's start for what differs only in configuration.)

  Governs R6, R13, R20, R28; AE1.

### Risks

- **A timed-out parent step does not cancel its child.** The session budget bounds the child at `AGENT_EXECUTION_TIMEOUT`.

## Implementation Units

### U7. The `dir-review` workflow that spawns both agents

- **Goal:** a contributor can copy a workflow whose steps spawn agents as child runs and combine their outputs, from the main worker.
- **Requirements:** R7, R20, R21, R24, R25; AE7; KTD9, KTD17, KTD26.
- **Dependencies:** U6.
- **Files:**
  - Create `src/corvo/core/workflows/dir_review.py` and `tests/core/workflows/test_dir_review.py`.
  - Modify `src/corvo/worker/agent_calls.py` (the stubs of `tone` and `dir-summary`) and `tests/worker/test_registration.py` (the stubs check).
  - Create `src/corvo/worker/workflows/dir_review.py` and `tests/worker/workflows/test_dir_review.py`.
  - Modify `src/corvo/worker/profiles/main.py` (its list) and `tests/integration/worker/test_agents.py`.
- **Approach:**
  1. The core twin builds the review line from the word count and the tone over plain values.
  2. The stubs and their registration check per KTD26.
  3. `hatchet.workflow(name="dir-review")` holds two steps that spawn through the stubs: `summarize` spawns `dir-summary`, and `judge`, with parent `summarize`, spawns `tone` on the summary.
  4. Both steps declare `retries=0` and `AGENT_WAITING_EXECUTION_TIMEOUT`.
  5. The header adds the agent-waiting rule, why a waiting step holds a main-worker slot but no agent slot, and that agents are reached through stubs only.
- **Patterns to follow:** `src/corvo/worker/workflows/greeting.py` and its tests.
- **Test scenarios:**
  - The core twin's line names the tone and the word count.
  - `summarize`, mock-run with the `dir-summary` stub's `aio_run` replaced, passes the workflow's `workdir` and returns the replacement's output.
  - `judge`, mock-run with the parent output and the `tone` stub's `aio_run` replaced, passes the summary as the text and returns the core twin's line.
  - Both steps declare `retries == 0` and `AGENT_WAITING_EXECUTION_TIMEOUT`.
  - A stub whose output model differs from its task's fails the registration test, and so does a stub placed on either profile's list. A stub imported into `workflows/dir_review.py` counts neither as unregistered nor as a name clash.
  - Covers AE7. Integration: `dir-review` triggered by name on a working directory returns a review derived from both fakes' outputs. The main worker served the workflow and the agent worker served both children.
- **Verification:** the suites pass. The pull request records the workflow's Haiku proof, and the registration test passes with `dir-review` on the `main` profile and both agents on the `agents` profile.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/core tests/worker`: unit tests.
- `uv run pytest tests/integration/worker`: integration on compose.
- Manual: the Haiku runbook, once for `dir-review`.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- The integration tests pass, and the registration test passes with `dir-review` on the `main` profile and both agents on the `agents` profile.
- The pull request records the workflow's Haiku proof.
- The whole plan's Definition of Done holds for the stack.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u7-dir-review`, on top of `feat/agents-u6-dir-summary`, pull request new. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
