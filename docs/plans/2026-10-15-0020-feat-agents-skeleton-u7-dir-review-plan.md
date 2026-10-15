---
title: Agents Skeleton U7 Dir Review Workflow - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u7-dir-review
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U7 Dir Review Workflow - Plan

## Goal Capsule

- **Objective:** A contributor can copy a workflow whose steps spawn agents as child runs and combine their outputs.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 7 of 7. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** U6. **Blocks:** none; this is the top of the stack.
- **Stop conditions:** stop and ask when the SDK, Hatchet or Podman behaves differently from this plan on the pinned versions, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U4: the agent defaults, `AGENT_WAITING_EXECUTION_TIMEOUT` included, and the `tone` task.
- U5: `docs/agents.md` and its manual proof runbook.
- U6: the `dir-summary` task.

## Product Contract

### Summary

Adds the `dir-review` DAG, whose `summarize` step spawns `dir-summary` and whose `judge` step spawns `tone` on the summary, with its core twin and tests.

### Context

This is the example for workflows that hand steps to agents. R20 and AE7 are completed here, with R25's proof for the workflow.

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

- R24. The integration suite runs every example on the real Hatchet and a real rootless Podman, with the SDK replaced inside the container, including the kill and removal on timeout. It creates its working directories under the agent-workdir root (R5), not in pytest's temporary directories.
- R25. Each example is proven once against real Claude Haiku with a small prompt, through a documented manual command whose run is recorded in the pull request.

### Acceptance Examples

- AE7. **Covers R20, R24.** **Given** the workflow example on Hatchet and Podman with the SDK replaced, **when** it runs, **then** it returns outputs derived from both agents' structured outputs.

### Scope Boundaries

- No new agent.

## Planning Contract

### Key Technical Decisions

- KTD1. **An agent package exposes one coroutine, `run`, in `agent.py`, and keeps everything the worker reads in `models.py`.**
  - `run` takes the agent's input model and its working directory (`None` for an agent without one). It returns its output model together with a `RunReport`: the subtype, turns, cost and session ID.
  - A failed session raises `AgentRunFailed`, which carries the same report. Both types live in `corvo.agents.envelope`, which imports only Pydantic.
  - Inside, `run` builds `ClaudeAgentOptions` and calls `query()` itself, with the SDK's own names (R4). It hands the iterator `query()` returned to `corvo.agents.session.consume`, which applies KTD4's result rule and returns the structured output and the report, or raises. The helper consumes the SDK's stream, and does not wrap or replace any of its calls.
  - `models.py` holds the input model, the model whose JSON Schema becomes `output_format`, the output model, and a `WRITES_WORKDIR` flag. It imports only Pydantic and the standard library.
  - The worker imports `models.py` and the SDK-free shared modules `envelope` and `fingerprint`, never `agent.py`, `tools.py` or `session.py`.

  The container's entrypoint, `corvo-agent` (`corvo.agents.runner`), imports `corvo.agents.<package>.agent`, validates the request's input with the input model, awaits `run`, and writes the envelope from what `run` returned or raised. The entrypoint sits outside the agent, not between the agent and the SDK. The agent's output model wraps the session's structured output and any field its core twin derives from it (R3). Governs R1, R3, R4, R8, R17.
- KTD4. **The container hands back a JSON envelope framed on its stdout, and the worker treats it as untrusted.**
  - **The request.** The worker writes the request to the container's stdin, holding the agent package, its input, and a session budget in seconds. The budget is `AGENT_EXECUTION_TIMEOUT` minus `AGENT_DEADLINE_MARGIN`, minus the time already passed since the task started. Hatchet's timer starts at assignment, so a deadline equal to the timeout would never fire before Hatchet's own.
    - The request is framed by its length: an ASCII decimal length, a newline, then exactly that many bytes, at most 1 MiB. `corvo.agents.frame` holds the rule for both sides (agent-request-stdin plan, KTD1).
    - The worker attaches to the created container before it starts, and writes the frame within `REQUEST_WRITE_TIMEOUT` (45 s). A container that never reads fails the run within that bound (agent-request-stdin plan, KTD2, KTD3).
    - The runner reads the frame within `REQUEST_READ_TIMEOUT` (30 s), then points fd 0 at `/dev/null`. A request that does not arrive whole fails as `invalid_request` (agent-request-stdin plan, KTD4).
  - **Running the session.** The runner runs `run` under `asyncio.timeout` to that budget. Inside `run`, `corvo.agents.session.consume` keeps the last `ResultMessage` and catches `ResultError` and `ProcessError`. It prints the session ID to stderr when the init message arrives. The run succeeds only when the result is not an error, its subtype is `success`, and its `structured_output` validates.
  - **The envelope.** The runner frames the envelope on a private copy of its stdout, and points fd 1 at stderr, so nothing else printed reaches the frame (agent-request-stdin plan, KTD6). It holds:
    - a protocol version;
    - `ok` or `failed`, with the output or the reason (`deadline` when the budget ran out);
    - the run report: subtype, turns, cost and session ID.
  - **Reading the envelope.** The worker reads the attach stream. Stdout is kept up to one frame at the 1 MiB cap and drained past it, so the container never blocks. Reading continues until the stream ends, at most `DRAIN_TIMEOUT` (5 s) after the container exits (agent-request-stdin plan, KTD6). A missing or truncated frame is "no envelope". A bad header, an oversized frame or invalid JSON is "invalid envelope". The worker never echoes what it read, and validates it with the envelope model. The probe's report (KTD10) is read the same way.
  - **Failures.** A failed envelope, a missing or invalid one, or an out-of-memory kill fails the task. The worker logs the cost, turns and session ID from the validated envelope only. When no envelope exists, it logs them as `unknown`, with the exit code and the OOM flag.
  - **Forwarding stderr.** The worker sends the stderr lines of the attach stream to `ctx.log` behind a fixed `agent stderr:` prefix, so a line the agent prints can never pass for one of the worker's own. Each line is cut to 500 characters with control characters stripped, up to 900 lines (Hatchet keeps 1000).

  The attach stream's stdout reaches the worker raw and never reaches Hatchet's log, and the runner's private stdout keeps anything else printed out of the frame (agent-request-stdin plan, KTD6). Governs R8, R13, R15.
- KTD9. **The agent defaults live in `src/corvo/worker/defaults.py`, each with a prose comment, as KTD1 of the precedent does.**

  | Constant | Value | Why |
  |---|---|---|
  | `AGENT_EXECUTION_TIMEOUT` | 15 minutes | The longest example session plus container start. |
  | `AGENT_DEADLINE_MARGIN` | 60 seconds | The in-container budget (KTD4) ends this long before Hatchet's timeout, which leaves time to write, read and clean up. |
  | `AGENT_SCHEDULE_TIMEOUT` | 60 minutes | Waiting behind the cap counts against it (engine `schedule_timeout_at`). |
  | `AGENT_WAITING_EXECUTION_TIMEOUT` | 80 minutes | One attempt queued and run (`retries=0`), plus a 5-minute detection margin. |
  | `AGENT_CONCURRENCY` | `max_runs=2` | A `ConcurrencyExpression` named `corvo-agents`, with a constant key, `GROUP_ROUND_ROBIN` and `is_tenant_scoped=True`. |
  | `AGENT_MEMORY` | 2 GiB | Anthropic's 1 GiB floor, doubled for the CLI and its tools. |
  | `AGENT_NANO_CPUS` | 1 CPU | Anthropic's starting point. |
  | `AGENT_PIDS_LIMIT` | 256 | Above the CLI's threads. Measured in the Haiku proof. |

  - Every agent task passes `retries=0` with these values.
  - `CANCEL_IN_PROGRESS` is avoided, because it kills paid runs.
  - The cap is per tenant, and so shared by deployments on one tenant.

  Governs R7, R9, R15.
- KTD17. **The examples are `tone`, `dir-summary` and `dir-review`, all on `claude-haiku-5-5`.**
  - **`tone`** (R18) has no tools, `max_turns=3` and `max_budget_usd=0.05`. Its session classifies a text as `friendly`, `neutral` or `unfriendly`. Its output adds `friendly: bool` from `corvo.core.agents.tone`.
  - **`dir-summary`** (R19) mounts its working directory read-only. It uses `Read`, `Glob`, `Grep` and the custom tool `count_words`, whose logic is `corvo.core.agents.dir_summary.count_words`, with `max_turns=15` and `max_budget_usd=0.25`. Its output is a summary and a word count.
  - **`dir-review`** (R20) is a DAG. Step `summarize` spawns `dir-summary`, and step `judge`, with parent `summarize`, spawns `tone` on the summary. A core twin builds the review line from both outputs.
  - A task whose agent works in a directory declares its own input model in the worker module: the agent's input plus `workdir`. The agent receives `/workspace`.

  Governs R10, R18, R19, R20, R21.

## Implementation Units

### U7. The `dir-review` workflow that spawns both agents

- **Goal:** a contributor can copy a workflow whose steps spawn agents as child runs and combine their outputs.
- **Requirements:** R7, R20, R21, R24, R25, AE7; KTD9, KTD17.
- **Dependencies:** U6.
- **Files:**
  - Create `src/corvo/core/workflows/dir_review.py` and `tests/core/workflows/test_dir_review.py`.
  - Create `src/corvo/worker/workflows/dir_review.py` and `tests/worker/workflows/test_dir_review.py`.
  - Modify `src/corvo/worker/worker.py` (`WORKFLOWS`) and `tests/integration/worker/test_agents.py`.
- **Approach:**
  1. The core twin builds the review line from the summary's word count and the tone over plain values.
  2. `hatchet.workflow(name="dir-review")` holds two steps. `summarize` spawns `dir_summary`. `judge`, with parent `summarize`, spawns `tone` on the summary and returns the review through the core twin.
  3. Both steps declare `retries=0` and `AGENT_WAITING_EXECUTION_TIMEOUT` (R7), the agent counterpart of the precedent's waiting rule.
  4. The header comment adds the agent-waiting rule and the reason a waiting step holds a worker slot but no agent slot.
- **Patterns to follow:** `src/corvo/worker/workflows/greeting.py` and its tests.
- **Test scenarios:**
  - The core twin's line names the tone and the word count.
  - `summarize`, mock-run with `dir_summary.aio_run` replaced, passes the workflow's `workdir` and returns the replacement's output.
  - `judge`, mock-run with the parent output and `tone.aio_run` replaced, passes the summary as the text and returns the core twin's line.
  - Both steps declare `retries == 0` and `AGENT_WAITING_EXECUTION_TIMEOUT`.
  - Covers AE7. Integration: `dir-review` triggered by name on a working directory under the root returns a review derived from both fakes' structured outputs.
- **Verification:** unit and integration suites pass. The PR records the workflow's Haiku proof, and the registration test passes with all three definitions in `WORKFLOWS`.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict with `types-docker`, lockfile.
- `uv run pytest tests/test_import_boundaries.py tests/test_settings.py tests/agents tests/core tests/worker`: unit tests, no Docker or Podman.
- `uv run pytest tests/integration/worker`: integration on compose and the test's rootless Podman (needs Docker and Podman).
- `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `coverage report --fail-under=90` the same way: CI's coverage floor.
- The manual Haiku proof in `docs/agents.md`, recorded in the PR.

## Definition of Done

- Every gate above passes locally and in CI.
- U7 when its integration test passes, its Haiku proof is recorded, and the registration test passes with all six definitions in `WORKFLOWS`.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-podman-fixture` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-container-piece` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u7-dir-review`, on top of `feat/agents-u6-dir-summary`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
