---
title: Agents Skeleton U4 Session Piece, Per-Run Cgroup and Tone Task - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u4-session-piece
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U4 Session Piece, Per-Run Cgroup and Tone Task - Plan

## Goal Capsule

- **Objective:** The agent worker's in-process side runs a session from start to cleanup, proven with the agent and the cgroup tree replaced.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 4 of 9 in stack order (unit U4). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U1, U3; it sits on `feat/agents-u3-tone-agent` in the stack. **Blocks:** U9 builds on this part directly; U6 and U7 through it.
- **Stop conditions:** stop and ask when Hatchet's cancellation or the SDK's transport close behave differently from this plan on the pinned versions, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U1: the wrapper and the `CORVO_SANDBOX_*` variables it reads.
- U2: the `agents` profile's list and the registration test.
- U3: `Session`, `consume`, `report.py` and the `tone` agent.
- From #36, which closes: its branch `feat/agents-u4-container-piece` stays on the remote as a reference. Re-create, do not cherry-pick:
  - 48b88db, the agent defaults, in sandbox wording;
  - d044538, the `tone` task's decorator;
  - `src/corvo/worker/agent_runtime/containers.py`'s `AgentFailed`, `printable`, the stderr prefix and caps, the shielded bounded cleanup and the in-flight set;
  - `src/corvo/worker/agent_runtime/spec.py`'s `check_workdir` and `session_budget`.

## Product Contract

### Summary

Adds the agent defaults, the per-run cgroup operations, the session piece `run_agent`, which runs one agent from the working-directory check to the cgroup's removal, and the thin `tone` task on the `agents` profile's list.

### Context

This is everything the agent worker's process does to run a session, proven in unit tests with the agent and the cgroup tree replaced. The real container, Hatchet and bubblewrap come in U9. R17 and R26 are completed there.

### Key Decisions

- **An agent is a Hatchet task that runs one agent session.** Workflows spawn it like any task. (session-settled: user-directed — chosen over an agent outside Hatchet that calls tasks as tools: both will exist, starting with this one.) Governs R6, R20.
- **Agent code lives in its own Hatchet-free package; the worker keeps only a thin task.** (session-settled: user-directed — chosen over an agents area inside `corvo.worker` that imports the SDK next to Hatchet.) Governs R1, R2, R6.
- **Each session's SDK engine runs in a fresh bubblewrap sandbox, and the SDK's sandbox with its credential scrub isolates every shell command inside it.** Measured together, the two layers stopped every escape a scripted shell command tried; either layer alone left some open. (session-settled: user-directed — chosen over the per-run Podman container, which left the forged result open, and over the SDK's sandbox alone, which leaves the worker's environment within every command's reach.) Governs R14, R15, R17, R26.
- **The caller gives the agent its working directory.** Cloning a repository or creating a worktree per issue is the caller's job. (session-settled: user-directed — chosen over the task building a temporary directory from its input.) Governs R5.
- **Hatchet does not retry agents.** A retry re-runs and re-pays the whole session, and the SDK already retries API errors itself. (session-settled: user-approved — chosen over corvo's `RETRIES` default, which assumes idempotent tasks.) Governs R7.

### Requirements

**Agent packages and boundaries**

- R5. An agent takes its working directory as a parameter and gives it to the SDK as the session's working directory. The task accepts only working directories strictly below `<root>/workdirs` (the `workdirs` directory under `CORVO_AGENT_ROOT`), resolving symlinks, and fails any other path before it starts a session.

**Hatchet integration**

- R6. Each agent has a thin Hatchet task in `corvo.worker.agents` with an explicit name and Pydantic input and output models. Agent tasks are registered only in the agent worker's list, which holds nothing else, and the registration test covers both workers.
- R7. Agent tasks declare `retries=0`, an agent execution timeout and an agent schedule timeout sized for the queue behind R9's cap, all defined once in the worker's defaults. A step that waits on an agent child declares a timeout derived from the agent's schedule and execution timeouts, not `WAITING_EXECUTION_TIMEOUT`.
- R8. A run that ends without valid structured output fails its task. That covers an error result, the turn or budget limit, and a success result without `structured_output`. In every case the task logs the run's cost, turns and session ID.
- R9. The pattern caps how many agent runs execute at once across the worker pool.

**Isolation**

- R17. One piece of the agent worker starts, bounds and ends each session's sandbox, and every agent task uses it. When Hatchet times out or cancels an agent task, no process of that run survives.
- R26. A session sees only its run's working directory, a temporary home and read-only system files, and its own cgroup limits its memory, CPU and processes. The working directory is read-only unless the agent declares that it writes to it.
- R29. What a session hands back, and whatever it writes into its working directory, is untrusted output: the task validates the output (R8), and the worker runs no hooks, config or code from the directory.

**Living examples**

- R21. Each example file opens with a header comment that carries the rules a copier needs, as the task and workflow examples do.

**Tests**

- R23. Each agent has unit tests that run without Hatchet and without a sandbox, with the SDK replaced. Agent tasks and the session piece have unit tests with the agent and the sandbox replaced.

### Acceptance Examples

- AE1. **Covers R6.** **Given** a new agent task in `corvo.worker.agents`, **when** its line is missing from the agent worker's list, **then** the registration test fails and names the task.
- AE3. **Covers R8.** **Given** an agent that reaches its turn limit, **when** its task finishes, **then** the run is marked failed without a retry, and its log holds the cost, turns and session ID.

### Scope Boundaries

Not in this part:

- No start checks, SIGTERM hook or compose service (U9).
- No integration test (U9).

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- hatchet-sdk 1.42.1 cancels a running async task's asyncio task on cancellation and timeout (`hatchet_sdk/worker/runner/runner.py:920-944`). It sets the context's cancellation flag, sleeps one second, cancels the task, and frees the task's slot without waiting for its `finally`. Engine timeout and cancel reach the worker as the same `CANCEL_STEP_RUN` action. The SDK also has an unpinned `claude` extra and `mcp_tool` (`hatchet_sdk/runnables/workflow.py:831`), neither used here.
- The engine re-queues a task whose worker misses heartbeats for 30 seconds as an internal failure, up to `MaxInternalRetryCount` times, which is 10, whatever its `retries` (engine v0.110.5 `pkg/repository/task.go`, `pkg/repository/sqlcv1/tasks.sql`). `ctx.retry_count` is above zero on such a re-run.

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD1. **An agent package exposes one coroutine, `run(input, session)`, in `agent.py`, and keeps everything the worker reads in `models.py`.**
  - `session` is a `Session` from `corvo.agents.session`: the per-run values the session piece supplies, which are `cli_path`, `cwd`, `env`, `sandbox`, and the `stderr` and `log` callbacks. `run` passes them into `ClaudeAgentOptions` itself, under the SDK's own names (R4), next to the options it owns (KTD3). For an agent with no working directory, `cwd` is `None` and the wrapper starts the engine in its tmpfs home (KTD20).
  - `run` returns its output model together with a `RunReport` (subtype, turns, cost and session ID), or raises `AgentRunFailed` carrying the same report. Both live in `corvo.agents.report`, which imports only Pydantic.
  - `run` hands the iterator `query()` returned to `consume(messages, schema, log)`. The result rule is unchanged: the run succeeds only when the result is not an error, its subtype is `success`, and its `structured_output` validates. `consume` reports the session ID through `log` as soon as the init message arrives.
  - `models.py` holds the input model, the schema model, the output model and `WRITES_WORKDIR`, and imports only Pydantic and the standard library.

  Governs R1, R3, R4, R8.
- KTD7. **One setting, `CORVO_AGENT_ROOT`, holds the working directories, and a task's input names one relative to `<root>/workdirs`.**
  - The task resolves the name, symlinks included, to an existing directory strictly below `<root>/workdirs`. It refuses `<root>/workdirs` itself, absolute names, names that leave it, and missing paths, before any session starts.
  - The wrapper opens the directory without following a final symlink. It checks that the opened descriptor's real path is still strictly below `<root>/workdirs`, and gives bubblewrap that descriptor (`--ro-bind-fd`, or `--bind-fd` when the agent writes). A symlink swapped in after the task's check, by another run that can write under the root, therefore cannot redirect the mount.
  - The caller creates the directory, readable by the agent worker's uid 1000 (writable too when the agent writes). It keeps credentials out of it, such as a token in `.git/config`, and deletes it afterwards. `docs/agents.md` and the examples' headers state these rules.
  - The main worker never reads a working directory, so only the agent worker mounts the root.

  Governs R5, R26, R29.
- KTD8. **Re-runs fail, and a session's end kills its cgroup before anything else.**
  - **Re-runs.** A run whose `ctx.retry_count` is above zero fails before any session. Its message names the re-run and says to trigger a new run, or to replay the parent step, which spawns a fresh child. (session-settled: user-directed — chosen over accepting every re-run: in-process, the engine's re-queue after a lost worker and a dashboard replay look the same, and accepting them re-pays sessions nobody asked for, up to the engine's 10 internal retries.)
  - **The session piece** (`corvo.worker.agent_runtime.sessions.run_agent`) checks the working directory, then creates the run's cgroup (KTD21). It builds the `Session` and starts the agent's `run` as a child task. It waits on that task with `asyncio.wait`, bounded by `session_budget`, which forwards neither the piece's own cancellation nor the deadline into the child. Awaiting the child directly would let a cancel reach the SDK's transport first, whose close can take up to 15 seconds before the kill below. The deadline is that wait ending with the child not done.
  - **The end.** On result, error, budget, Hatchet timeout or cancel, the piece first writes `cgroup.kill`, with no `await` before it. Only then does it cancel the child task and await it, which lets the SDK close the transport. It then polls until `cgroup.events` shows `populated 0`, writing `cgroup.kill` again on every poll, and removes the cgroup. The repeated kill catches a wrapper that joined just after the first one. All of that runs shielded and bounded to 10 seconds. A cgroup it cannot remove is logged and left for the next start's sweep (KTD10).
  - Hatchet frees the slot about a second after a cancel without waiting for this cleanup (Dependencies), which is why the kill comes first.

  Governs R7, R17.
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
- KTD20. **The wrapper `corvo-agent-sandbox` is the SDK's `cli_path`, and it starts the engine in a fresh bubblewrap of its own.**
  - It lives in `corvo.worker.agent_runtime.sandbox`, which imports only the standard library (KTD2): a pure function builds bubblewrap's arguments, and `main` only checks and execs.
  - It reads its run's values from variables the session piece puts in `options.env`: `CORVO_SANDBOX_CGROUP`, `CORVO_SANDBOX_WORKDIR` (empty for an agent without one), `CORVO_SANDBOX_WRITES`, `CORVO_SANDBOX_ENGINE` and `CORVO_SANDBOX_TMPFS`. A call without them exits non-zero.
  - It refuses to start unless the `--settings` argument the SDK passes holds `sandbox.enabled`, `failIfUnavailable: true` and `allowUnsandboxedCommands: false`, and no `excludedCommands` or `enableWeakerNestedSandbox`. An agent that left out `session.sandbox` therefore never runs. It also refuses a session that loads settings from disk, anything but the SDK's empty `--setting-sources=`, and a working directory bound over, inside or above a system path the sandbox mounts: `/usr`, `/etc`, `/proc`, `/dev`, the root symlinks and the engine's directory.
  - It writes its PID into the run's `cgroup.procs`, and exits non-zero if it cannot, so nothing starts outside the cgroup.
  - It then execs `bwrap` with an **empty environment**. bubblewrap's own pid 1 inside the sandbox is a fork that never execs, so the environment `bwrap` was started with stays readable at `/proc/1/environ`; `--clearenv` alone would leave the worker's Hatchet token there. Its arguments:
    - `--unshare-all --unshare-cgroup --share-net --die-with-parent --new-session --clearenv`. `--unshare-cgroup` is explicit, because `--unshare-all` only tries it;
    - each allowed variable by `--setenv`: the placeholder's variable, which is the credential variable holding the fixed placeholder `corvo.worker.agent_runtime.sandbox.PLACEHOLDER` (KTD12), `ANTHROPIC_BASE_URL`, `HOME`, `CLAUDE_CONFIG_DIR`, `PATH`, the SDK's own `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_AGENT_SDK_VERSION` and `CLAUDE_CODE_SDK_READS_SESSION_STATE`, and the isolation flags, which the wrapper sets itself whatever `options.env` held;
    - `/usr` and `/etc` read-only, with their symlinks; a fresh `/proc` and `/dev`, and no `/sys`; `/tmp` and the home as tmpfs of `CORVO_SANDBOX_TMPFS`;
    - the engine's directory read-only, and the working directory by descriptor (KTD7) at the same path, or `--chdir` to the home when there is none.
  - The isolation flags are `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` and `ENABLE_CLAUDEAI_MCP_SERVERS=false`. `HOME` and `CLAUDE_CONFIG_DIR` point into the tmpfs home.
  - The agent worker sets `CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1` in its own environment, so the SDK never runs the wrapper with `-v`.
  - These are the arguments measured on 2026-10-15 (Dependencies), whose wrapper ran `env -i` before `bwrap`. The variable filter is tightened from a prefix match to an allowlist.

  Governs R11, R14, R15, R26.
- KTD21. **Each run gets a cgroup, `<agent_cgroup_root>/run-<task_run_id>`, made before the session and removed after it.**
  - It sets `memory.max` to `AGENT_MEMORY`, `memory.swap.max` to 0, `memory.oom.group` to 1, `cpu.max` from `AGENT_CPUS` and `pids.max` to `AGENT_PIDS_LIMIT`.
  - After the end, the piece reads `memory.events`. A non-zero `oom_kill` turns the failure's reason into `out of memory`, in the error and in the run log (AE9).
  - The worker owns each `run-*` cgroup's files, and a session runs as the same uid. What keeps a session from rewriting its own limits is the cgroup namespace bubblewrap gives it, under `nsdelegate` (KTD10), and the absence of `/sys` in its sandbox. U8 tries both ways around them.
  - Leftovers come only from a cleanup that failed while the worker lived, because a worker restart is a container restart and drops the subtree. KTD10 sweeps them at start.

  Governs R17, R26.
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
- KTD27. **The run log carries the engine's stderr behind a fixed prefix and always ends with the run's report.**
  - The SDK's `stderr` callback sends each line to `ctx.log` behind `agent stderr: `, cut to 500 characters with control characters stripped, up to 900 lines. That leaves Hatchet's 1000-line budget room for the worker's own lines.
  - The report line (subtype, turns, cost, session ID, and `out of memory` when it applies) is logged to `ctx.log` and to the worker's stdout. After a cancel, `ctx.log` may no longer reach the run.
  - Nothing a session returns or prints is echoed unsanitized (R29).

  Governs R8, R29.

### Risks

- **The cap over-commits for a moment.** A cancelled run's slot frees before its cleanup ends, so cap + 1 sessions can briefly coexist. The cgroup kill comes first (KTD8) and the sizing allows for it (KTD9).
- **A timed-out parent step does not cancel its child.** The session budget bounds the child at `AGENT_EXECUTION_TIMEOUT`.

### Deferred to Implementation

- The SDK's exact close behavior after `cgroup.kill`, and the bound on awaiting it inside KTD8's 10 seconds.

## Implementation Units

### U4. The session piece, the per-run cgroup and the `tone` task

- **Goal:** the agent worker's in-process side runs a session from start to cleanup, proven with the agent and the cgroup tree replaced.
- **Requirements:** R5, R6, R7, R8, R9, R17, R21, R23, R26, R29; AE1, AE3; KTD7, KTD8, KTD9, KTD21, KTD27.
- **Dependencies:** U1, U3.
- **Files:**
  - Modify `src/corvo/worker/defaults.py` and `tests/worker/test_defaults.py`.
  - Create `src/corvo/worker/agent_runtime/cgroups.py` and `src/corvo/worker/agent_runtime/sessions.py`.
  - Create `src/corvo/worker/agents/tone.py`, and modify `src/corvo/worker/profiles/agents.py` (its list).
  - Create `tests/worker/agent_runtime/test_cgroups.py` and `tests/worker/agent_runtime/test_sessions.py`.
  - Create `tests/worker/agents/__init__.py` and `tests/worker/agents/test_tone.py`.
- **Approach:**
  1. Defaults per KTD9, re-created from 48b88db with prose comments in sandbox wording.
  2. `cgroups.py` holds the cgroup operations of KTD21 behind a root path, so unit tests drive them on a fake directory tree.
  3. `sessions.py` runs one agent per KTD7, KTD8 and KTD27, with `check_workdir` and `session_budget` moved in from `spec.py`. It keeps `containers.py`'s error and cleanup patterns.
  4. The `tone` task, re-created from d044538, keeps its decorator and hands `corvo.agents.tone.agent.run` to the session piece. Its header carries R21's rules for a copier: thin shell, the agent named once, the retries rule and why, the agent list, no stubs in this area.
- **Patterns to follow:** `src/corvo/worker/agent_runtime/containers.py` on `feat/agents-u4-container-piece` for cleanup and the in-flight set; `tests/worker/workflows/test_greeting.py` for declaration tests and mock runs.
- **Test scenarios:**
  - The `tone` task declares `retries == 0`, `AGENT_EXECUTION_TIMEOUT`, `AGENT_SCHEDULE_TIMEOUT` and the `corvo-agents` concurrency.
  - `AGENT_WAITING_EXECUTION_TIMEOUT` is at least `AGENT_SCHEDULE_TIMEOUT + AGENT_EXECUTION_TIMEOUT + DETECTION_LAG`.
  - The working-directory check accepts a name strictly below `<root>/workdirs`. It rejects the empty name, an absolute path, `../other`, a symlink pointing outside, and a missing directory, before any cgroup exists.
  - With a replaced agent returning an output and a report, the piece returns the output and logs the report line. The run's cgroup was created with every KTD21 limit, then removed.
  - With a replaced agent raising `AgentRunFailed`, the task fails with the reason, and the log holds the report.
  - With `oom_kill` set in the fake tree's `memory.events`, the failure's reason is `out of memory`.
  - A cancel delivered while the agent is running writes `cgroup.kill` before the agent's own cleanup runs, and the cgroup is removed within the bound.
  - A cancel delivered right after the cgroup is made, before the agent starts, still removes the cgroup.
  - A process that joins the cgroup after the first `cgroup.kill` is killed by a later poll, and the cgroup is removed.
  - A cgroup that never empties is logged and left after the 10-second bound, and the run keeps its own failure.
  - With `ctx.retry_count` of 1, the task fails before creating a cgroup, with the re-run message.
  - Stderr lines reach `ctx.log` behind `agent stderr: `, cut to 500 characters, stopping after 900 lines, and the report line still lands after the cap.
  - A stderr line or a failure reason holding control characters or terminal escapes reaches the log with them stripped.
  - Covers AE1. Removing `tone` from the `agents` profile's list makes the registration test fail, naming it.
- **Verification:** the unit suite passes, and coverage of `src` stays at 90% or above.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/agents tests/core tests/worker`: unit tests, no Docker.
- The coverage floor as CI runs it: `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `uv run --locked --with coverage==7.16.2 coverage report --fail-under=90`.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- The session piece's unit tests pass, and coverage of `src` stays at 90% or above.
- No container, docker-py or Podman code is re-created from #36.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u4-session-piece`, on top of `feat/agents-u3-tone-agent`, pull request new. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
