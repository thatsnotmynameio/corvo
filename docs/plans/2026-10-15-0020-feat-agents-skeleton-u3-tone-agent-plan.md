---
title: Agents Skeleton U3 Tone Agent, Entrypoint and Fake CLI - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u3-tone-agent
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U3 Tone Agent, Entrypoint and Fake CLI - Plan

## Goal Capsule

- **Objective:** A contributor can copy an agent with no tools that turns a Pydantic input into a structured output, and the image that runs it and the fake CLI that replaces Claude exist.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 3 of 7. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** U2. **Blocks:** U4 builds on this part directly; U5 to U7 through it.
- **Stop conditions:** stop and ask when the SDK, Hatchet or Podman behaves differently from this plan on the pinned versions, or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U2: the empty agent packages, the pinned SDK, the boundary test, the no-Claude guard in `tests/conftest.py`, and the `CORVO_AGENT_*` settings.

## Product Contract

### Summary

Adds the `tone` agent package and its core twin, the container entrypoint `corvo-agent` with its envelope, session helper and fingerprint, the `agent` stage of the `Dockerfile`, and the fake `claude` CLI with its contract test and test image.

### Context

This is the first agent and the code that runs inside every agent container. R18 is completed by U4, when `tone` runs end to end; R1, R3, R4, R10, R11, R21 and R23 are built here for `tone` and completed by U6 and U7.

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
- R23. Each agent has unit tests that run without Hatchet and without a container, with the SDK replaced. Agent tasks and the container piece have unit tests with the agent and the container client replaced.

### Scope Boundaries

- No Hatchet task and no container start: U4 runs `tone` in a container.

### Dependencies / Assumptions

- claude-agent-sdk 0.2.167 (2026-10-14, bundling CLI 2.1.300) ships only `manylinux_2_17` wheels, which `python:3.14.7-slim` satisfies, and bundles a native `claude` binary of about 250 MB. It releases almost daily.
- The SDK's `ResultMessage` carries `subtype`, `is_error`, `structured_output`, `total_cost_usd`, `num_turns` and `session_id`. An error result is yielded, then raised as `ResultError`. An API failure arrives as `subtype="success"` with `is_error=True`. A Pydantic model's JSON Schema passed as `output_format` comes back in `structured_output` (Agent SDK Python reference and structured-outputs guide).
- `allowed_tools` with `permission_mode="dontAsk"` still lets read-only Bash, the Agent tool and reads inside the working directory run. Restricting the tool set takes the `tools` option (Agent SDK `permissions.md`).
- uv_build packages every file under `src/corvo/`, so `prompts/*.md` reaches the wheel with no configuration (checked by building one). `.dockerignore` excludes `tests/`.

## Planning Contract

### Key Technical Decisions

- KTD1. **An agent package exposes one coroutine, `run`, in `agent.py`, and keeps everything the worker reads in `models.py`.**
  - `run` takes the agent's input model and its working directory (`None` for an agent without one). It returns its output model together with a `RunReport`: the subtype, turns, cost and session ID.
  - A failed session raises `AgentRunFailed`, which carries the same report. Both types live in `corvo.agents.envelope`, which imports only Pydantic.
  - Inside, `run` builds `ClaudeAgentOptions` and calls `query()` itself, with the SDK's own names (R4). It hands the iterator `query()` returned to `corvo.agents.session.consume`, which applies KTD4's result rule and returns the structured output and the report, or raises. The helper consumes the SDK's stream, and does not wrap or replace any of its calls.
  - `models.py` holds the input model, the model whose JSON Schema becomes `output_format`, the output model, and a `WRITES_WORKDIR` flag. It imports only Pydantic and the standard library.
  - The worker imports `models.py` and the SDK-free shared modules `envelope` and `fingerprint`, never `agent.py`, `tools.py` or `session.py`.

  The container's entrypoint, `corvo-agent` (`corvo.agents.runner`), imports `corvo.agents.<package>.agent`, validates the request's input with the input model, awaits `run`, and writes the envelope from what `run` returned or raised. The entrypoint sits outside the agent, not between the agent and the SDK. The agent's output model wraps the session's structured output and any field its core twin derives from it (R3). Governs R1, R3, R4, R8, R17.
- KTD2. **R2 is enforced by an AST test over `src/corvo`, not by ruff.** `tests/test_import_boundaries.py` parses every module and builds the import graph inside `corvo`. Importing `a.b.c` also counts its parent packages' `__init__` modules, which stay empty. The test fails, naming the module and the import, when:
  1. a module outside `corvo.agents` imports `claude_agent_sdk`;
  2. a module in `corvo.worker` imports, directly or transitively, a `corvo` module that imports `claude_agent_sdk`;
  3. a module in `corvo.agents` imports `hatchet_sdk` or `corvo.worker`;
  4. a module in `corvo.core` imports `corvo.agents` or `claude_agent_sdk`.

  The checks run as a pure function, fed by test-declared sources in the same test module, and once against the real tree, as `test_registration.py` does. Ruff cannot do it: per-file TID251 ignores drop every ban for `src/corvo/worker/**` and `src/corvo/server/api/**`, and CI's `ruff check --config=ruff.toml` ignores nested config files. `ruff.toml` stays unchanged. Governs R2.
- KTD3. **Each agent sets the isolation options itself, and the container piece sets the isolation environment.**
  - Every agent passes `tools=[…]` (its built-ins, `[]` for none), `allowed_tools` (its file tools as rules scoped to `/workspace`, its other built-ins by name, and its `mcp__<server>__<tool>` names), `permission_mode="dontAsk"`, `setting_sources=[]`, `skills=[]` and `strict_mcp_config=True`, with `model`, `max_turns` and `max_budget_usd` (R10).
  - The container piece sets `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`, `HOME=/home/agent` and `CLAUDE_CONFIG_DIR=/home/agent/.claude`, both on the home tmpfs.
  - A test helper in `tests/agents/` asserts the isolation fields on the options an agent built. Every agent's unit test calls it, which keeps a corvo options builder out of the runtime code (R4).

  Governs R10, R11.
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
- KTD6. **One function builds the container spec, used by every run and by the startup probe.**
  - Hardening: `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]` with Podman's default seccomp, `read_only=True` and `init=True`.
  - tmpfs through docker-py's `tmpfs=` mapping (a tmpfs `Mount` gets mode 0 on Podman):
    - `/tmp` as `rw,noexec,nosuid,nodev,size=100m`;
    - `/home/agent` as `rw,noexec,nosuid,nodev,size=500m`.

    These are the flags of Anthropic's hardened example. If the first proof that runs `Glob` or `Grep` (`dir-summary`'s, in U6) shows the bundled CLI needs an executable temp directory, the fallback is a third tmpfs, `/home/agent-exec` (`rw,nosuid,nodev,size=200m`, no `noexec`), with `CLAUDE_CODE_TMPDIR` pointing at it.
  - Limits: `AGENT_MEMORY` with swap equal to it, `AGENT_NANO_CPUS` and `AGENT_PIDS_LIMIT`.
  - Mounts: the working directory at `/workspace`, read-only unless `WRITES_WORKDIR`, when the run has one, and nothing else. The request and the envelope travel over the attach stream (KTD4), so no run directory is mounted (agent-request-stdin plan, KTD6).

    A run without a working directory gets no `/workspace` mount, and its session runs in the image's empty `/workspace`.
  - Streams: stdin is open without a tty, and the log driver is `none`, so no envelope is copied into the host's journal (agent-request-stdin plan, KTD6).
  - Naming: the container is named `corvo-agent-<task_run_id>-<retry_count>`, and its labels are `corvo.managed=true`, `corvo.deployment`, `corvo.run_id` (the workflow run), `corvo.task_run_id`, `corvo.attempt` and `corvo.agent`.
  - Network: the compat API's default.
  - Environment: KTD3's isolation variables, plus exactly one credential variable when the spec is given a credential. The probe is given none.

  Governs R13, R15, R16.
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
- KTD11. **The sweep removes containers of this deployment whose run has ended.**
  - The deployment label is `<tenant_id>@<server_url>`, taken from `hatchet.config` once at start.
  - It lists containers by the positive filters `label=corvo.managed=true` and `label=corvo.deployment=<id>`. Podman 6 changed negative label filters.
  - It reads each run's status once, bounded to 5 seconds, through the REST client under `hatchet.runs`. It bypasses the SDK's `get_status` wrapper, whose tenacity policy retries a 404 five times, about 15 seconds per container.
  - It removes a container only on `COMPLETED`, `FAILED` or `CANCELLED` (R16).
  - It keeps a container whose run is not found or whose lookup timed out, and logs it as a warning for the operator. A 404 does not prove the run ended: it can come from Hatchet's read model, which fills asynchronously, or from another stack on the same quickstart tenant.
  - The sweep's total is bounded to 20 seconds, inside KTD10's budget.
  - Probe containers are not the sweep's: the probe step force-removes its own container by label when it ends (KTD10).
  - The REST call needs the dashboard's address. The compose overlay sets `HATCHET_CLIENT_SERVER_URL` for the worker, because the token's `localhost:8080` points at the worker itself inside its container.

  Governs R16.
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
- KTD16. **Agent containers keep the default rootless network.** This instantiates the Key Decision on egress and inherits its label. (session-settled: user-approved — chosen over building the credential proxy now.) Conflict call-out: research found that the default network reaches more than the internet. It reaches the LAN, the cloud metadata endpoint and the compose stack's bridge addresses, through sockets the dedicated user opens on the host. Postgres and Hatchet still need credentials the container does not hold. The decision stands for these examples. `docs/agents.md` adds an owner-matched nftables rule as a production provisioning step: it drops the dedicated user's traffic to private, link-local and loopback ranges, with DNS allowed first. Every manual proof records what the container reached. Governs R15.
- KTD17. **The examples are `tone`, `dir-summary` and `dir-review`, all on `claude-haiku-5-5`.**
  - **`tone`** (R18) has no tools, `max_turns=3` and `max_budget_usd=0.05`. Its session classifies a text as `friendly`, `neutral` or `unfriendly`. Its output adds `friendly: bool` from `corvo.core.agents.tone`.
  - **`dir-summary`** (R19) mounts its working directory read-only. It uses `Read`, `Glob`, `Grep` and the custom tool `count_words`, whose logic is `corvo.core.agents.dir_summary.count_words`, with `max_turns=15` and `max_budget_usd=0.25`. Its output is a summary and a word count.
  - **`dir-review`** (R20) is a DAG. Step `summarize` spawns `dir-summary`, and step `judge`, with parent `summarize`, spawns `tone` on the summary. A core twin builds the review line from both outputs.
  - A task whose agent works in a directory declares its own input model in the worker module: the agent's input plus `workdir`. The agent receives `/workspace`.

  Governs R10, R18, R19, R20, R21.

## Implementation Units

### U3. The `tone` agent, the container entrypoint and the fake CLI

- **Goal:** a contributor can copy an agent with no tools that turns a Pydantic input into a structured output. The image that runs it exists, and so does the fake CLI that replaces Claude.
- **Requirements:** R1, R3, R4, R8, R10, R11, R18, R21, R22, R23; KTD1, KTD3, KTD4, KTD13, KTD14, KTD17.
- **Dependencies:** U2.
- **Files:**
  - Create `src/corvo/core/agents/tone.py` and `tests/core/agents/__init__.py`, `tests/core/agents/test_tone.py`.
  - Create `src/corvo/agents/tone/__init__.py`, `models.py`, `agent.py` and `prompts/system.md`.
  - Create `src/corvo/agents/envelope.py`, `src/corvo/agents/fingerprint.py`, `src/corvo/agents/session.py` and `src/corvo/agents/runner.py`.
  - Modify `pyproject.toml` (`corvo-agent` script).
  - Modify `Dockerfile` (`agent` stage).
  - Create `tests/agents/isolation.py`, `tests/agents/fake_claude.py`, `tests/agents/fake/Containerfile` and `tests/agents/test_fake_claude_contract.py`.
  - Create `tests/agents/test_runner.py`, `tests/agents/test_envelope.py`, `tests/agents/test_session.py`, `tests/agents/tone/__init__.py` and `tests/agents/tone/test_agent.py`.
- **Approach:**
  1. The core twin decides `friendly` from the tone label over plain `str` (R3).
  2. `models.py` holds `ToneInput` (text, bounded length), `ToneVerdict` (the schema the session returns), `ToneOutput` and `WRITES_WORKDIR = False`.
  3. `agent.py` reads `prompts/system.md` through `importlib.resources`, builds the options of KTD3 and KTD17, and runs `query()` with KTD4's result rule. It returns `ToneOutput` built with the core twin.
  4. `session.py` holds `consume` (KTD1, KTD4: the result rule and the session-ID line). `envelope.py` holds the envelope, `RunReport` and `AgentRunFailed`.
  5. `runner.py` implements `corvo-agent run` (KTD4: request, budget, envelope) and `corvo-agent probe` (KTD10's report). `fingerprint.py` and `envelope.py` import only the standard library and Pydantic.
  6. The `agent` stage and the named `app` stage per KTD13.
  7. The fake CLI and its contract test per KTD14. The test image's `Containerfile` lands here, and U4 builds it in integration.
  8. Header comments per R21. `agent.py` states the native-API rule, the isolation options with why each is there, the result rule, and that logic belongs in the core twin. `models.py` states that it must not import the SDK.
- **Patterns to follow:** `src/corvo/worker/tasks/hello.py` and its core twin for header and shell-over-core; the SDK's `tests/test_run_end_subprocess.py` for the fake.
- **Test scenarios:**
  - The core twin returns true for `friendly` and false for `neutral` and `unfriendly`.
  - With `query` replaced by a script yielding a success result whose structured output is `{"tone": "friendly"}`, `run` returns `ToneOutput(tone="friendly", friendly=True)`.
  - The options it built pass the isolation helper: `tools == []`, `permission_mode == "dontAsk"`, `setting_sources == []`, `skills == []`, `strict_mcp_config`, the model, and positive `max_turns` and `max_budget_usd`. Their `output_format` schema equals `ToneVerdict`'s.
  - Covers AE3. A scripted `error_max_turns` result followed by `ResultError` makes `run` raise a failure that carries the subtype, turns, cost and session ID.
  - A `success` result with `is_error=True` is a failure.
  - A `success` result without `structured_output` is a failure, and so is one whose structured output does not validate.
  - The runner, with the agent's `run` replaced by one returning an output and a `RunReport`, writes an `ok` envelope with both.
  - With `run` raising `AgentRunFailed`, the runner writes a `failed` envelope with the reason and the report.
  - When the budget runs out, the runner writes a `failed` envelope naming `deadline`.
  - Each envelope is framed on the runner's private stdout, and anything else printed to fd 1 goes to stderr, not into the frame (agent-request-stdin plan, KTD6).
  - The runner rejects a request naming a package that does not exist under `corvo.agents`, with a `failed` envelope.
  - `corvo-agent probe` frames a report on its stdout with the fingerprint and the cgroup values it read, from a fake `/sys` root passed in the test.
  - Two fingerprints over the same files are equal, and changing one byte of a prompt changes it.
  - A stray `__pycache__/x.pyc` under `corvo/agents/` leaves the fingerprint unchanged.
  - The fake CLI run through the real SDK via `cli_path` returns a `ResultMessage` with the canned structured output within the timeout, and with `fake:max-turns`, an error result and `ResultError`.
- **Verification:** the unit suite passes with the SDK guard active. `docker build --target agent .` builds the image, and `podman build` of `tests/agents/fake/Containerfile` on it passes its `claude -v` assertion.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict with `types-docker`, lockfile.
- `uv run pytest tests/test_import_boundaries.py tests/test_settings.py tests/agents tests/core tests/worker`: unit tests, no Docker or Podman.
- `docker build --target agent .`, `docker build .` still running uvicorn by default, and `podman build` of `tests/agents/fake/Containerfile` on the agent image.

## Definition of Done

- Every gate above passes locally and in CI.
- U3 when the agent image and the test image build, and the fake CLI's contract test passes.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-podman-fixture` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-container-piece` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u3-tone-agent`, on top of `feat/agents-u2-boundaries`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
