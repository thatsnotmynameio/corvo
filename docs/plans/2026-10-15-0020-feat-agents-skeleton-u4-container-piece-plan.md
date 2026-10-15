---
title: Agents Skeleton U4 Container Piece and Tone Task - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u4-container-piece
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U4 Container Piece and Tone Task - Plan

## Goal Capsule

- **Objective:** `tone` runs end to end on Hatchet and rootless Podman, and timeout, cancel, worker loss, restart and shutdown leave no stray container.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 4 of 7. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** U1, U3. **Blocks:** U5 and U6 build on this part; U7 through U6.
- **Stop conditions:** stop and ask when Podman's Docker-compatible API on 4.9.3 or 6.1 rejects or silently drops a field of KTD6's container spec; when engine v0.110.5 rejects KTD9's tenant-scoped named concurrency strategy; or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U1: the rootless Podman session fixture in `tests/integration/worker/` and its limits test.
- U2: the agent areas, settings, boundary test and guard.
- U3: the `tone` package, `corvo-agent` (run and probe), the envelope and fingerprint modules, the `agent` Docker stage, and the fake CLI with its test image.

## Product Contract

### Summary

Adds the agent defaults, the container piece in `corvo.worker.agent_runtime` (spec, run, startup preparation and sweep, SIGTERM hook), the `tone` task registered in `WORKFLOWS`, and the integration tests on real Hatchet and Podman.

### Context

This is the piece every agent task uses, and the part where isolation, cleanup and the Hatchet contract come together. R7, R8, R9, R13 to R17 and AE1, AE3, AE4 and AE5 are completed here; R5 is completed by U6, the first agent with a working directory.

### Key Decisions

- **An agent is a Hatchet task that runs one agent session.** Workflows spawn it like any task. (session-settled: user-directed — chosen over an agent outside Hatchet that calls tasks as tools: both will exist, starting with this one.) Governs R6, R20.
- **Agent code lives in its own Hatchet-free package; the worker keeps only a thin task.** (session-settled: user-directed — chosen over an agents area inside `corvo.worker` that imports the SDK next to Hatchet.) Governs R1, R2, R6.
- **Each run executes in a fresh, hardened container.** It keeps a prompt-injected agent away from the worker's credentials. Following the Agent SDK's own docs, the whole agent runs inside the boundary, not just its commands. (session-settled: user-directed — chosen over running the agent as a subprocess of the worker, and over the SDK's built-in sandbox.) Governs R13, R15, R17.
- **Rootless Podman under a dedicated host user, with its socket mounted into the worker's container.** The worker stays a compose service. (session-settled: user-directed — chosen over the host's `docker.sock` (a compromised worker is host root), the worker running on the host, Docker-in-Docker and a hosted sandbox.) (session-settled: user-approved — Podman chosen over rootless Docker: it runs beside the compose stack's rootful Docker on its documented path, GitLab Runner documents the same setup, and the CI runner ships it.) Governs R14.
- **The caller gives the agent its working directory.** Cloning a repository or creating a worktree per issue is the caller's job. (session-settled: user-directed — chosen over the task building a temporary directory from its input.) Governs R5.
- **Hatchet does not retry agents.** A retry re-runs and re-pays the whole session, and the SDK already retries API errors itself. (session-settled: user-approved — chosen over corvo's `RETRIES` default, which assumes idempotent tasks.) Governs R7.
- **The container keeps network egress and receives the Claude credential, for now.** The SDK's docs recommend `--network none` behind a credential-injecting proxy; that is deferred. (session-settled: user-approved — chosen over building the proxy now.) Governs R15.

### Requirements

**Agent packages and boundaries**

- R5. An agent takes its working directory as a parameter and gives it to the SDK as the session's working directory. The task accepts only working directories under one configured agent-workdir root that both the worker's user and the dedicated Podman user can read, resolving symlinks, and fails any other path before it starts a container.

**Hatchet integration**

- R6. Each agent has a thin Hatchet task in `corvo.worker.agents` with an explicit name and Pydantic input and output models. The task is registered in `WORKFLOWS`, and the registration test covers the area.
- R7. Agent tasks declare `retries=0`, an agent execution timeout and an agent schedule timeout sized for the queue behind R9's cap, all defined once in the worker's defaults. A step that waits on an agent child declares a timeout derived from the agent's schedule and execution timeouts, not `WAITING_EXECUTION_TIMEOUT`.
- R8. A run that ends without valid structured output fails its task. That covers an error result, the turn or budget limit, and a success result without `structured_output`. In every case the task logs the run's cost, turns and session ID.
- R9. The pattern caps how many agent runs execute at once across the worker pool.

**Isolation**

- R13. Each agent run executes in a fresh container started for that run. The agent's code runs inside the container and hands its structured output to the task, which then removes the container.
- R14. Agent containers run on a rootless Podman under a dedicated host user, apart from the daemon that runs the compose stack. The worker stays a compose service and reaches Podman through that user's API socket, mounted into the worker's container and reachable by the worker's user through a shared group. When it starts, the worker checks that the host's cgroup controllers for memory, CPU and processes are available, and refuses agent runs when they are not.
- R15. The agent container drops every capability, has a read-only root filesystem, runs under the default seccomp profile, and is limited in memory, CPU and processes. Besides size-limited tmpfs mounts for `/tmp` and the agent user's home, it receives only the working directory mount and the Claude credential, and it takes its request and hands back its result over its standard streams (agent-request-stdin plan, KTD6). The working directory is mounted read-only unless the agent declares that it writes to it, and a directory an agent may have written is untrusted output: the worker runs no hooks, config or code from it.
- R16. When Hatchet times out or cancels an agent task, the task kills and removes its container. Every container carries labels with its run's ID and its Hatchet deployment (server and tenant). A worker that starts removes only containers of its own deployment whose run Hatchet reports as finished, failed or cancelled.
- R17. One piece of the worker starts, waits on, reads and removes agent containers, and every agent task uses it.

**Living examples**

- R21. Each example file opens with a header comment that carries the rules a copier needs, as the task and workflow examples do.

**Tests**

- R23. Each agent has unit tests that run without Hatchet and without a container, with the SDK replaced. Agent tasks and the container piece have unit tests with the agent and the container client replaced.
- R24. The integration suite runs every example on the real Hatchet and a real rootless Podman, with the SDK replaced inside the container, including the kill and removal on timeout. It creates its working directories under the agent-workdir root (R5), not in pytest's temporary directories.

### Acceptance Examples

- AE1. **Covers R6.** **Given** a new agent task in `corvo.worker.agents`, **when** its line is missing from `WORKFLOWS`, **then** the registration test fails and names the task.
- AE3. **Covers R8.** **Given** an agent that reaches its turn limit, **when** its task finishes, **then** the run is marked failed without a retry, and its log holds the cost, turns and session ID.
- AE4. **Covers R16, R24.** **Given** an agent run that is still working, **when** the task's execution timeout passes, **then** its container is killed and removed, and no container labelled with that run remains.
- AE5. **Covers R16.** **Given** a container of this worker's deployment whose run Hatchet reports as ended, and another whose run is still running on a second worker, **when** a worker starts, **then** it removes the first and leaves the second running.

### Scope Boundaries

- No compose overlay or provisioning doc: U5 adds them.

### Dependencies / Assumptions

- hatchet-sdk 1.42.1 cancels a running async task's asyncio task on cancellation and timeout (`hatchet_sdk/worker/runner/runner.py:920-944`). It sets the context's cancellation flag, sleeps one second, cancels the task, and frees the task's slot without waiting for its `finally`. Engine timeout and cancel reach the worker as the same `CANCEL_STEP_RUN` action. The SDK also has a `claude` extra (unpinned) and `mcp_tool` (`hatchet_sdk/runnables/workflow.py:831`), neither used here.
- The engine re-queues a task whose worker misses heartbeats for 30 seconds as an internal failure, up to `MaxInternalRetryCount` (10) times, whatever its `retries` (engine v0.110.5 `pkg/repository/task.go`, `pkg/repository/sqlcv1/tasks.sql`). `ctx.retry_count` is above zero on such a re-run.
- Podman's Docker-compatible API translates labels, mounts, tmpfs, `CapDrop`, `SecurityOpt`, `ReadonlyRootfs`, `PidsLimit`, `Memory` and `NanoCPUs` (Podman `pkg/api/handlers/compat/containers_create.go`). It forces read-write tmpfs mounts on `/run` and `/var/tmp` under a read-only root, which the memory cgroup bounds. docker-py refuses to send a user-namespace mode other than `host`, so `keep-id` is out of reach. Running on 4.9.3 and 6.1 is unverified until U1.
- On cgroup v2, a rootless container that asks for a limit whose controller is not delegated fails to start. Only cgroup v1 drops limits with a warning, and Podman 6 refuses cgroup v1. systemd 252 or later delegates memory, CPU and processes to user sessions by default. A user without lingering has no session, and Podman then falls back to cgroupfs.
- CI runs the organization's reusable `python.yml`, which allows no services and no setup steps. It runs `uv run --locked … pytest` in a 20-minute job, with passwordless `sudo` on GitHub-hosted runners. Any Podman setup in CI happens inside pytest.
- The integration suite runs `corvo-worker` as a host subprocess of the pytest session, which inherits its environment (`tests/integration/worker/conftest.py`). The compose stack runs only Hatchet there, so the worker runs as the developer's or the CI runner's user, the same user that owns the test Podman (KTD15).
- The default rootless network relays traffic through sockets the dedicated user opens on the host. The container therefore reaches the LAN, the cloud metadata endpoint and the compose stack's bridge addresses, not only the internet (passt and Podman network docs).

## Planning Contract

### Key Technical Decisions

- KTD1. **An agent package exposes one coroutine, `run`, in `agent.py`, and keeps everything the worker reads in `models.py`.**
  - `run` takes the agent's input model and its working directory (`None` for an agent without one). It returns its output model together with a `RunReport`: the subtype, turns, cost and session ID.
  - A failed session raises `AgentRunFailed`, which carries the same report. Both types live in `corvo.agents.envelope`, which imports only Pydantic.
  - Inside, `run` builds `ClaudeAgentOptions` and calls `query()` itself, with the SDK's own names (R4). It hands the iterator `query()` returned to `corvo.agents.session.consume`, which applies KTD4's result rule and returns the structured output and the report, or raises. The helper consumes the SDK's stream, and does not wrap or replace any of its calls.
  - `models.py` holds the input model, the model whose JSON Schema becomes `output_format`, the output model, and a `WRITES_WORKDIR` flag. It imports only Pydantic and the standard library.
  - The worker imports `models.py` and the SDK-free shared modules `envelope` and `fingerprint`, never `agent.py`, `tools.py` or `session.py`.

  The container's entrypoint, `corvo-agent` (`corvo.agents.runner`), imports `corvo.agents.<package>.agent`, validates the request's input with the input model, awaits `run`, and writes the envelope from what `run` returned or raised. The entrypoint sits outside the agent, not between the agent and the SDK. The agent's output model wraps the session's structured output and any field its core twin derives from it (R3). Governs R1, R3, R4, R8, R17.
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
- KTD5. **The container piece talks to Podman through docker-py over the dedicated user's Docker-compatible socket.** Each blocking call runs in `asyncio.to_thread`, and `types-docker` types it. With no `keep-id`, the agent runs as uid 0 inside the container, which rootless Podman maps to the dedicated host user. Its files are therefore owned by that user, with every capability dropped and no-new-privileges. (session-settled: user-approved — chosen over aiodocker, a corvo client over Podman's libpod API with httpx, and podman-py: docker-py is the official SDK on the path Podman documents, aiodocker is unverified against Podman, and podman-py silently drops `nano_cpus` and rejects `tmpfs=`.) The choice stays inside one module, so it did not call for a bake-off. Governs R13, R14, R17.
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
- KTD7. **One setting, `CORVO_AGENT_ROOT`, holds the working directories, at the same absolute path for the worker and for Podman.**
  - **Working directories.** They must resolve, symlinks included, to an existing directory strictly below `<root>/workdirs/`. `<root>/workdirs` itself is refused, since it would expose every other working directory.
  - **No run directories.** The request and the envelope travel over the attach stream (KTD4), so no run directory exists for any agent. The worker writes nothing under the root for a run, and the root holds only the working directories (agent-request-stdin plan, KTD6).
  - **Output from an agent that writes.** A working directory an agent may have written is untrusted output (R15). The container piece's header and `docs/agents.md` state the rule: the worker runs no git, hooks, config or code from such a tree.
  - **The same-path rule.** Podman resolves bind sources on the host, so the compose worker mounts the root at its host path, the same rule Testcontainers states. The integration worker runs on the host, so its paths agree by construction.

  Governs R5, R13, R15.
- KTD8. **The task guards against the engine's re-runs, and cleans up by label, shielded and time-bounded.**
  - **The re-run guard.** Before any session starts, a run whose `ctx.retry_count` is above zero force-removes every container labelled with its `corvo.task_run_id`.
    - When it found such a container, the earlier attempt never cleaned up, so its worker was lost (Dependencies). The run then fails with a message naming the re-assignment. The sweep removes only containers of ended runs (KTD11), and a re-queued run has not ended, so an earlier attempt's container is still there (agent-request-stdin plan, KTD6).
    - When it found none, the earlier attempt ended cleanly and this is a replay someone asked for: a dashboard or API replay also increments `retry_count` (engine v0.110.5 `tasks-overwrite.go`). The run proceeds. Only a worker lost before it created its container goes unflagged, and no session ran then.
  - **Cleanup.** On exit, error, timeout or cancel, the piece force-removes containers by the `corvo.task_run_id` label, one `remove(force=True)` call each, never by the handle `create` returned. A cancel can land while the create thread is still running and leave a container with no handle. Force-remove works on running and exited containers alike, whereas a kill of an exited container answers 409.
    - Cleanup first closes the attach socket, then waits for an in-flight create, attach or start thread (agent-request-stdin plan, KTD2).
    - It runs inside a shielded scope bounded to 30 seconds.
    - It treats 404 ("no such container") and 409 ("removal already in progress") as done.

  This instantiates the Key Decision that Hatchet does not retry agents, and inherits its label. (session-settled: user-approved — chosen over corvo's `RETRIES` default, which assumes idempotent tasks.) Governs R7, R13, R16.
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
- KTD15. **The integration suite runs its own rootless Podman as the test user.**
  - **Podman.** A session fixture starts `podman system service --time=0` on a socket inside a fixture-made agent root (`tempfile.mkdtemp`, outside pytest's temporary directories). It builds the agent image and the test image there.
  - **Worker.** The worker fixture passes `CORVO_AGENT_*` pointing at it, but only when Podman is present. Without Podman, the agent tests skip locally and fail when `CI` is set, and the other integration tests keep their worker.
  - **CI fallback.** When the runner has no systemd user session, the fixture's CI-only branch runs `sudo loginctl enable-linger` and sets `XDG_RUNTIME_DIR`. U1 decides whether that branch is needed.
  - **Timeout path.** AE4 is driven by `hatchet.runs.aio_cancel`, the same engine action a timeout sends (Dependencies), because a 15-minute timeout does not fit the 20-minute CI job.
  - **Teardown.** It removes every `corvo.managed` container in the test store.
  - **Health wait.** The worker fixture's health wait rises from 30 to 120 seconds, above KTD10's 45-second preparation and a cold first container start.

  The shared-group socket and the root-worker permissions exist only on the compose topology, which the manual proof covers (KTD18). Governs R24.
- KTD16. **Agent containers keep the default rootless network.** This instantiates the Key Decision on egress and inherits its label. (session-settled: user-approved — chosen over building the credential proxy now.) Conflict call-out: research found that the default network reaches more than the internet. It reaches the LAN, the cloud metadata endpoint and the compose stack's bridge addresses, through sockets the dedicated user opens on the host. Postgres and Hatchet still need credentials the container does not hold. The decision stands for these examples. `docs/agents.md` adds an owner-matched nftables rule as a production provisioning step: it drops the dedicated user's traffic to private, link-local and loopback ranges, with DNS allowed first. Every manual proof records what the container reached. Governs R15.
- KTD18. **Operating agents is opt-in through `compose.agents.yaml`, documented in `docs/agents.md`.**
  - **The overlay.** It changes the worker service:
    - It mounts the socket and `CORVO_AGENT_ROOT` at their host paths.
    - It adds the `corvo-agents` GID through `group_add`.
    - It drops the capabilities the worker does not need, at least `MKNOD`, `SETUID`, `SETGID` and `FOWNER`.
    - It sets the `CORVO_AGENT_*` variables, with `CORVO_AGENT_REQUIRE_EGRESS_BLOCK=true`, and `HATCHET_CLIENT_SERVER_URL`.

    Without the overlay, the stack runs as today, and agent tasks fail fast (KTD12).
  - **Provisioning.** The doc covers:
    - installing Podman;
    - the dedicated user, with subordinate IDs and lingering, kept out of the `docker` group and sudoers. Its login configuration, its systemd-user configuration and its `containers` configuration (`~/.config/containers`, including `containers.conf`, `storage.conf` and `registries.conf`) are root-owned and not writable by it. It writes only its container storage;
    - a `podman.socket` drop-in that moves `ListenStream=` to `/run/corvo-agents/podman.sock` with `SocketGroup=corvo-agents` and `SocketMode=0660`, plus the `tmpfiles.d` entry for its directory;
    - the agent root, setgid with a default ACL for the group, for the working directories under `<root>/workdirs`. It holds no run directories (agent-request-stdin plan, KTD6). In production it sits on its own filesystem or quota, mounted `nodev,nosuid`;
    - building the agent image as that user on every deploy, and recording its image ID. KTD10 refuses stale images, and a changed ID between deploys is then visible;
    - KTD16's nftables rule;
    - the credential terms and the OAuth token's one-year expiry.
  - **The manual proof runbook.** It triggers an example on the compose topology with real Haiku, and records in the pull request:
    - cost, turns and session ID;
    - peak process count;
    - that `/tmp` with `noexec` did not break the CLI;
    - that the worker read the envelope from the attach stream across the root/rootless boundary;
    - the agent root's mount flags and the worker's dropped capabilities;
    - what the container could reach.

    `dir-summary`'s proof also carries AE6 and tool denial: its working directory holds a CLAUDE.md, a `.claude/skills/` entry and a prompt that asks for a tool outside the list and for a read of `/proc/self/environ`. A fake CLI cannot prove those.

  Governs R14, R16, R25.
- KTD19. **When the worker gets SIGTERM, it force-removes the containers of its in-flight agent runs before Hatchet's graceful wait.**
  - The container piece keeps an in-process set of the containers this worker started.
  - The hook removes them by label, then hands over to Hatchet's own shutdown. Their tasks then fail on a missing envelope while the worker is still alive, so the engine records a failure instead of re-queuing them after the heartbeat window.
  - Without the hook, a redeploy leaves the old sessions running and paying until their deadline. Their re-queued attempts wait at the back of the `corvo-agents` queue, so the host could hold up to twice the cap.
  - A SIGKILL, an OOM kill or a host crash still skips the hook; KTD8's guard and KTD11's sweep cover those.
  - (session-settled: user-directed — chosen over sizing host memory for twice the cap plus one: a redeploy must not leave paid sessions running.)

  Governs R16.

## Implementation Units

### U4. The container piece, the `tone` task and the worker's preparation

- **Goal:** `tone` runs end to end on Hatchet and rootless Podman, and timeout, cancel, worker loss and restart leave no stray container.
- **Requirements:** R5, R6, R7, R8, R9, R13, R14, R15, R16, R17, R21, R23, R24, AE1, AE3, AE4, AE5; KTD4 to KTD12, KTD15, KTD19.
- **Dependencies:** U1, U3.
- **Files:**
  - Modify `src/corvo/worker/defaults.py` and `tests/worker/test_defaults.py`.
  - Create `src/corvo/worker/agent_runtime/__init__.py`, `spec.py`, `containers.py` and `startup.py`.
  - Create `src/corvo/worker/agents/tone.py`.
  - Modify `src/corvo/worker/worker.py` (`WORKFLOWS`, preparation in `main()`).
  - Create `tests/worker/agent_runtime/__init__.py`, `test_spec.py`, `test_containers.py` and `test_startup.py`.
  - Create `tests/worker/agents/__init__.py` and `tests/worker/agents/test_tone.py`.
  - Modify `tests/integration/worker/conftest.py` (images, agent env) and `test_podman.py` (use the spec from `spec.py`).
  - Create `tests/integration/worker/test_agents.py`.
- **Approach:**
  1. Defaults per KTD9, with prose comments, and `AGENT_WAITING_EXECUTION_TIMEOUT` derived in the comment, as `WAITING_EXECUTION_TIMEOUT` is.
  2. `spec.py` holds pure functions: the container spec (KTD6), the working-directory check (KTD7), the deployment label and the sweep decision (KTD11), and the probe comparison (KTD10).
  3. `containers.py` runs one agent with docker-py in `asyncio.to_thread`, per the run flowchart, with KTD4's reading rules and KTD8's guard and cleanup.
  4. `startup.py` prepares agents (KTD10) and sweeps (KTD11). It is called from `main()` before `create_worker().start()`. `main()` also installs KTD19's SIGTERM hook.
  5. The `tone` task declares the name `tone`, `ToneInput` and `ToneOutput`, `retries=0` and the agent defaults. Its body calls the container piece. Its header carries R21's rules for a copier: thin shell, the agent's package named once, models from `models.py` only, the retries rule and why, no stubs in this area.
  6. The integration fixture builds the agent image from the repository and the test image on it, then gives the worker the test image's tag.
- **Patterns to follow:** `src/corvo/worker/workflows/greeting.py` for declaration tests and replaced children; `tests/integration/worker/test_workflows.py` for triggering by name, `finished_tasks` polling and `asyncio.timeout`.
- **Test scenarios:**
  - The `tone` task declares `retries == 0`, `AGENT_EXECUTION_TIMEOUT`, `AGENT_SCHEDULE_TIMEOUT` and the `corvo-agents` concurrency, read from its public definition.
  - `AGENT_WAITING_EXECUTION_TIMEOUT` is at least `AGENT_SCHEDULE_TIMEOUT + AGENT_EXECUTION_TIMEOUT + DETECTION_LAG`.
  - The spec drops every capability, and sets no-new-privileges, a read-only root, both tmpfs mounts with `noexec,nosuid,nodev` and their sizes, and the three limits. It carries all six labels.
  - The spec mounts the working directory read-only, or read-write when `WRITES_WORKDIR` is true, and nothing else. It opens stdin without a tty and sets the log driver to `none` (agent-request-stdin plan, KTD6).
  - With no working directory, the spec mounts no `/workspace`. With no credential, as the probe's spec, it carries no credential variable.
  - The spec passes `ANTHROPIC_API_KEY` for `api_key` and `CLAUDE_CODE_OAUTH_TOKEN` for `oauth_token`, never both, and every isolation variable of KTD3.
  - The working-directory check accepts a directory strictly below `<root>/workdirs`. It rejects `<root>/workdirs` itself, one outside the root, one reached through a symlink that points outside, `<root>/workdirs/../other`, and a missing path.
  - The request's budget is `AGENT_EXECUTION_TIMEOUT - AGENT_DEADLINE_MARGIN` minus the time since the task started, so it is always below Hatchet's timeout.
  - A request over the 1 MiB cap fails the run before any container call, and a container that never reads its request fails the run within `REQUEST_WRITE_TIMEOUT` (agent-request-stdin plan, KTD3).
  - The sweep decision removes `COMPLETED`, `FAILED` and `CANCELLED` entries, and keeps `QUEUED`, `RUNNING`, not-found and timed-out entries, logging a warning for the last two.
  - The probe's container is gone after preparation, whether the probe passed or failed.
  - The probe comparison rejects a `memory.max` of `max`, a fingerprint that differs and a non-empty capability set.
  - A report with a reachable metadata address disables agents when `agent_require_egress_block` is set, and only logs a warning when it is not.
  - With the docker client replaced, a run reads an `ok` envelope and returns the output. It logs cost, turns and session ID from the envelope, then closes the attach socket and force-removes the already-exited container by label.
  - Cleanup treats a 404 or a 409 from the force-remove as done.
  - Forwarded stderr lines reach `ctx.log` behind the `agent stderr:` prefix, cut to 500 characters, and stop after 900 lines.
  - Stdout past the 1 MiB cap, a bad frame header or invalid JSON fails the task as "invalid envelope", and a missing or truncated frame as "no envelope". The stream is drained to its end without blocking, and nothing the container sent on stdout reaches the log (agent-request-stdin plan, KTD6).
  - An exit with the OOM flag and no envelope fails, logging `cost=unknown`, the exit code and the flag.
  - With `ctx.retry_count` of 1 and a container labelled with its task run ID, the task removes that container, then fails before creating one.
  - With `ctx.retry_count` of 1 and no such container, the task proceeds as a replay.
  - A cancel delivered while the replaced create call is still running still removes the container that call created, found by label.
  - With agents unconfigured, the task fails with "agents are not configured" and makes no client call.
  - A run that finds agents disabled fails at once with the reason preparation logged.
  - Covers AE1. Removing `tone` from `WORKFLOWS` makes the registration test fail, naming it.
  - Integration: `tone` triggered by name with a friendly text returns the fake's canned verdict with `friendly` true, and no `corvo.managed` container remains.
  - Covers AE3. Integration: `tone` with `fake:max-turns` in its text fails without a retry, and its run log holds the cost, turns and session ID.
  - Covers AE4. Integration: `tone` with `fake:hang`, cancelled through `hatchet.runs.aio_cancel` once its container runs, ends with no container labelled with that run. The engine sends the same action on timeout.
  - Covers AE5. Integration, ended run: a stray container of this deployment labelled with a completed run is removed when a second worker starts.
  - Covers AE5. Integration, live run: while that second worker starts, a `fake:hang` run on the first keeps its container, which the test then cancels.
  - With the docker client replaced, the SIGTERM hook removes every container in the in-flight set, and none outside it.
  - Integration: SIGTERM to a worker running a `fake:hang` run removes its container before the worker exits. The run ends `FAILED` and is not re-run.
  - The sweep keeps a container whose status lookup timed out, and finishes within its 20-second bound with four not-found runs.
  - Integration: the preparation's probe report matches the spec on the test Podman, so the worker logs agents as enabled. This covers R15 on real Podman.
- **Verification:** unit and integration suites pass on compose plus the test Podman, and coverage of `src` stays at 90% or above.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict with `types-docker`, lockfile.
- `uv run pytest tests/test_import_boundaries.py tests/test_settings.py tests/agents tests/core tests/worker`: unit tests, no Docker or Podman.
- `uv run pytest tests/integration/worker`: integration on compose and the test's rootless Podman (needs Docker and Podman).
- `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `coverage report --fail-under=90` the same way: CI's coverage floor.

## Definition of Done

- Every gate above passes locally and in CI.
- U4 when `tone`'s integration tests pass on compose plus the test Podman.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-podman-fixture` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-container-piece` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u4-container-piece`, on top of `feat/agents-u3-tone-agent`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
