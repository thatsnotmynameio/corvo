---
title: Agents Skeleton U3 Tone Agent on the Session Carrier - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u3-tone-agent
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U3 Tone Agent on the Session Carrier - Plan

## Goal Capsule

- **Objective:** A contributor can copy an agent with no tools that turns a Pydantic input into a structured output, written against the `Session` the agent worker supplies.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 3 of 9 in stack order (unit U3). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U2; it sits on `feat/agents-u2-boundaries` in the stack. **Blocks:** U4 builds on this part directly; U6 copies it.
- **Stop conditions:** stop and ask when the SDK's message types or its control protocol differ from this plan on 0.2.167, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U2: the agent areas, the guard and the boundary test.
- #35's code on `feat/agents-u3-tone-agent`, reworked on top of U2:
  - kept: 075c201 (core twin), 3112cc9 (the `tone` agent and the isolation helper), 06ec8db, 5762cd6, and 44c57de's fake CLI and contract test;
  - reworked: 3a4045e, whose `envelope.py` becomes `report.py` and whose `session.py` gains `Session`;
  - dropped: b906cc5 (`runner.py`, `fingerprint.py`, the `corvo-agent` script and their tests), c05e8de (the `agent` stage), 4d29143 and d840c94 (the runner's tests and fix), 44c57de's `tests/agents/fake/Containerfile`, and c4d70c4's part in `test_runner.py`.

## Product Contract

### Summary

Adds the `tone` agent and its core twin, the `Session` carrier and the result rule in `corvo.agents.session`, `corvo.agents.report`, the isolation helper over every agent's options, and the fake `claude` CLI with its contract test.

### Context

`tone` is the first living example (R18). It is written against the `Session` the agent worker supplies in U4, so it never builds its own isolation, and it runs nowhere yet: U4 gives it a task and U9 a worker. No module of the container design survives under `corvo.agents`.

### Key Decisions

- **Each agent uses its SDK's own API, with no corvo interface over SDKs.** Agents share a shape, not a contract: a thin task, a core twin, Pydantic models, defaults and registration. (session-settled: user-directed — chosen over one agent definition runnable on any SDK through corvo adapters, and over a common corvo contract every SDK adapter implements.) Governs R4.
- **Agent code lives in its own Hatchet-free package; the worker keeps only a thin task.** (session-settled: user-directed — chosen over an agents area inside `corvo.worker` that imports the SDK next to Hatchet.) Governs R1, R2, R6.
- **One package per agent, with `agent.py` and `prompts/`, plus `tools.py` when the agent has custom tools, mirrored by a core twin.** These are the names Google ADK, Anthropic's Agent SDK cookbooks and demos, and Hatchet's agent examples use. (session-settled: user-approved — chosen over a prompt held as a constant in code, and over SDK-named files such as `agent_claude.py`.) Governs R1, R3.
- **Prompts live with the agent, not in the core.** A prompt is tuned to its SDK and model. The core holds only logic that survives an SDK change. (session-settled: user-approved — chosen over prompts in the core: a prompt is tuned to its SDK and model.) Governs R1, R3.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.
- **Three examples cover the four shapes.** Example 2 combines the working directory with a custom tool, as `greeting-rounds` combined spawning and waiting. (session-settled: user-approved — chosen over one example per shape.) Governs R18, R19, R20.

### Requirements

**Agent packages and boundaries**

- R1. `corvo.agents` holds one package per agent. `agent.py` builds the SDK options and runs the session, `models.py` holds the agent's Pydantic models and imports no SDK, `tools.py` holds the agent's custom tools when it has any, and `prompts/` holds the prompt text files the agent reads and passes to the SDK.
- R3. Logic that must survive an SDK change, such as decisions on the agent's output and its tools' logic, lives in pure functions in `corvo.core.agents` at the mirrored path. The agent package only adapts that logic to the SDK.
- R4. Every agent is written with its SDK's own API, with no corvo layer between it and the SDK.

**Hatchet integration**

- R8. A run that ends without valid structured output fails its task. That covers an error result, the turn or budget limit, and a success result without `structured_output`. In every case the task logs the run's cost, turns and session ID.

**Agent execution**

- R10. Every agent declares its model, its turn limit and its budget limit.
- R11. Agents load no CLAUDE.md, skills, settings or auto memory, whether from the host or from the working directory. They use only tools they list explicitly, and every other tool call is denied.

**Living examples**

- R18. An agent with no tools turns a Pydantic input into a structured output.
- R21. Each example file opens with a header comment that carries the rules a copier needs, as the task and workflow examples do.

**Tests**

- R22. No automated test calls Claude, and a guard fails any test that tries.
- R23. Each agent has unit tests that run without Hatchet and without a sandbox, with the SDK replaced. Agent tasks and the session piece have unit tests with the agent and the sandbox replaced.

### Acceptance Examples

- AE3. **Covers R8.** **Given** an agent that reaches its turn limit, **when** its task finishes, **then** the run is marked failed without a retry, and its log holds the cost, turns and session ID.
- AE8. **Covers R22.** **Given** a unit test that runs an agent without replacing the SDK, **when** it runs, **then** the guard fails it before any request leaves.

### Scope Boundaries

Not in this part:

- No task, session piece or cgroup (U4).
- No integration test: the fake CLI runs in process, through the real SDK, only.

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- claude-agent-sdk 0.2.167 (2026-10-14, bundling CLI 2.1.300) ships only `manylinux_2_17` wheels, which `python:3.14.7-slim` satisfies, and bundles a native `claude` binary of about 250 MB. It releases almost daily. `query()` runs that engine as a subprocess over stdio, and `ClaudeAgentOptions.env` is merged over the inherited environment (`_internal/transport/subprocess_cli.py`), so only a sandbox that starts from an empty environment keeps the worker's variables out of the engine.
- The SDK's `ResultMessage` carries `subtype`, `is_error`, `structured_output`, `total_cost_usd`, `num_turns` and `session_id`. An error result is yielded, then raised as `ResultError`. An API failure arrives as `subtype="success"` with `is_error=True`. A Pydantic model's JSON Schema passed as `output_format` comes back in `structured_output` (Agent SDK Python reference and structured-outputs guide).
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
- KTD14. **Tests replace the SDK at the same seams, and the compose stack is the guard for the agent worker.**
  - **The pytest guard** in `tests/conftest.py` is unchanged. It removes the credential variables, points `ANTHROPIC_BASE_URL` at a closed port, and fails any unreplaced transport `connect`, except in `fake_cli` tests (R22, AE8).
  - **Unit seam.** `ScriptedQuery` replaces `query` on an agent's module and records the options (R23).
  - **Fake CLI.** `tests/agents/fake_claude.py` stays the engine stand-in. It gains a `fake:hog` scenario that allocates past its memory limit. It reports the environment names, the processes `/proc` lists, and whether its working directory is writable, all to stderr. In integration, the overlay bind-mounts it read-only into the agent worker and points `CORVO_AGENT_ENGINE` at it; `tests/agents/fake/Containerfile` goes.
  - **The out-of-process guard.** The agent worker in compose runs the real transport, outside pytest's guard. What keeps it from Claude is the test stack itself: no service holds a real credential, every upstream is `tests/agents/scripted_api.py`, and the `agents` network has no route out. A test asserts the scripted API received only the dummy credential. R31's real engine runs in that stack alone, so the pytest guard admits nothing new.

  Governs R22, R23, R24, R31.
- KTD17. **The examples are `tone`, `dir-summary` and `dir-review`, all on `claude-haiku-5-5`.**
  - **`tone`** (R18) has no tools, `max_turns=3` and `max_budget_usd=0.05`. It classifies a text as `friendly`, `neutral` or `unfriendly`, and its output adds `friendly: bool` from `corvo.core.agents.tone`.
  - **`dir-summary`** (R19) works in its directory read-only, with `Read`, `Glob`, `Grep` and the custom tool `count_words`, at `max_turns=15` and `max_budget_usd=0.25`. Its output is a summary and a word count.
  - `count_words` takes a text and never a path. Custom tools run in the agent worker's process, where a symlink in a working directory resolves against the worker's own files (R30). The tool is async and does no blocking work, because a blocked event loop starves the worker's heartbeats.
  - **`dir-review`** (R20) is a DAG on the main worker. Step `summarize` spawns `dir-summary`, and step `judge`, with parent `summarize`, spawns `tone` on the summary, both through stubs (KTD26). A core twin builds the review line.

  Governs R10, R18, R19, R20, R21, R30.

### Risks

- **SDK churn.** Releases come almost daily, and Dependabot bumps the lock weekly. The exact pin, the fake-CLI contract test and the failIfUnavailable assertion catch protocol drift. The integration gate catches a moved bundled binary. `docs/agents.md` asks for a new Haiku proof when the engine's minor version changes.

### Deferred to Implementation

- The fake CLI's canned outputs per schema title, and the exact `asyncio.timeout` of each integration test.

## Implementation Units

### U3. The `tone` agent on the session carrier, with the container pieces removed

- **Goal:** a contributor can copy an agent with no tools that turns a Pydantic input into a structured output, written against the `Session` the agent worker supplies.
- **Requirements:** R1, R3, R4, R8, R10, R11, R18, R21, R22, R23; KTD1, KTD3, KTD14, KTD17.
- **Dependencies:** U2.
- **Files:**
  - Create `src/corvo/core/agents/tone.py`, `tests/core/agents/__init__.py` and `tests/core/agents/test_tone.py`.
  - Create `src/corvo/agents/tone/__init__.py`, `models.py`, `agent.py` and `prompts/system.md`.
  - Create `src/corvo/agents/report.py` and `src/corvo/agents/session.py`.
  - Create `tests/agents/isolation.py`, `tests/agents/scripted.py`, `tests/agents/fake_claude.py`, `tests/agents/test_fake_claude_contract.py`, `tests/agents/test_session.py`, `tests/agents/tone/__init__.py` and `tests/agents/tone/test_agent.py`.
- **Approach:** this is #35 reworked on top of U2.
  1. Drop the commits that add `runner.py`, `frame.py`, `fingerprint.py`, the `agent` Dockerfile stage, the `corvo-agent` script and `tests/agents/fake/Containerfile`, with their tests.
  2. Rename `envelope.py` to `report.py`, trimmed per the Builds on table.
  3. Add `Session` and the sandbox settings to `session.py` per KTD1 and KTD3, and turn `consume`'s stderr line into its `log` callback.
  4. `tone/agent.py` passes the session's values next to its own options. Its header states the native-API rule, why each isolation option is there, the result rule, and that logic belongs in the core twin.
  5. Extend the isolation helper to both halves of KTD3, and to its refusal of `WebFetch` and `WebSearch`.
  6. The fake CLI gains `fake:hog` and its reports per KTD14.
- **Patterns to follow:** the existing tone agent, its tests and the fake CLI on the `feat/agents-u3-tone-agent` branch; `src/corvo/worker/tasks/hello.py` for headers.
- **Test scenarios:**
  - The core twin returns true for `friendly` and false for `neutral` and `unfriendly`.
  - With `query` replaced by a script yielding a success result whose structured output is `{"tone": "friendly"}`, `run` returns `ToneOutput(tone="friendly", friendly=True)` and a report with the script's cost, turns and session ID.
  - The options it built pass the isolation helper. They carry `tools == []`, `dontAsk`, no setting sources or skills, `strict_mcp_config`, the model, positive limits, and the session's `cli_path`, `cwd` and `env`. The sandbox has `failIfUnavailable` true and unsandboxed commands off, and `output_format` equals `ToneVerdict`'s schema.
  - The isolation helper rejects options whose `tools` include `WebFetch` or `WebSearch`.
  - Covers AE3. A scripted `error_max_turns` result followed by `ResultError` makes `run` raise `AgentRunFailed` carrying the subtype, turns, cost and session ID.
  - A `success` result with `is_error=True` is a failure. So is a `success` result without `structured_output`, and one whose structured output does not validate.
  - `consume` calls its `log` callback with the session ID when the init message arrives, before any result.
  - The fake CLI, run through the real SDK via `cli_path`, returns the canned structured output within the timeout. With `fake:max-turns` it returns an error result and `ResultError`. Its reported `--settings` holds `sandbox.failIfUnavailable: true`.
- **Verification:** the unit suite passes with the guard active, and no module named `runner`, `frame`, `fingerprint` or `envelope` remains under `src/corvo/agents/`.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/agents tests/core`: unit tests with the guard active, no Docker.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- No module named `runner`, `frame`, `fingerprint` or `envelope` remains under `src/corvo/agents/`, and no `agent` stage remains in the `Dockerfile`.
- `tone/agent.py` opens with R21's header.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u3-tone-agent`, on top of `feat/agents-u2-boundaries`, pull request #35, reworked. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
