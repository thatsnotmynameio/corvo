---
title: Agents Skeleton U6 Dir-Summary Agent - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u6-dir-summary
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U6 Dir-Summary Agent - Plan

## Goal Capsule

- **Objective:** A contributor can copy an agent that works in a directory it is given, with read-only file tools and one custom tool whose logic lives in the core.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 8 of 9 in stack order (unit U6). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U5; it sits on `feat/agents-u5-operations` in the stack. **Blocks:** U7 builds on this part directly.
- **Stop conditions:** stop and ask when the SDK's `@tool` or `mcp_message` flow differs from this plan on 0.2.167.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U3's `tone` agent and its tests, the pattern this agent follows.
- U4's session piece, its working-directory check and the `tone` task.
- U5's proxy and `docs/agents.md`, which this part's working-directory rules extend.

## Product Contract

### Summary

Adds the `dir-summary` agent, its core twin and its custom tool `count_words`, its thin task, and `corvo.worker.agent_calls` with the task's input model.

### Context

`dir-summary` is the second living example (R19): it combines the working directory with a custom tool. Custom tools run in the agent worker's process, outside the sandbox (R30).

### Key Decisions

- **Agent code lives in its own Hatchet-free package; the worker keeps only a thin task.** (session-settled: user-directed — chosen over an agents area inside `corvo.worker` that imports the SDK next to Hatchet.) Governs R1, R2, R6.
- **One package per agent, with `agent.py` and `prompts/`, plus `tools.py` when the agent has custom tools, mirrored by a core twin.** These are the names Google ADK, Anthropic's Agent SDK cookbooks and demos, and Hatchet's agent examples use. (session-settled: user-approved — chosen over a prompt held as a constant in code, and over SDK-named files such as `agent_claude.py`.) Governs R1, R3.
- **Prompts live with the agent, not in the core.** A prompt is tuned to its SDK and model. The core holds only logic that survives an SDK change. (session-settled: user-approved — chosen over prompts in the core: a prompt is tuned to its SDK and model.) Governs R1, R3.
- **The caller gives the agent its working directory.** Cloning a repository or creating a worktree per issue is the caller's job. (session-settled: user-directed — chosen over the task building a temporary directory from its input.) Governs R5.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.
- **Three examples cover the four shapes.** Example 2 combines the working directory with a custom tool, as `greeting-rounds` combined spawning and waiting. (session-settled: user-approved — chosen over one example per shape.) Governs R18, R19, R20.

### Requirements

**Agent packages and boundaries**

- R1. `corvo.agents` holds one package per agent. `agent.py` builds the SDK options and runs the session, `models.py` holds the agent's Pydantic models and imports no SDK, `tools.py` holds the agent's custom tools when it has any, and `prompts/` holds the prompt text files the agent reads and passes to the SDK.
- R3. Logic that must survive an SDK change, such as decisions on the agent's output and its tools' logic, lives in pure functions in `corvo.core.agents` at the mirrored path. The agent package only adapts that logic to the SDK.
- R5. An agent takes its working directory as a parameter and gives it to the SDK as the session's working directory. The task accepts only working directories strictly below `<root>/workdirs` (the `workdirs` directory under `CORVO_AGENT_ROOT`), resolving symlinks, and fails any other path before it starts a session.

**Agent execution**

- R10. Every agent declares its model, its turn limit and its budget limit.
- R11. Agents load no CLAUDE.md, skills, settings or auto memory, whether from the host or from the working directory. They use only tools they list explicitly, and every other tool call is denied.

**Isolation**

- R30. Custom tools run in the agent worker's process, outside the sandbox, so each one treats its input as untrusted.

**Living examples**

- R19. An agent works in the directory it receives, with the SDK's read-only file tools and one custom tool whose logic lives in the core.
- R21. Each example file opens with a header comment that carries the rules a copier needs, as the task and workflow examples do.

**Tests**

- R23. Each agent has unit tests that run without Hatchet and without a sandbox, with the SDK replaced. Agent tasks and the session piece have unit tests with the agent and the sandbox replaced.
- R24. The integration suite runs every example on the real Hatchet and real bubblewrap with the SDK's engine replaced, including the end of a run on timeout. It creates its working directories below `<root>/workdirs` (R5), not in pytest's temporary directories.
- R25. Each example is proven once against real Claude Haiku with a small prompt, through a documented manual command whose run is recorded in the pull request.

### Acceptance Examples

- AE6. **Covers R11.** **Given** a working directory that holds a CLAUDE.md and `.claude/skills/`, **when** an agent runs in it, **then** the session loads neither.

### Scope Boundaries

Not in this part:

- No writable working directory: the integration scenario and its permission checks wait for the first agent that writes.
- No stubs (U7): `agent_calls` holds only the task's input model here.

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- `allowed_tools` with `permission_mode="dontAsk"` still lets read-only Bash, the Agent tool and reads inside the working directory run. Restricting the tool set takes the `tools` option (Agent SDK `permissions.md`).
- Per the Claude Code sandboxing doc, the SDK's sandbox covers only the commands of Bash, PowerShell and Monitor, and file tools follow permission rules. The Python SDK runs commands unsandboxed when the sandbox cannot start, unless `failIfUnavailable` is set. Per the env-vars doc, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips credentials from commands' environments and runs them in their own PID namespace.
- uv_build packages every file under `src/corvo/`, so `prompts/*.md` reaches the wheel with no configuration (checked by building one). `.dockerignore` excludes `tests/`.

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD1. **An agent package exposes one coroutine, `run(input, session)`, in `agent.py`, and keeps everything the worker reads in `models.py`.**
  - `session` is a `Session` from `corvo.agents.session`: the per-run values the session piece supplies, which are `cli_path`, `cwd`, `env`, `sandbox`, and the `stderr` and `log` callbacks. `run` passes them into `ClaudeAgentOptions` itself, under the SDK's own names (R4), next to the options it owns (KTD3). For an agent with no working directory, `cwd` is `None` and the wrapper starts the engine in its tmpfs home (KTD20).
  - `run` returns its output model together with a `RunReport` (subtype, turns, cost and session ID), or raises `AgentRunFailed` carrying the same report. Both live in `corvo.agents.report`, which imports only Pydantic.
  - `run` hands the iterator `query()` returned to `consume(messages, schema, log)`. The result rule is unchanged: the run succeeds only when the result is not an error, its subtype is `success`, and its `structured_output` validates. `consume` reports the session ID through `log` as soon as the init message arrives.
  - `models.py` holds the input model, the schema model, the output model and `WRITES_WORKDIR`, and imports only Pydantic and the standard library.

  Governs R1, R3, R4, R8.
- KTD3. **Each agent sets the options it owns; the session supplies the isolation it does not.**
  - The agent passes `tools=[…]`, `allowed_tools` (its file tools as rules scoped to `session.cwd`, its other built-ins by name, its `mcp__<server>__<tool>` names), `permission_mode="dontAsk"`, `setting_sources=[]`, `skills=[]`, `strict_mcp_config=True`, `model`, `max_turns` and `max_budget_usd`.
  - The session supplies `cli_path`, `cwd`, `env` (KTD20) and `sandbox`. `sandbox` is `enabled`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands: false`, `failIfUnavailable: true`, and a network allowlist that is empty for every example.
  - SDK 0.2.167's `SandboxSettings` type lacks `failIfUnavailable`, which the bundled engine reads. `corvo.agents.session` builds that one dictionary, with the one typed cast it needs. A fake-CLI test asserts the key reaches the engine's `--settings`.
  - `tests/agents/isolation.py` asserts both halves on every agent's options, which keeps a corvo options builder out of the runtime code (R4). It also rejects `WebFetch` and `WebSearch` until a network decision covers what the engine itself may reach (KTD24). An agent that leaves out a session value still cannot run unsandboxed: KTD13 moves the engine out of the SDK's package, and the wrapper checks the sandbox settings itself (KTD20).

  Governs R10, R11, R15.
- KTD7. **One setting, `CORVO_AGENT_ROOT`, holds the working directories, and a task's input names one relative to `<root>/workdirs`.**
  - The task resolves the name, symlinks included, to an existing directory strictly below `<root>/workdirs`. It refuses `<root>/workdirs` itself, absolute names, names that leave it, and missing paths, before any session starts.
  - The wrapper opens the directory without following a final symlink. It checks that the opened descriptor's real path is still strictly below `<root>/workdirs`, and gives bubblewrap that descriptor (`--ro-bind-fd`, or `--bind-fd` when the agent writes). A symlink swapped in after the task's check, by another run that can write under the root, therefore cannot redirect the mount.
  - The caller creates the directory, readable by the agent worker's uid 1000 (writable too when the agent writes). It keeps credentials out of it, such as a token in `.git/config`, and deletes it afterwards. `docs/agents.md` and the examples' headers state these rules.
  - The main worker never reads a working directory, so only the agent worker mounts the root.

  Governs R5, R26, R29.
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

### Deferred to Implementation

- Whether Glob and Grep need an executable `/tmp`. bubblewrap's tmpfs is executable unless remounted, so this only matters if a later hardening adds `noexec`.
- The fake CLI's canned outputs per schema title, and the exact `asyncio.timeout` of each integration test.

## Implementation Units

### U6. The `dir-summary` agent: working directory and a custom tool

- **Goal:** a contributor can copy an agent that works in a directory it is given, with read-only file tools and one custom tool whose logic lives in the core.
- **Requirements:** R1, R3, R5, R10, R11, R19, R21, R23, R24, R25, R30; AE6; KTD1, KTD3, KTD7, KTD17, KTD26.
- **Dependencies:** U5.
- **Files:**
  - Create `src/corvo/core/agents/dir_summary.py` and `tests/core/agents/test_dir_summary.py`.
  - Create `src/corvo/agents/dir_summary/__init__.py`, `models.py`, `agent.py`, `tools.py` and `prompts/system.md`.
  - Create `tests/agents/dir_summary/__init__.py`, `test_agent.py` and `test_tools.py`.
  - Create `src/corvo/worker/agent_calls.py` (the task's input model) and `src/corvo/worker/agents/dir_summary.py`, with `tests/worker/agents/test_dir_summary.py`.
  - Modify `src/corvo/worker/profiles/agents.py` (its list).
  - Modify `tests/agents/fake_claude.py` (canned output and the tool call) and `tests/integration/worker/test_agents.py`.
- **Approach:**
  1. The core twin counts the words in a text over plain `str`.
  2. `tools.py` declares `count_words` with the SDK's `@tool`, takes a text and calls the core twin (KTD17).
  3. `agent.py` uses `session.cwd`, `tools=["Read", "Glob", "Grep"]`, those three as rules scoped to the working directory, and `mcp__dir_summary__count_words`.
  4. `agent_calls.py` declares the task's input model, the agent's input plus `workdir`, and the task imports it from there (KTD26).
  5. The fake drives `count_words` through `mcp_message` and puts the tool's result into its structured output.
  6. The headers add the custom-tool rules (logic in the core twin; no path from the model; async, no blocking work) and the working-directory rules (KTD7).
- **Patterns to follow:** U3's `tone` agent and U4's task.
- **Test scenarios:**
  - The core twin counts `"one two  three\n"` as 3 and an empty text as 0.
  - The `count_words` handler returns the core twin's count in the SDK's tool-result shape.
  - With `query` replaced, `run` passes the session's `cwd`. Its options pass the isolation helper with exactly the three built-ins, scoped to that directory, and the one custom tool.
  - The isolation helper rejects options whose `allowed_tools` holds an unscoped `Read`, `Glob` or `Grep`.
  - The task rejects a `workdir` that leaves `<root>/workdirs` before any cgroup exists.
  - Integration: `dir-summary` on a working directory holding two small files returns the fake's summary and the word count the core twin computed in the worker. The fake reports its working directory as read-only.
- **Verification:** the suites pass. The pull request records the Haiku proof, including AE6 and tool denial: the session ignores a planted CLAUDE.md and `.claude/skills/`, and a request for a tool outside its list is denied.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/agents tests/core tests/worker`: unit tests.
- `uv run pytest tests/integration/worker`: integration on compose.
- Manual: the Haiku runbook, once for `dir-summary`.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- The integration tests pass.
- The pull request records the Haiku proof, including AE6 and tool denial.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u6-dir-summary`, on top of `feat/agents-u5-operations`, pull request new. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
