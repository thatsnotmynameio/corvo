---
title: Agents Skeleton U2 Agent Boundaries, Settings, Guard and Worker Profiles - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u2-boundaries
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U2 Agent Boundaries, Settings, Guard and Worker Profiles - Plan

## Goal Capsule

- **Objective:** The import rules, the settings and the no-Claude guard hold for the profile shape before any agent exists. `corvo-worker` serves the profile it is given, and the `agents` profile's empty list is registered and tested.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 2 of 9 in stack order (unit U2). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U1; it sits on `feat/agents-u1-isolation-gate` in the stack. **Blocks:** U3 builds on this part directly; U4 to U7 through it.
- **Stop conditions:** stop and ask when the SDK or Hatchet behaves differently from this plan on the pinned versions, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U1: the SDK pin, the Linux-only lock, and `corvo.worker.agent_runtime.sandbox`, which KTD2's fifth rule holds to the standard library.
- #34's code on `feat/agents-u2-boundaries`, reworked on top of U1:
  - 5ee4c09 keeps only the three empty agent areas; its pin moved to U1.
  - b3bc08e (settings) is trimmed and extended per KTD12, and gains `worker_profile`.
  - b0ea5b6, 9603eed and 71f9efc (the boundary test) keep their pure checker and fixtures; the fourth rule is narrowed and the fifth added.
  - 1cfec79 and a896c65 (the guard) stay as they are. 1698f6c (Trunk's `corvo-agents` collection) is dropped: U1 adds the same entry.
  - e36a843 (the registration test) becomes the walk over `PROFILES`.
- On `main`: `src/corvo/worker/worker.py`'s `WORKFLOWS`, `create_worker()` and `main()`, whose list moves to the `main` profile.

## Product Contract

### Summary

Adds the three empty agent areas, the AST import-boundary test with its rules for the profile shape, the agent settings of the bubblewrap design, the no-Claude guard, and the worker's permission profiles: `corvo.worker.profiles` with its `main` and `agents` profiles, the `main()` that serves the one `CORVO_WORKER_PROFILE` names, and the registration test that walks them.

### Context

The boundary and the guard must hold before the first agent lands, so no agent can be written against them. The profiles replace a second worker module (KTD26, owner-directed): what differs between the main worker and the agent worker is configuration, so one `corvo-worker` serves either. R2 and R22 are completed here; R6, R12 and R13 are completed by U4, U5 and U9, which register agents, hand the credential to the proxy and start the agent worker. #37 builds on this part's profiles for `CORVO_WORKER_NAME` and the compose test.

### Key Decisions

- **An agent is a Hatchet task that runs one agent session.** Workflows spawn it like any task. (session-settled: user-directed — chosen over an agent outside Hatchet that calls tasks as tools: both will exist, starting with this one.) Governs R6, R20.
- **Agent code lives in its own Hatchet-free package; the worker keeps only a thin task.** (session-settled: user-directed — chosen over an agents area inside `corvo.worker` that imports the SDK next to Hatchet.) Governs R1, R2, R6.
- **The agent worker is a compose service of its own.** (session-settled: user-approved — chosen over a systemd service on the host: it keeps one deploy path and the Hatchet engine's gRPC internal, at the cost of R27's container settings and a profile kept in step with Docker's.) Governs R13, R27.
- **The Claude credential lives in a proxy and the agent worker's egress is cut, from the first run.** Without both, a session that reads its own engine's credential could send it out. (session-settled: user-approved — chosen over deferring the proxy and `--network none`, as the Podman design did.) Governs R12, R16.
- **The Claude credential is either an API key or a subscription OAuth token, chosen per environment.** (session-settled: user-directed — chosen over an API key only and over a subscription token only.) Governs R12.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.

### Requirements

**Agent packages and boundaries**

- R2. Only `corvo.agents` imports `claude_agent_sdk`. `corvo.agents` imports neither Hatchet nor `corvo.worker`, and `corvo.core` imports neither `corvo.agents` nor the SDK. A check fails on each of these imports in every module, including `corvo.worker` and `corvo.server.api`, whose files ignore ruff's TID251 wholesale today.

**Hatchet integration**

- R6. Each agent has a thin Hatchet task in `corvo.worker.agents` with an explicit name and Pydantic input and output models. Agent tasks are registered only in the agent worker's list, which holds nothing else, and the registration test covers both workers.

**Agent execution**

- R12. The Claude credential is set in the deployment's environment, as an API key or a subscription OAuth token, and each environment chooses which. Only the proxy of R16 receives it; corvo's settings hold only which kind it is.

**Isolation**

- R13. Agent tasks run only on a dedicated agent worker, which holds the Hatchet token but neither the database password nor the Claude credential.

**Tests**

- R22. No automated test calls Claude, and a guard fails any test that tries.

### Acceptance Examples

- AE2. **Covers R2.** **Given** a module outside `corvo.agents` that imports `claude_agent_sdk`, such as an agent task in `corvo.worker.agents`, or a module in `corvo.agents` that imports Hatchet, **when** the checks run, **then** they fail on that import.
- AE8. **Covers R22.** **Given** a unit test that runs an agent without replacing the SDK, **when** it runs, **then** the guard fails it before any request leaves.

### Scope Boundaries

Not in this part:

- No agent, task or session piece (U3, U4).
- No `before_start` or `on_sigterm` for the `agents` profile (U9); `serve` runs them when a profile has them.
- No `CORVO_WORKER_NAME` and no compose test (#37).

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- Hatchet API tokens are scoped per tenant, with no per-worker or narrower token (Hatchet security docs). A task goes only to workers that registered it, and worker labels attract tasks without keeping others away (Hatchet worker and worker-affinity docs). In hatchet-sdk 1.42.1, `DesiredWorkerLabel.required` defaults to `False` (`hatchet_sdk/types/labels.py:69`), so isolation by registration is the only exclusion this plan relies on.
- claude-agent-sdk 0.2.167 (2026-10-14, bundling CLI 2.1.300) ships only `manylinux_2_17` wheels, which `python:3.14.7-slim` satisfies, and bundles a native `claude` binary of about 250 MB. It releases almost daily. `query()` runs that engine as a subprocess over stdio, and `ClaudeAgentOptions.env` is merged over the inherited environment (`_internal/transport/subprocess_cli.py`), so only a sandbox that starts from an empty environment keeps the worker's variables out of the engine.
- The subscription OAuth token is, by Anthropic's terms, for ordinary individual use by the subscriber. Products and services built on the Agent SDK must use API keys (`legal-and-compliance.md`; Agent SDK `overview.md`). A `claude setup-token` token lasts one year.

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD2. **R2 stays an AST test over `src/corvo`, with its transitive rule narrowed to the main profile.** Three rules stay: no module outside `corvo.agents` imports `claude_agent_sdk`; `corvo.agents` imports neither `hatchet_sdk` nor `corvo.worker`; `corvo.core` imports neither `corvo.agents` nor the SDK. The fourth rule now reads: no module the main profile imports reaches a module that imports the SDK. The main profile means `corvo.worker.worker`, `corvo.worker.profiles`, `corvo.worker.profiles.main`, `corvo.worker.tasks`, `corvo.worker.workflows`, `corvo.worker.agent_calls` and everything they import (KTD26); `corvo.server`, which will trigger agents through the same stubs, is held to the same rule. `corvo.worker.agents`, `corvo.worker.agent_runtime` and `corvo.worker.profiles.agents` reach the SDK through `corvo.agents`, and never import it themselves. A fifth rule keeps `corvo.worker.agent_runtime.sandbox`, and anything it imports, to the standard library: it runs as the wrapper process before it has joined its cgroup (KTD20). Governs R2, R6.
- KTD12. **Agent settings are `CORVO_AGENT_*` fields for the root, the kind, the proxy, the cgroup root and the engine.**
  - Removed: `agent_podman_socket`, `agent_image`, `agent_require_egress_block` and `agent_credential`. The credential moves to the proxy's environment (R12).
  - Kept: `agent_root` and `agent_credential_kind: Literal["api_key", "oauth_token"]`.
  - Added: `agent_proxy_url` (the sessions' `ANTHROPIC_BASE_URL`), `agent_cgroup_root` (default `/sys/fs/cgroup/agents`) and `agent_engine`, the engine's path. The `agent-worker` image sets it to the engine KTD13 moved; the integration overlay points it at the fake CLI, and KTD10 logs it at start.
  - Each session gets a fixed placeholder as `ANTHROPIC_API_KEY` for `api_key`, or as `CLAUDE_CODE_OAUTH_TOKEN` for `oauth_token`, never both. The engine then sends `x-api-key` or `Authorization: Bearer`, which the proxy replaces (KTD22).
  - The settings comment and `docs/agents.md` carry the OAuth terms (Dependencies).

  Governs R12, R13.
- KTD14. **Tests replace the SDK at the same seams, and the compose stack is the guard for the agent worker.**
  - **The pytest guard** in `tests/conftest.py` is unchanged. It removes the credential variables, points `ANTHROPIC_BASE_URL` at a closed port, and fails any unreplaced transport `connect`, except in `fake_cli` tests (R22, AE8).
  - **Unit seam.** `ScriptedQuery` replaces `query` on an agent's module and records the options (R23).
  - **Fake CLI.** `tests/agents/fake_claude.py` stays the engine stand-in. It gains a `fake:hog` scenario that allocates past its memory limit. It reports the environment names, the processes `/proc` lists, and whether its working directory is writable, all to stderr. In integration, the overlay bind-mounts it read-only into the agent worker and points `CORVO_AGENT_ENGINE` at it; `tests/agents/fake/Containerfile` goes.
  - **The out-of-process guard.** The agent worker in compose runs the real transport, outside pytest's guard. What keeps it from Claude is the test stack itself: no service holds a real credential, every upstream is `tests/agents/scripted_api.py`, and the `agents` network has no route out. A test asserts the scripted API received only the dummy credential. R31's real engine runs in that stack alone, so the pytest guard admits nothing new.

  Governs R22, R23, R24, R31.
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

## Implementation Units

### U2. Agent boundaries, settings, the guard and the worker's profiles

- **Goal:** the import rules, the settings and the no-Claude guard hold for the profile shape before any agent exists. `corvo-worker` serves the profile it is given, and the `agents` profile's empty list is registered and tested.
- **Requirements:** R2, R6, R12, R13, R22; AE2, AE8; KTD2, KTD12, KTD14, KTD26.
- **Dependencies:** U1.
- **Files:**
  - Create `src/corvo/agents/__init__.py`, `src/corvo/core/agents/__init__.py` and `src/corvo/worker/agents/__init__.py`.
  - Create `src/corvo/worker/profiles/__init__.py`, `src/corvo/worker/profiles/main.py`, `src/corvo/worker/profiles/agents.py` and `tests/worker/test_profiles.py`.
  - Modify `src/corvo/worker/worker.py` and `tests/worker/test_worker.py`.
  - Modify `src/corvo/settings.py` and `tests/test_settings.py`.
  - Create `tests/test_import_boundaries.py` and `tests/agents/test_guard.py`.
  - Modify `tests/worker/test_registration.py`.
- **Approach:** this is #34 reworked on top of U1, without its SDK pin, which U1 now holds.
  1. Narrow the boundary test's fourth rule and add the fifth per KTD2, keeping its pure checker and its fixtures for the other rules.
  2. Trim and extend the settings per KTD12, and add `worker_profile` per KTD26.
  3. Keep the guard as it is.
  4. `corvo.worker.profiles` per KTD26. `main` takes today's `WORKFLOWS`. `agents` holds an empty list, its name and its slots; its hooks come in U9. `corvo.worker.worker.main()` resolves the profile and calls `serve`.
  5. The registration test walks `PROFILES` per KTD26.
- **Patterns to follow:** the existing `tests/worker/test_registration.py` and `tests/worker/test_worker.py`; `src/corvo/settings.py` field style.
- **Test scenarios:**
  - Covers AE2. A declared `corvo.worker.agents.x` importing `claude_agent_sdk` directly yields a problem naming it.
  - Covers AE2. A declared `corvo.agents.x.agent` importing `hatchet_sdk` yields a problem, and so does one importing `corvo.worker.defaults`.
  - A declared `corvo.worker.workflows.x` importing `corvo.worker.agents.y`, which imports an agent that imports the SDK, yields a transitive problem naming the chain. The same chain from `corvo.server.api.x` does too.
  - The same chain from `corvo.worker.agents.y` itself yields none.
  - A declared `corvo.worker.agent_calls` importing `corvo.agents.x.models`, which imports only Pydantic, yields none.
  - A declared `corvo.worker.agent_runtime.sandbox` importing `corvo.worker.defaults` yields a problem.
  - The real tree yields no problems.
  - Covers AE8. A test that calls `claude_agent_sdk.query` unreplaced fails with the guard's message, and no subprocess starts.
  - Settings read `CORVO_AGENT_CREDENTIAL_KIND=oauth_token` and reject `token`. They default the cgroup root to `/sys/fs/cgroup/agents`, and no longer accept a credential field.
  - A definition listed on both the `main` and the `agents` profile fails the registration test, and so does a name shared across the two lists.
  - Every name in `PROFILES` imports a module whose `PROFILE` is a `Profile`, and importing `corvo.worker.profiles` imports no profile module.
  - `main()` with `CORVO_WORKER_PROFILE` unset serves `main` as `corvo-worker` with every task and workflow. With `agents`, it serves `corvo-agent-worker` with the `agents` list and the cap's slots. With an unknown name, it exits with status 1, naming `main` and `agents`, before a Hatchet worker exists.
  - `serve` runs `before_start` before creating the Hatchet worker, and installs `on_sigterm` after it. A profile without hooks starts the same as today's worker.
- **Verification:** the unit suite and `prek` pass. Adding `import claude_agent_sdk` to `src/corvo/worker/worker.py` fails the boundary test by name, and so does importing `corvo.worker.profiles.agents` from it.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/test_import_boundaries.py tests/test_settings.py tests/agents tests/core tests/worker`: unit tests, no Docker.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- Adding `import claude_agent_sdk` to `src/corvo/worker/worker.py` fails the boundary test by name, and so does importing `corvo.worker.profiles.agents` from it.
- `corvo-worker` with no profile set starts exactly as today's worker.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u2-boundaries`, on top of `feat/agents-u1-isolation-gate`, pull request #34, reworked. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
