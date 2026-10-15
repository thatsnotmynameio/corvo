---
title: Agents Skeleton U2 Agent Boundaries, Settings and Guard - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u2-boundaries
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U2 Agent Boundaries, Settings and Guard - Plan

## Goal Capsule

- **Objective:** The three agent areas exist, and the import rules, the no-Claude test guard and the agent settings are enforced before any agent exists.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 2 of 7. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** none (it sits above U1 in the stack). **Blocks:** U3 builds on this part directly; U4 to U7 through it.
- **Stop conditions:** stop and ask when the SDK, Hatchet or Podman behaves differently from this plan on the pinned versions, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U1: a rootless Podman fixture in `tests/integration/worker/`; this part does not use it.

## Product Contract

### Summary

Adds the pinned `claude-agent-sdk`, the empty `corvo.agents`, `corvo.core.agents` and `corvo.worker.agents` packages, the AST import-boundary test, the guard that fails any test reaching Claude, the agent settings, and the agents area in the registration test.

### Context

The boundary and the guard must hold before the first agent lands, so no agent can be written against them. R2 and R22 are completed here; R6 and R12 are completed by U4, which uses the area and the settings.

### Key Decisions

- **An agent is a Hatchet task that runs one agent session.** Workflows spawn it like any task. (session-settled: user-directed — chosen over an agent outside Hatchet that calls tasks as tools: both will exist, starting with this one.) Governs R6, R20.
- **Agent code lives in its own Hatchet-free package; the worker keeps only a thin task.** (session-settled: user-directed — chosen over an agents area inside `corvo.worker` that imports the SDK next to Hatchet.) Governs R1, R2, R6.
- **The Claude credential is either an API key or a subscription OAuth token, chosen per environment.** (session-settled: user-directed — chosen over an API key only and over a subscription token only.) Governs R12.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.

### Requirements

**Agent packages and boundaries**

- R2. Only `corvo.agents` imports `claude_agent_sdk`. `corvo.agents` imports neither Hatchet nor `corvo.worker`, and `corvo.core` imports neither `corvo.agents` nor the SDK. A check fails on each of these imports in every module, including `corvo.worker` and `corvo.server.api`, whose files ignore ruff's TID251 wholesale today.

**Hatchet integration**

- R6. Each agent has a thin Hatchet task in `corvo.worker.agents` with an explicit name and Pydantic input and output models. The task is registered in `WORKFLOWS`, and the registration test covers the area.

**Agent execution**

- R12. The Claude credential comes from corvo's settings, as an API key or a subscription OAuth token, and each environment chooses which.

**Tests**

- R22. No automated test calls Claude, and a guard fails any test that tries.

### Acceptance Examples

- AE2. **Covers R2.** **Given** a module outside `corvo.agents` that imports `claude_agent_sdk`, such as an agent task in `corvo.worker.agents`, or a module in `corvo.agents` that imports Hatchet, **when** the checks run, **then** they fail on that import.
- AE8. **Covers R22.** **Given** a unit test that runs an agent without replacing the SDK, **when** it runs, **then** the guard fails it before any request leaves.

### Scope Boundaries

- No agent, task or container code.

### Dependencies / Assumptions

- claude-agent-sdk 0.2.167 (2026-10-14, bundling CLI 2.1.300) ships only `manylinux_2_17` wheels, which `python:3.14.7-slim` satisfies, and bundles a native `claude` binary of about 250 MB. It releases almost daily.
- The subscription OAuth token is, by Anthropic's terms, for ordinary individual use by the subscriber. Products and services built on the Agent SDK must use API keys (`legal-and-compliance.md`; Agent SDK `overview.md`). A `claude setup-token` token lasts one year.

## Planning Contract

### Key Technical Decisions

- KTD2. **R2 is enforced by an AST test over `src/corvo`, not by ruff.** `tests/test_import_boundaries.py` parses every module and builds the import graph inside `corvo`. Importing `a.b.c` also counts its parent packages' `__init__` modules, which stay empty. The test fails, naming the module and the import, when:
  1. a module outside `corvo.agents` imports `claude_agent_sdk`;
  2. a module in `corvo.worker` imports, directly or transitively, a `corvo` module that imports `claude_agent_sdk`;
  3. a module in `corvo.agents` imports `hatchet_sdk` or `corvo.worker`;
  4. a module in `corvo.core` imports `corvo.agents` or `claude_agent_sdk`.

  The checks run as a pure function, fed by test-declared sources in the same test module, and once against the real tree, as `test_registration.py` does. Ruff cannot do it: per-file TID251 ignores drop every ban for `src/corvo/worker/**` and `src/corvo/server/api/**`, and CI's `ruff check --config=ruff.toml` ignores nested config files. `ruff.toml` stays unchanged. Governs R2.
- KTD10. **Before the worker starts serving, `main()` prepares agents in at most 45 seconds, and a failure only disables them.** When agents are configured (KTD12), it runs, in order:
  1. Check that the image is present.
  2. Run the probe: `corvo-agent probe` in a container built by KTD6's spec and attached as a run is, with no credential, no working directory and no request. It frames a report on its stdout, which the worker reads from the attach stream as it reads an envelope (KTD4; agent-request-stdin plan, KTD6):
     - the fingerprint;
     - `memory.max`, `cpu.max` and `pids.max` read inside the container;
     - the effective capabilities;
     - the environment variable names;
     - whether the root filesystem is read-only;
     - the flags of the `/tmp` and `/home/agent` mounts, read from `/proc/self/mounts`;
     - whether a one-second TCP connect reaches the container's default gateway and `169.254.169.254:80`.
  3. Compare the report with the spec and with the worker's own fingerprint. The probe step then force-removes its container by label, whatever the outcome.
  4. Sweep (KTD11).

  - **When a check fails.** A limit, a flag or a fingerprint that differs, or any error, disables agents, with the reason logged. Every other task keeps working.
  - **When egress is open.** A reachable gateway or metadata address means KTD16's nftables rule is missing. With `agent_require_egress_block` set (KTD12), it disables agents. Otherwise it logs a warning, which is the default for development and CI, which have no such rule.
  - **Recovery.** Agents stay disabled until the worker restarts. Agent runs fail at once with the logged reason, which is how the operator learns of it.
  - **The fingerprint.** It is a SHA-256 over the `*.py` files and `prompts/**` under `corvo/agents/` and `corvo/core/agents/`, sorted by relative path, with `__pycache__` and `*.pyc` excluded, plus the installed `claude-agent-sdk` version. `corvo.agents.fingerprint` computes it from the standard library alone, and each side computes it over its own installed copy. A stale agent image is therefore refused instead of running old code. The report comes from the image under test, so the fingerprint detects a stale image, not a tampered one (Risks).
  - **The cgroup check.** The probe is also R14's cgroup check: on cgroup v2, an undelegated controller makes the container fail to start.

  Governs R14, R15, R16.
- KTD12. **Agent settings are five `CORVO_AGENT_*` fields plus the credential, and an empty socket or root means "agents not configured".**
  - The fields are `agent_podman_socket`, `agent_root`, `agent_image` (default `localhost/corvo-agent:latest`), `agent_credential_kind: Literal["api_key", "oauth_token"]` and `agent_require_egress_block: bool = False` (KTD10), plus `agent_credential`.
  - They are plain `str`, as `settings.py` holds its other secrets.
  - With the socket or the root empty, an agent task fails at once with "agents are not configured", and `main()` skips KTD10.
  - An empty credential while the rest is configured disables agents in KTD10.
  - The container receives the credential as `ANTHROPIC_API_KEY` or as `CLAUDE_CODE_OAUTH_TOKEN`, never both.
  - The settings comment and `docs/agents.md` carry the OAuth terms (Dependencies).

  Governs R12, R14.
- KTD13. **The agent image is an `agent` stage of the repository's `Dockerfile`, and the SDK is an exact-pinned runtime dependency.**
  - The existing stage is named `app`. The `agent` stage builds from it, and sets `WORKDIR /workspace` (empty in the image), `HOME=/home/agent` and `ENTRYPOINT ["corvo-agent"]`.
  - The file ends with a closing `FROM app`. A build without `--target`, which is what compose's `build: .` runs, still produces today's app image, so `compose.yaml` stays unchanged.
  - The operator builds the agent image into the dedicated user's store with `podman build --target agent`.
  - `claude-agent-sdk==0.2.167` sits in `[project].dependencies`, so the app image carries it too. A dependency group kept out of the app image fails in CI, whose fixed `uv run` installs only the default groups. KTD2 already keeps the worker from importing it.
  - `docker` joins the runtime dependencies and `types-docker` the dev group.

  Governs R13, R17.
- KTD14. **Tests replace the SDK at three seams, and a guard stops everything else.**
  - **The guard.** `tests/conftest.py` removes `ANTHROPIC_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN`, and sets `ANTHROPIC_BASE_URL=http://127.0.0.1:9`. An autouse fixture replaces the SDK's subprocess transport `connect` with a failure that names the test. A marker opts out the fake-CLI contract test only. Governs R22, AE8.
  - **Unit seam.** An agent's tests replace `query` on the agent module with a scripted async generator that yields real `ResultMessage` objects, and they record the options it received (R23).
  - **Fake CLI.** `tests/agents/fake_claude.py` is a stand-in for the `claude` binary, after the SDK's own `tests/test_run_end_subprocess.py`:
    - It answers `-v`, replies to each `control_request`, drives custom tools through `mcp_message`, and emits a `result`.
    - It picks its scenario from markers in the prompt: success by default, `fake:max-turns`, `fake:api-error` or `fake:hang`.
    - It returns a canned structured output chosen by the JSON Schema's title.
    - It prints its argv and the isolation variables it saw to stderr.
  - **Contract test.** An in-process test runs the fake through the real SDK via `cli_path`, under a 20-second `asyncio.timeout`. A protocol change in an SDK bump then fails fast instead of hanging.
  - **Test image.** `tests/agents/fake/Containerfile` builds `FROM` the agent image, with only the fake in its build context. It overwrites the SDK's bundled `claude`, at a path found at build time, then asserts at build that `claude -v` prints the fake's version. It sets `ANTHROPIC_BASE_URL` to an unreachable address, so a missed overwrite cannot reach Claude.

  Governs R22, R23, R24.

## Implementation Units

### U2. Agent boundaries, settings and the guard

- **Goal:** the three agent areas exist and are empty. The import rules, the no-Claude guard and the agent settings are enforced before any agent exists.
- **Requirements:** R2, R6, R12, R22, AE2, AE8; KTD2, KTD12, KTD13, KTD14.
- **Dependencies:** none.
- **Files:**
  - Modify `pyproject.toml` and `uv.lock` (`claude-agent-sdk==0.2.167`).
  - Create `src/corvo/agents/__init__.py`, `src/corvo/core/agents/__init__.py` and `src/corvo/worker/agents/__init__.py`.
  - Modify `src/corvo/settings.py` and `tests/test_settings.py`.
  - Create `tests/test_import_boundaries.py`.
  - Modify `tests/conftest.py` (guard).
  - Create `tests/agents/__init__.py` and `tests/agents/test_guard.py`.
  - Modify `tests/worker/test_registration.py` (add `corvo.worker.agents` to `AREAS`, docstring), `src/corvo/worker/worker.py` (comment) and `tests/worker/test_worker.py` (comment).
- **Approach:**
  1. Add the settings fields of KTD12, each with a one-line comment. The OAuth comment carries the terms.
  2. Write the boundary checker of KTD2 as a pure function over a mapping of module name to source, and test it with declared sources and once over `src/corvo`.
  3. Add the guard of KTD14 to `tests/conftest.py`, next to the existing token shim, in the same comment style.
  4. Extend the registration test's areas.
- **Patterns to follow:** `tests/worker/test_registration.py` (a pure checker plus a real-tree test); `src/corvo/settings.py` field style.
- **Test scenarios:**
  - Covers AE2. A declared module `corvo.worker.agents.x` importing `claude_agent_sdk` yields a problem naming it.
  - Covers AE2. A declared `corvo.agents.x.agent` importing `hatchet_sdk` yields a problem, and so does one importing `corvo.worker.defaults`.
  - A declared `corvo.worker.agents.x` importing `corvo.agents.x.models`, where `models` imports only Pydantic, yields none.
  - The same import, where `models` imports `corvo.agents.x.agent`, which imports the SDK, yields a transitive problem naming the chain.
  - A declared `corvo.core.agents.x` importing `corvo.agents` yields a problem.
  - The real tree yields no problems.
  - Covers AE8. A test that calls `claude_agent_sdk.query` with a trivial prompt, with nothing replaced, fails with the guard's message, and no subprocess starts.
  - Settings read `CORVO_AGENT_CREDENTIAL_KIND=oauth_token` and reject `token`.
  - With no agent variables set, the settings report agents as not configured.
- **Verification:** the unit suite and `prek` pass. Adding `import claude_agent_sdk` to `src/corvo/worker/worker.py` fails the boundary test by name.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict with `types-docker`, lockfile.
- `uv run pytest tests/test_import_boundaries.py tests/test_settings.py tests/agents tests/core tests/worker`: unit tests, no Docker or Podman.

## Definition of Done

- Every gate above passes locally and in CI.
- U2 when adding `import claude_agent_sdk` to `src/corvo/worker/worker.py` fails the boundary test by name.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-podman-fixture` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-container-piece` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u2-boundaries`, on top of `feat/agents-u1-podman-fixture`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
