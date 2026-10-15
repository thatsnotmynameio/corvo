---
title: Agents Skeleton - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
execution: code
deepened: 2026-10-15
---

# Agents Skeleton - Plan

## Goal Capsule

- **Objective:** Adding an AI agent to corvo means copying a living example, filling it in, adding one line to the agent worker and writing its tests. From its first run, an agent whose shell commands follow a prompt injection cannot reach corvo's credentials, other runs, the host or the outside world.
- **Means:** the Claude Agent SDK, used with its own API in a Hatchet-free `corvo.agents` package. A thin Hatchet task on a dedicated agent worker runs each session with the SDK's engine in a bubblewrap sandbox of its own, the SDK's sandbox around every shell command, and the Claude credential held by a proxy outside.
- **Product authority:** the repository owner, who settled every decision recorded under Key Decisions. The Product Contract wins on behavior; a KTD wins on mechanism within its cited requirements.
- **Open blockers:** the Planning Contract, Implementation Units, Verification Contract, Definition of Done and the part plans (`docs/plans/2026-10-15-0020-feat-agents-skeleton-u1-podman-fixture-plan.md` to `docs/plans/2026-10-15-0020-feat-agents-skeleton-u7-dir-review-plan.md`) still describe per-run Podman containers. They must be planned again against this Product Contract before any implementation. `docs/plans/2026-10-15-1030-fix-agent-request-stdin-plan.md` is superseded with them.

---

## Product Contract

### Summary

`corvo.agents` gets one package per agent, written with the Claude Agent SDK's own API and blind to Hatchet. Its SDK-independent logic lives in a mirrored `corvo.core.agents` module. Each agent has a thin Hatchet task that runs only on a dedicated agent worker. The task runs each session with the SDK's engine in a fresh bubblewrap sandbox bounded by its own cgroup. Inside, the SDK's own sandbox isolates every shell command, and a proxy outside holds the Claude credential. Three living examples show each shape. Other SDKs come later as agents written with their own native APIs.

The plan builds this whole contract, plus what operating it needs: the agent worker's compose service and container settings, the credential proxy, and the repository's first operations doc, which covers the manual Haiku proofs.

### Problem Frame

corvo's workflows track will hand steps to agents: crew's own agents (product-manager, claude-developer) already plan, split and relate issues headless in a worktree. Today nothing in corvo says where an agent goes, what shape it takes, or how it meets Hatchet. The first agent would invent all three, and every later one would copy whatever it chose.

Where the agent runs matters as much as its shape. Every agent corvo plans will have Bash, and an agent with Bash in the worker's process sees the worker's environment: the Hatchet token, the database password and the Claude credential. Hatchet provides no sandboxing and leaves it to infrastructure, so corvo has to decide it.

A first design ran each session in a fresh rootless-Podman container driven from the worker. Each review round found another hole in it: a group-readable request file, then a result that any process in the container could forge, then the Claude credential in every child process's environment. Measured on 2026-10-15, a child process in that container wrote a forged result through `/proc/1/fd/1`, which the container's init held open, and the forgery reached the worker before the real result. Each fix added transport code over the container's streams, and the host still needed a Podman of its own.

The tasks and workflows skeleton (`docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md`) solved the same problem for Hatchet code with living examples, mirrored core twins, explicit registration and an import rule. This work does the same for agents.

### Key Decisions

- **An agent is a Hatchet task that runs one agent session.** Workflows spawn it like any task. (session-settled: user-directed — chosen over an agent outside Hatchet that calls tasks as tools: both will exist, starting with this one.) Governs R6, R20.
- **Each agent uses its SDK's own API, with no corvo interface over SDKs.** Agents share a shape, not a contract: a thin task, a core twin, Pydantic models, defaults and registration. (session-settled: user-directed — chosen over one agent definition runnable on any SDK through corvo adapters, and over a common corvo contract every SDK adapter implements.) Governs R4.
- **Agent code lives in its own Hatchet-free package; the worker keeps only a thin task.** (session-settled: user-directed — chosen over an agents area inside `corvo.worker` that imports the SDK next to Hatchet.) Governs R1, R2, R6.
- **One package per agent, with `agent.py` and `prompts/`, plus `tools.py` when the agent has custom tools, mirrored by a core twin.** These are the names Google ADK, Anthropic's Agent SDK cookbooks and demos, and Hatchet's agent examples use. (session-settled: user-approved — chosen over a prompt held as a constant in code, and over SDK-named files such as `agent_claude.py`.) Governs R1, R3.
- **Prompts live with the agent, not in the core.** A prompt is tuned to its SDK and model. The core holds only logic that survives an SDK change. (session-settled: user-approved — chosen over prompts in the core: a prompt is tuned to its SDK and model.) Governs R1, R3.
- **Each session's SDK engine runs in a fresh bubblewrap sandbox, and the SDK's sandbox with its credential scrub isolates every shell command inside it.** Measured together, the two layers stopped every escape a scripted shell command tried; either layer alone left some open. (session-settled: user-directed — chosen over the per-run Podman container, which left the forged result open, and over the SDK's sandbox alone, which leaves the worker's environment within every command's reach.) Governs R14, R15, R17, R26.
- **bubblewrap for both layers.** The SDK's sandbox already depends on it, and Flatpak, Claude Code and Codex use it. (session-settled: user-directed — chosen over runc, youki, nsjail and gVisor for the outer layer: each adds a second isolation tool without removing bubblewrap, and rootless gVisor drops cgroup limits and network namespaces.) Governs R14.
- **No VM.** The sessions share the host's kernel, as the Podman design did. (session-settled: user-directed — chosen over a dedicated VM for the agent worker and over a microVM per run.)
- **The agent worker is a compose service of its own.** (session-settled: user-approved — chosen over a systemd service on the host: it keeps one deploy path and the Hatchet engine's gRPC internal, at the cost of R27's container settings and a profile kept in step with Docker's.) Governs R13, R27.
- **The Claude credential lives in a proxy and the agent worker's egress is cut, from the first run.** Without both, a session that reads its own engine's credential could send it out. (session-settled: user-approved — chosen over deferring the proxy and `--network none`, as the Podman design did.) Governs R12, R16.
- **Every tool corvo runs or ships has its license read at the source before it is adopted.** bubblewrap's files are LGPL-2.0-or-later and LGPL-2.1-or-later, and socat is GPL-2.0-only. Both run as separate, unmodified programs from distribution packages, which their licenses leave unrestricted. (session-settled: user-approved — chosen over permissive-only tools for the outer layer, after the license texts were read.)
- **The caller gives the agent its working directory.** Cloning a repository or creating a worktree per issue is the caller's job. (session-settled: user-directed — chosen over the task building a temporary directory from its input.) Governs R5.
- **The Claude credential is either an API key or a subscription OAuth token, chosen per environment.** (session-settled: user-directed — chosen over an API key only and over a subscription token only.) Governs R12.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.
- **Hatchet does not retry agents.** A retry re-runs and re-pays the whole session, and the SDK already retries API errors itself. (session-settled: user-approved — chosen over corvo's `RETRIES` default, which assumes idempotent tasks.) Governs R7.
- **Three examples cover the four shapes.** Example 2 combines the working directory with a custom tool, as `greeting-rounds` combined spawning and waiting. (session-settled: user-approved — chosen over one example per shape.) Governs R18, R19, R20.

### Requirements

**Agent packages and boundaries**

- R1. `corvo.agents` holds one package per agent. `agent.py` builds the SDK options and runs the session, `models.py` holds the agent's Pydantic models and imports no SDK, `tools.py` holds the agent's custom tools when it has any, and `prompts/` holds the prompt text files the agent reads and passes to the SDK.
- R2. Only `corvo.agents` imports `claude_agent_sdk`. `corvo.agents` imports neither Hatchet nor `corvo.worker`, and `corvo.core` imports neither `corvo.agents` nor the SDK. A check fails on each of these imports in every module, including `corvo.worker` and `corvo.server.api`, whose files ignore ruff's TID251 wholesale today.
- R3. Logic that must survive an SDK change, such as decisions on the agent's output and its tools' logic, lives in pure functions in `corvo.core.agents` at the mirrored path. The agent package only adapts that logic to the SDK.
- R4. Every agent is written with its SDK's own API, with no corvo layer between it and the SDK.
- R5. An agent takes its working directory as a parameter and gives it to the SDK as the session's working directory. The task accepts only working directories under one configured agent-workdir root, resolving symlinks, and fails any other path before it starts a session.

**Hatchet integration**

- R6. Each agent has a thin Hatchet task in `corvo.worker.agents` with an explicit name and Pydantic input and output models. Agent tasks are registered only in the agent worker's list, which holds nothing else, and the registration test covers both workers.
- R7. Agent tasks declare `retries=0`, an agent execution timeout and an agent schedule timeout sized for the queue behind R9's cap, all defined once in the worker's defaults. A step that waits on an agent child declares a timeout derived from the agent's schedule and execution timeouts, not `WAITING_EXECUTION_TIMEOUT`.
- R8. A run that ends without valid structured output fails its task. That covers an error result, the turn or budget limit, and a success result without `structured_output`. In every case the task logs the run's cost, turns and session ID.
- R9. The pattern caps how many agent runs execute at once across the worker pool.

**Agent execution**

- R10. Every agent declares its model, its turn limit and its budget limit.
- R11. Agents load no CLAUDE.md, skills, settings or auto memory, whether from the host or from the working directory. They use only tools they list explicitly, and every other tool call is denied.
- R12. The Claude credential comes from corvo's settings, as an API key or a subscription OAuth token, and each environment chooses which. Only the proxy of R16 receives it.

**Isolation**

- R13. Agent tasks run only on a dedicated agent worker, which holds the Hatchet token but neither the database password nor the Claude credential.
- R14. Each session's SDK engine runs in a fresh bubblewrap sandbox started for its run and ended with it, in a process namespace of its own and an environment that holds only what the session needs.
- R15. Every shell command a session runs goes through the SDK's sandbox with its subprocess credential scrub, and a command that cannot be sandboxed does not run. Command network reaches only an allowlist, which is empty for every example.
- R16. A proxy outside the agent worker holds the Claude credential, puts it in place of the placeholder each session sends, and forwards only to the Claude API. The agent worker's network reaches only the proxy and the Hatchet engine.
- R17. One piece of the agent worker starts, bounds and ends each session's sandbox, and every agent task uses it. When Hatchet times out or cancels an agent task, no process of that run survives.
- R26. A session sees only its run's working directory, a temporary home and read-only system files, and its own cgroup limits its memory, CPU and processes. The working directory is read-only unless the agent declares that it writes to it.
- R27. The agent worker's container keeps a syscall filter: Docker's default profile plus only the calls bubblewrap needs. The profile is generated from the upstream one, and a CI check fails when the generated and the committed profiles differ.
- R28. When the agent worker starts and its isolation cannot apply in full, it refuses agent runs and logs which part failed: bubblewrap, the SDK's sandbox, the cgroup delegation or the proxy.
- R29. What a session hands back, and whatever it writes into its working directory, is untrusted output: the task validates the output (R8), and the worker runs no hooks, config or code from the directory.
- R30. Custom tools run in the agent worker's process, outside the sandbox, so each one treats its input as untrusted.

**Living examples**

- R18. An agent with no tools turns a Pydantic input into a structured output.
- R19. An agent works in the directory it receives, with the SDK's read-only file tools and one custom tool whose logic lives in the core.
- R20. A workflow spawns both agents as child runs and uses their outputs.
- R21. Each example file opens with a header comment that carries the rules a copier needs, as the task and workflow examples do.

**Tests**

- R22. No automated test calls Claude, and a guard fails any test that tries.
- R23. Each agent has unit tests that run without Hatchet and without a sandbox, with the SDK replaced. Agent tasks and the session piece have unit tests with the agent and the sandbox replaced.
- R24. The integration suite runs every example on the real Hatchet and real bubblewrap with the SDK's engine replaced, including the end of a run on timeout. It creates its working directories under the agent-workdir root (R5), not in pytest's temporary directories.
- R25. Each example is proven once against real Claude Haiku with a small prompt, through a documented manual command whose run is recorded in the pull request.
- R31. An automated test runs the real SDK engine in the real sandbox against a scripted Messages API that makes a session try each escape of AE5, and fails when any succeeds.

### How a run flows

```mermaid
flowchart TB
  WF[workflow: DAG or durable] -->|spawns as a child run| T[agent task on the agent worker]
  T -.-> S[session piece]
  S -.-> A[agent package in corvo.agents]
  A -.->|pure calls| K[corvo.core.agents twin]
  A -->|query| E[SDK engine in a fresh bubblewrap sandbox, own cgroup]
  E -->|each shell command| B[SDK sandbox with credential scrub]
  E -->|placeholder credential| P[credential proxy]
  P -->|real credential| CL[Claude API]
  E -->|ResultMessage with structured output| A
  S -->|validated output model| T
  S -->|end the sandbox: on finish, timeout or cancel| E
```

Solid arrows cross a process, sandbox or network boundary. Dotted arrows are calls inside the agent worker's process, where custom tools also run.

### Acceptance Examples

- AE1. **Covers R6.** **Given** a new agent task in `corvo.worker.agents`, **when** its line is missing from the agent worker's list, **then** the registration test fails and names the task.
- AE2. **Covers R2.** **Given** a module outside `corvo.agents` that imports `claude_agent_sdk`, such as an agent task in `corvo.worker.agents`, or a module in `corvo.agents` that imports Hatchet, **when** the checks run, **then** they fail on that import.
- AE3. **Covers R8.** **Given** an agent that reaches its turn limit, **when** its task finishes, **then** the run is marked failed without a retry, and its log holds the cost, turns and session ID.
- AE4. **Covers R17, R24.** **Given** an agent run that is still working, **when** the task's execution timeout passes, **then** its sandbox ends and no process of that run remains.
- AE5. **Covers R13, R14, R15, R16, R26, R31.** **Given** a session whose shell command follows a prompt injection, **when** it tries to read the Hatchet token or the Claude credential from any process, write a result into its engine's output, list another run's or the host's files, or reach the internet, **then** every attempt fails and the task returns only the session's real output.
- AE6. **Covers R11.** **Given** a working directory that holds a CLAUDE.md and `.claude/skills/`, **when** an agent runs in it, **then** the session loads neither.
- AE7. **Covers R20, R24.** **Given** the workflow example on Hatchet and bubblewrap with the SDK's engine replaced, **when** it runs, **then** it returns outputs derived from both agents' structured outputs.
- AE8. **Covers R22.** **Given** a unit test that runs an agent without replacing the SDK, **when** it runs, **then** the guard fails it before any request leaves.
- AE9. **Covers R26.** **Given** a session that allocates memory past its limit, **when** the limit is reached, **then** that run fails, and the agent worker and the other runs keep going.
- AE10. **Covers R27, R28.** **Given** an agent worker whose container lacks R27's profile, so bubblewrap cannot create its namespaces, **when** it starts, **then** it refuses agent runs and logs that bubblewrap failed.

### Success Criteria

- A contributor, human or LLM agent, adds a working agent by reading only the examples. That means an agent package, its core twin, a thin task, one line in the agent worker's list, and their tests.
- The official Claude Agent SDK docs apply to corvo's agents unchanged, and Hatchet's task and workflow docs apply to their thin tasks.
- AE5 holds with the operating system enforcing every part of it (R14, R15, R16, R26), not the SDK's permission rules.
- A compromised agent worker finds no database password and no Claude credential to take (R13).

### Scope Boundaries

- Agents that call Hatchet tasks as tools, and agents that run outside Hatchet and trigger it. Custom tools run in the agent worker's process, which holds the tenant-wide Hatchet token, so a Hatchet-backed tool would put that authority behind the model's tool calls.
- Other agent SDKs (OpenAI Agents SDK and others). Each will be written with its own API when its first agent arrives.
- Shell network allowlist entries. The first agent whose commands need a host, such as GitHub, brings its entry.
- runc, youki, nsjail or gVisor for the outer layer, and a VM or a microVM per run (Key Decisions).
- More than one host: Kubernetes Jobs or a hosted sandbox (E2B, Modal).
- An e2e job against real Claude, and evals. Evals belong to the question bank.
- Resumable sessions, session stores, multi-turn conversations, subagents, and approval callbacks (human in the loop).
- Porting crew's agents, and loading skills or CLAUDE.md into agent sessions, which those agents need. The main flow decides both.
- Creating working directories (clone or worktree per issue). The caller does that.
- No real business logic: the examples hold only trivial prompts and core functions.

Considered and not built:

- A systemd service on the host for the agent worker. It needs no relaxed container settings, but it adds a second deploy path and publishes the Hatchet engine's gRPC outside compose (Key Decisions).
- A check that the credential's prefix matches its configured kind. A mismatch fails the first run at once with an `api_error` result and zero cost, which the run log shows.
- Preparing again when a run finds agents refused. The run fails at once with the logged reason, and a worker restart prepares again.

#### Deferred to Follow-Up Work

- An integration scenario for the writable working directory, and the permission checks around it, when the first agent that writes arrives.

### Dependencies / Assumptions

- hatchet-sdk 1.42.1 cancels a running async task's asyncio task on cancellation and timeout (`hatchet_sdk/worker/runner/runner.py:920-944`). It sets the context's cancellation flag, sleeps one second, cancels the task, and frees the task's slot without waiting for its `finally`. Engine timeout and cancel reach the worker as the same `CANCEL_STEP_RUN` action. The SDK also has an unpinned `claude` extra and `mcp_tool` (`hatchet_sdk/runnables/workflow.py:831`), neither used here.
- The engine re-queues a task whose worker misses heartbeats for 30 seconds as an internal failure, up to `MaxInternalRetryCount` times, which is 10, whatever its `retries` (engine v0.110.5 `pkg/repository/task.go`, `pkg/repository/sqlcv1/tasks.sql`). `ctx.retry_count` is above zero on such a re-run.
- Hatchet API tokens are scoped per tenant, with no per-worker or narrower token (Hatchet security docs). A task goes only to workers that registered it, and worker labels attract tasks without keeping others away (Hatchet worker and worker-affinity docs).
- claude-agent-sdk 0.2.167 (2026-10-14, bundling CLI 2.1.300) ships only `manylinux_2_17` wheels, which `python:3.14.7-slim` satisfies, and bundles a native `claude` binary of about 250 MB. It releases almost daily. `query()` runs that engine as a subprocess over stdio, and `ClaudeAgentOptions.env` is merged over the inherited environment (`_internal/transport/subprocess_cli.py`), so only a sandbox that starts from an empty environment keeps the worker's variables out of the engine.
- The SDK's `ResultMessage` carries `subtype`, `is_error`, `structured_output`, `total_cost_usd`, `num_turns` and `session_id`. An error result is yielded, then raised as `ResultError`. An API failure arrives as `subtype="success"` with `is_error=True`. A Pydantic model's JSON Schema passed as `output_format` comes back in `structured_output` (Agent SDK Python reference and structured-outputs guide).
- `allowed_tools` with `permission_mode="dontAsk"` still lets read-only Bash, the Agent tool and reads inside the working directory run. Restricting the tool set takes the `tools` option (Agent SDK `permissions.md`).
- Per the Claude Code sandboxing doc, the SDK's sandbox covers only the commands of Bash, PowerShell and Monitor, and file tools follow permission rules. The Python SDK runs commands unsandboxed when the sandbox cannot start, unless `failIfUnavailable` is set. Per the env-vars doc, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips credentials from commands' environments and runs them in their own PID namespace.
- Measured on 2026-10-15 with the bundled engine against a local stand-in for the Messages API that scripted Bash and Read calls (Arch, kernel 7.2, bubblewrap 0.12.0, Docker 29.7.2):
  - Without a sandbox, and with the outer bubblewrap alone, a shell command forged a `ResultMessage` that the SDK yielded before the real one. With the SDK's sandbox alone, the command still read the Hatchet token and the Claude credential in its environment and listed other checkouts. With both layers and the scrub, every attempt failed.
  - The scrub forces `permission_mode` from `dontAsk` to `default`; with explicit `allowed_tools`, every other call was still denied. On the development host, the scrub's own bubblewrap fails outside an outer sandbox because `/run/containerd` exists but is unreadable, and it then runs nothing.
  - The Read tool refuses `/proc/*/environ` as a device file. That is an engine check, not an OS boundary.
  - The engine refuses to run with no credential. With a placeholder it sends `x-api-key: <placeholder>` for an API key, or `Authorization: Bearer <placeholder>` with `anthropic-beta: oauth-2025-04-20` for an OAuth token, to `ANTHROPIC_BASE_URL` alone, with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
  - Docker's default seccomp profile refuses the user namespaces bubblewrap needs. That profile plus `clone`, `unshare`, `mount`, `umount2`, `pivot_root` and `setns` lets bubblewrap start, while `keyctl`, `add_key`, `request_key`, `perf_event_open`, `kexec_load` and `open_by_handle_at` stay refused.
  - A fresh `/proc` also needs Docker's `/proc` masks lifted (`systempaths=unconfined`). uid 1000 then still cannot read `/proc/kcore` or `/proc/timer_list` and gains no write.
  - With `writable-cgroups=true`, a root entrypoint delegated a cgroup subtree to uid 1000 and dropped root. A session in a child cgroup stopped at its process limit and was killed at its memory limit, while the worker's cgroup was untouched.
- Ubuntu 24.04 and later restrict unprivileged user namespaces through AppArmor (`kernel.apparmor_restrict_unprivileged_userns`), and the sandboxing doc says bubblewrap needs an AppArmor profile there. Whether that blocks bubblewrap on CI's `ubuntu-latest` runner, on the host or inside Docker there is unverified.
- CI runs the organization's reusable `python.yml`, which allows no services and no setup steps. It runs `uv run --locked … pytest` in a 20-minute job, with passwordless `sudo` on GitHub-hosted runners. Any sandbox setup in CI happens inside pytest.
- uv_build packages every file under `src/corvo/`, so `prompts/*.md` reaches the wheel with no configuration (checked by building one). `.dockerignore` excludes `tests/`.
- The subscription OAuth token is, by Anthropic's terms, for ordinary individual use by the subscriber. Products and services built on the Agent SDK must use API keys (`legal-and-compliance.md`; Agent SDK `overview.md`). A `claude setup-token` token lasts one year.

### Outstanding Questions

Deferred to Planning:

- Which proxy holds the credential: a small service of corvo's or an existing proxy, with its license read first.
- How CI gets bubblewrap, socat and user namespaces within `python.yml`'s no-setup rule, proved first on the runner as U1 proved Podman.
- Which of `corvo.agents.runner`, `corvo.agents.frame`, `corvo.agents.envelope`, the fake CLI and the `agent` image stage survive, and how the existing stack's pull requests are reworked or closed.
- What the agent worker does with cgroups a run left behind when it restarts.
- How R22's guard admits R31's session against the scripted API and nothing else.

### Sources / Research

- Claude Agent SDK and Claude Code docs, each page served as markdown under https://code.claude.com/docs/en/:
  - `agent-sdk/overview.md`, `agent-sdk/agent-loop.md` and `agent-sdk/python.md`: `query`, `ClaudeAgentOptions` (`cli_path`, `sandbox`, `env`), `ResultMessage` subtypes, `max_turns` and `max_budget_usd`.
  - `agent-sdk/permissions.md`: `dontAsk`, `allowed_tools`, and the `tools` option that restricts the set.
  - `agent-sdk/claude-code-features.md`: `setting_sources=[]`, `CLAUDE_CODE_DISABLE_AUTO_MEMORY`, and what `settingSources` does not control.
  - `agent-sdk/structured-outputs.md` and `agent-sdk/custom-tools.md`.
  - `agent-sdk/hosting.md`: the subprocess model, one subprocess per session, about 1 GiB per agent.
  - `agent-sdk/secure-deployment.md`: isolation technologies and their ratings, and the credential proxy pattern.
  - `sandboxing.md`: what the sandbox covers, bubblewrap and socat on Linux, `failIfUnavailable`, `allowUnsandboxedCommands`, nested containers.
  - `env-vars.md`: `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` and the isolation and credential variables.
- anthropics/claude-agent-sdk-python at `v0.2.167`: `tests/test_run_end_subprocess.py` (the fake-CLI pattern), `_internal/query.py` (the control protocol and `mcp_message`), `_internal/transport/subprocess_cli.py` (CLI discovery, flags and the child environment).
- anthropics/claude-code-action `base-action/src/run-claude-sdk.ts`: result checks.
- Hatchet docs:
  - https://docs.hatchet.run/cookbooks/hatchet-claude-agent-sdk-trusted-env.md and https://docs.hatchet.run/cookbooks/hatchet-and-mcp.md: `mcp_tool`, and "Hatchet does not provide native code sandboxing".
  - https://docs.hatchet.run/v1/workers.md, https://docs.hatchet.run/v1/advanced-assignment/worker-affinity.md and https://docs.hatchet.run/v1/security/index.md: registration, labels, and tenant-scoped tokens.
  - https://docs.hatchet.run/v1/cancellation.md, https://docs.hatchet.run/v1/timeouts.md and https://docs.hatchet.run/v1/logging.md (1000 log lines per task).
  - https://docs.hatchet.run/v1/concurrency.md and https://docs.hatchet.run/v1/advanced-assignment/slot-cost.md.
- Isolation tools and their licenses:
  - containers/bubblewrap: `COPYING` and `LICENSE` (LGPL 2.1), the SPDX headers of its sources, and its Debian packaging.
  - GNU GPL FAQ, https://www.gnu.org/licenses/gpl-faq.html, entries `#MereAggregation` and `#GPLPlugins`.
  - moby/profiles `seccomp/default.json` and its history, vendored in moby at `docker-v29.7.2`.
  - opencontainers/runc README (libseccomp), google/nsjail `Makefile`, the gVisor rootless guide (https://gvisor.dev/docs/user_guide/rootless/), youki-dev/youki, google/minijail, anthropic-experimental/sandbox-runtime.
- Agent layouts:
  - google ADK project structure: https://adk.dev/get-started/python/.
  - anthropics/claude-cookbooks `claude_agent_sdk/`.
  - anthropics/claude-agent-sdk-demos `research-agent/` (`prompts/*.txt`).
  - hatchet-dev/hatchet `sdks/python/examples/support_agent_tools/`.
- Testing practice:
  - anthropics/claude-agent-sdk-python: mocked transport in `tests/`, and a separate `e2e-tests/` job.
  - openai/openai-agents-python `ScriptedModel`.
  - pydantic-ai `TestModel` and `ALLOW_MODEL_REQUESTS`.
  - https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents.
- Repo:
  - `docs/plans/2026-10-14-1724-feat-worker-tasks-workflows-skeleton-plan.md`, the precedent this work mirrors.
  - `src/corvo/worker/worker.py`, `src/corvo/worker/defaults.py` and `src/corvo/worker/hatchet_client.py`.
  - `src/corvo/agents/tone/agent.py`, the first agent, and `src/corvo/settings.py`.
  - `tests/worker/test_registration.py`, `ruff.toml`, `tests/conftest.py` (the guard) and `tests/integration/worker/conftest.py`.
  - `Dockerfile`, `.dockerignore`, `compose.yaml` and `.crew/config.yaml` (crew's agents).

---

## Planning Contract

Product Contract preservation: changed: R1 adds `models.py`, an agent's SDK-free Pydantic module. The worker validates the agent's input and output without importing the SDK (R2), so the models need a home the worker can import. R15 names the container's standard streams as the channel for the request and the result, since the envelope (KTD4) travels over them (agent-request-stdin plan, KTD6). Dependencies / Assumptions was corrected and extended with research findings: the Podman versions, cgroup v2 behavior, the engine's internal re-queue, the SDK's result and tool semantics, CI's limits, the OAuth terms and the network's reach. The uv_build packaging question is closed there. The questions deferred to planning are answered by KTD5 to KTD18, so their section was removed. Scope Boundaries gained the considered-and-not-built list and one deferred item. No requirement's behavior changed.

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
- KTD15. **The integration suite runs its own rootless Podman as the test user.**
  - **Podman.** A session fixture starts `podman system service --time=0` on a socket inside a fixture-made agent root (`tempfile.mkdtemp`, outside pytest's temporary directories). It builds the agent image and the test image there.
  - **Worker.** The worker fixture passes `CORVO_AGENT_*` pointing at it, but only when Podman is present. Without Podman, the agent tests skip locally and fail when `CI` is set, and the other integration tests keep their worker.
  - **CI fallback.** When the runner has no systemd user session, the fixture's CI-only branch runs `sudo loginctl enable-linger` and sets `XDG_RUNTIME_DIR`. U1 decides whether that branch is needed.
  - **Timeout path.** AE4 is driven by `hatchet.runs.aio_cancel`, the same engine action a timeout sends (Dependencies), because a 15-minute timeout does not fit the 20-minute CI job.
  - **Teardown.** It removes every `corvo.managed` container in the test store.
  - **Health wait.** The worker fixture's health wait rises from 30 to 120 seconds, above KTD10's 45-second preparation and a cold first container start.

  The shared-group socket and the root-worker permissions exist only on the compose topology, which the manual proof covers (KTD18). Governs R24.
- KTD16. **Agent containers keep the default rootless network.** This instantiates the Key Decision on egress and inherits its label. (session-settled: user-approved — chosen over building the credential proxy now.) Conflict call-out: research found that the default network reaches more than the internet. It reaches the LAN, the cloud metadata endpoint and the compose stack's bridge addresses, through sockets the dedicated user opens on the host. Postgres and Hatchet still need credentials the container does not hold. The decision stands for these examples. `docs/agents.md` adds an owner-matched nftables rule as a production provisioning step: it drops the dedicated user's traffic to private, link-local and loopback ranges, with DNS allowed first. Every manual proof records what the container reached. Governs R15.
- KTD17. **The examples are `tone`, `dir-summary` and `dir-review`, all on `claude-haiku-5-5`.**
  - **`tone`** (R18) has no tools, `max_turns=3` and `max_budget_usd=0.05`. Its session classifies a text as `friendly`, `neutral` or `unfriendly`. Its output adds `friendly: bool` from `corvo.core.agents.tone`.
  - **`dir-summary`** (R19) mounts its working directory read-only. It uses `Read`, `Glob`, `Grep` and the custom tool `count_words`, whose logic is `corvo.core.agents.dir_summary.count_words`, with `max_turns=15` and `max_budget_usd=0.25`. Its output is a summary and a word count.
  - **`dir-review`** (R20) is a DAG. Step `summarize` spawns `dir-summary`, and step `judge`, with parent `summarize`, spawns `tone` on the summary. A core twin builds the review line from both outputs.
  - A task whose agent works in a directory declares its own input model in the worker module: the agent's input plus `workdir`. The agent receives `/workspace`.

  Governs R10, R18, R19, R20, R21.
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

### High-Level Technical Design

The pieces and who imports whom:

```mermaid
flowchart TB
  subgraph worker process
    WK[corvo.worker.agents.tone: thin task] --> CP[corvo.worker.agent_runtime: container piece]
    WK --> MD[corvo.agents.tone.models]
    CP --> EV[corvo.agents.envelope]
    CP --> FP[corvo.agents.fingerprint]
    MN[worker main: prepare agents] --> CP
  end
  CP -->|docker-py over the dedicated user's socket| PD[rootless Podman]
  PD --> CT
  subgraph agent container
    CT[corvo-agent runner] --> AG[corvo.agents.tone.agent]
    AG --> MD2[corvo.agents.tone.models]
    AG --> CK[corvo.core.agents.tone]
    AG --> SDK[claude_agent_sdk + bundled claude CLI]
  end
  SDK -->|HTTPS| API[Claude API]
```

Inside the worker process, nothing reaches `claude_agent_sdk`. The test of KTD2 holds that boundary.

One run, with the failure branches KTD4 and KTD8 decide:

```mermaid
flowchart TB
  S[task starts] --> R{retry_count above zero?}
  R -->|yes| RR[remove containers labelled with this task_run_id]
  RR --> RL{anything left behind?}
  RL -->|yes: worker-loss re-run| RX[fail, naming the re-assignment]
  RL -->|no: a requested replay| C
  R -->|no| C{agents configured and prepared?}
  C -->|no| F1[fail: agents unavailable, no session]
  C -->|yes| W{workdir resolves under root/workdirs?}
  W -->|no| F2[fail before any container]
  W -->|yes| D[frame the request with its deadline]
  D --> K[create, attach and start container: KTD6 spec; write the frame to stdin]
  K --> ST[read the attach stream: capped stderr lines to ctx.log, stdout up to one frame]
  ST --> WT{container exits or task is cancelled}
  WT -->|cancel or timeout| X[shielded cleanup by label]
  WT -->|exit| DR[read until the stream ends, at most DRAIN_TIMEOUT]
  DR --> RD{stdout frame: whole, at most 1 MiB, valid envelope?}
  RD -->|ok| V[log cost, turns, session ID; return output model]
  RD -->|failed, missing, invalid or OOM| F3[log what is known; fail]
  V --> CL[cleanup: close the attach socket, remove by label]
  F3 --> CL
  X --> CL
```

Worker start, KTD10 and KTD11:

```mermaid
flowchart TB
  M[corvo-worker main] --> Q{agent settings present?}
  Q -->|no| SV[start serving: agent tasks fail fast]
  Q -->|yes| I{image present?}
  I -->|no| DIS[disable agents, log reason]
  I -->|yes| P[probe container: report limits, caps, env names, fingerprint]
  P -->|mismatch or error| DIS
  P -->|match| SW[sweep own deployment: remove containers of ended runs]
  SW --> SV2[start serving with agents enabled]
  DIS --> SV3[start serving: agent runs fail with the reason]
```

### Output Structure

```text
src/corvo/agents/
  __init__.py
  envelope.py
  fingerprint.py
  runner.py
  session.py
  tone/
    __init__.py
    agent.py
    models.py
    prompts/
      system.md
  dir_summary/
    __init__.py
    agent.py
    models.py
    tools.py
    prompts/
      system.md
src/corvo/core/agents/
  __init__.py
  tone.py
  dir_summary.py
src/corvo/core/workflows/
  dir_review.py
src/corvo/worker/
  defaults.py
  worker.py
  agent_runtime/
    __init__.py
    spec.py
    containers.py
    startup.py
  agents/
    __init__.py
    tone.py
    dir_summary.py
  workflows/
    dir_review.py
tests/
  conftest.py
  test_import_boundaries.py
  agents/
    __init__.py
    isolation.py
    fake_claude.py
    fake/
      Containerfile
    test_fake_claude_contract.py
    test_runner.py
    test_envelope.py
    test_session.py
    tone/
      __init__.py
      test_agent.py
    dir_summary/
      __init__.py
      test_agent.py
      test_tools.py
  core/agents/
    __init__.py
    test_tone.py
    test_dir_summary.py
  core/workflows/
    test_dir_review.py
  worker/agent_runtime/
    __init__.py
    test_spec.py
    test_containers.py
    test_startup.py
  worker/agents/
    __init__.py
    test_tone.py
    test_dir_summary.py
  worker/workflows/
    test_dir_review.py
  integration/worker/
    podman.py
    test_podman.py
    test_agents.py
compose.agents.yaml
docs/agents.md
```

The tree is the expected shape. Each unit's **Files** list is authoritative.

### System-Wide Impact

- **The worker's start.** `main()` gains a bounded preparation step (KTD10). With agents unconfigured, startup is unchanged.
- **The compose stack.** `compose.yaml` is unchanged, and agents come only with the overlay (KTD18).
- **CI.** The integration job builds two Podman images and runs a rootless Podman inside pytest, within the existing 20-minute job (Risks).
- **Images.** The app image grows by the SDK's bundled CLI, about 250 MB (KTD13).
- **Settings and environment.** `.env.example` gains the `CORVO_AGENT_*` variables, each with a comment in its existing style.
- **The host.** Production gains a dedicated user, a socket and an nftables rule (KTD18). These are the repository's first host-level requirements.

### Risks

- **The CI runner's rootless cgroups.** A GitHub runner process may have no systemd user session, so limits may fail to apply. U1 proves the environment first, and the `sudo` branch of KTD15 is the fallback. Failing both is a stop condition.
- **`ubuntu-latest` moves to Ubuntu 26.04 (Podman 5.7, pasta) in November 2026.** The repository cannot pin the runner, so U1's test is the canary when it moves.
- **SDK churn.** Releases come almost daily, and Dependabot bumps the lock weekly. The exact pin, the fake-CLI contract test and the test image's build assertion catch protocol drift and a moved binary. `docs/agents.md` asks for a new Haiku proof when the bundled CLI's minor version changes.
- **The socket carries the dedicated user's full authority.** A compromised worker can start any container as that user: it can mount the user's own files, or retag the agent image. The probe's fingerprint cannot detect a tampered image, because the image reports it.
  - Until a reboot, a socket holder can also run host processes as the dedicated user, for example through a container that mounts the user's systemd bus. Those processes are bounded by that user's file permissions and by KTD16's owner-matched nftables rule.
  - It cannot persist across deploys, because KTD18 makes the user's login, systemd-user and `containers` configuration root-owned and the image is rebuilt and its ID recorded at each deploy.
- **Hatchet frees the slot before cleanup ends.** A third container can briefly overlap the cap of two, so the host needs memory for three agents.
- **A timed-out parent step does not cancel its child.** The in-container deadline bounds the child's session to `AGENT_EXECUTION_TIMEOUT`.
- **CI time.** Building the agent image (about 250 MB of CLI) and the test image adds minutes to the 20-minute job. The images cache across a session but not across CI runs.
- **Unverified Podman behavior on the compat path.** The default network on 4.9.3, and the compat API's handling of each KTD6 field. U1 proves both on CI and on Arch.

### Deferred to Implementation

- The network mode, if the compat default (`bridge`) proves unusable rootless on Podman 4.9.3. The alternative is the rootless default (`slirp4netns` on 4.9, `pasta` on 5 and later).
- Whether the CI `sudo` branch of KTD15 is needed. U1 decides.
- The fake CLI's canned outputs per schema title, and how the runner reads `run`'s input model.
- The exact `asyncio.timeout` values of each integration test.
- How KTD19's hook runs ahead of Hatchet's own SIGTERM handling, which `Worker.start()` installs: by wrapping that handler, or through the worker's lifespan.
- The bundled binary's path inside the test image, found at build time.
- Gaps in `types-docker` for the calls KTD6 makes, if any.

---

## Implementation Units

### U1. Rootless Podman fixture and its proof on CI

- **Goal:** the integration suite runs its own rootless Podman. On the CI runner and on Arch, it proves that a container built with KTD6's hardening and limits starts and that its limits apply.
- **Requirements:** R14, R15, R24; KTD5, KTD6, KTD15.
- **Dependencies:** none.
- **Files:**
  - Modify `pyproject.toml` and `uv.lock` (`docker` in runtime dependencies, `types-docker` in the dev group).
  - Create `tests/integration/worker/podman.py` (service start, availability check, CI branch).
  - Modify `tests/integration/worker/conftest.py` (session fixture).
  - Create `tests/integration/worker/test_podman.py`.
- **Approach:**
  1. The fixture starts `podman system service --time=0 unix://<root>/podman.sock` under a `mkdtemp` agent root, waits for the socket, and connects with `docker.DockerClient(base_url=...)`.
  2. When Podman is missing, it skips, unless `CI` is set, in which case it fails.
  3. With `CI` set and no user session, it applies the `sudo loginctl enable-linger` branch (KTD15).
  4. The test starts `python:3.14.7-slim` with KTD6's flags inline: this unit has no container piece yet, and U4's spec replaces the inline flags. Its command prints `/sys/fs/cgroup/memory.max`, `cpu.max`, `pids.max`, `CapEff` from `/proc/self/status`, and whether `/` is writable.
  5. Teardown stops the service and removes `corvo.managed` containers.
- **Execution note:** this unit is mostly an environment proof. Push it first and read the CI run's output before starting U2, and stop per the Goal Capsule when limits do not apply.
- **Patterns to follow:** `docker_available()` and the compose fixture in `tests/integration/worker/conftest.py`; Podman's system-service man page.
- **Test scenarios:**
  - A container with the full flag set exits 0, and its output shows `memory.max` of 2 GiB, `pids.max` of 256, a CPU quota of one CPU, `CapEff` of zero and a read-only root.
  - Writing to `/tmp` succeeds and writing to `/` fails inside the container.
  - A container labelled `corvo.managed=true` and `corvo.deployment=x` is listed by the two positive label filters and not by `corvo.deployment=y`.
  - Killing and force-removing a running `sleep` container leaves no container with its name.
- **Verification:** the test passes on the CI runner, with the CI branch either used or proven unneeded, and on Arch with Podman 6.1.4. The PR notes which network mode and Podman version each ran.

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

### U5. Operations: compose overlay, provisioning doc and the `tone` proof

- **Goal:** an operator can switch agents on for the compose stack from one document, and `tone` is proven once against real Haiku on that topology.
- **Requirements:** R12, R14, R16, R25; KTD11, KTD12, KTD16, KTD18.
- **Dependencies:** U4.
- **Files:**
  - Create `compose.agents.yaml` and `docs/agents.md`.
  - Modify `.env.example`.
  - Modify `README.md` (one line pointing at `docs/agents.md`).
- **Approach:**
  1. The overlay per KTD18, with a header comment in `compose.yaml`'s style. A `stop_grace_period` of 30 seconds lets the worker's graceful exit finish short work.
  2. `docs/agents.md`, in this order:
     - what agents need;
     - provisioning, step by step;
     - switching on the overlay;
     - rebuilding the agent image on every deploy;
     - the nftables rule;
     - credentials and their terms;
     - the manual proof runbook (KTD18);
     - when to repeat a proof (Risks).
  3. `.env.example` gains each `CORVO_AGENT_*` variable and the numeric `CORVO_AGENTS_GID` for `group_add`, each under a comment.
- **Execution note:** this is configuration and documentation. Prove it with the runbook on a provisioned machine, not with new unit tests.
- **Patterns to follow:** `compose.yaml` and `.env.example` comment style; the GitLab Runner rootless Podman setup for the provisioning steps.
- **Test scenarios:** Test expectation: none -- configuration and documentation. The proof is the manual Haiku run recorded in the PR.
- **Verification:** `docker compose -f compose.yaml -f compose.agents.yaml config` validates. Following `docs/agents.md` on Arch produces a worker that logs agents as enabled. The PR records `tone`'s Haiku run with KTD18's evidence.

### U6. The `dir-summary` agent: working directory and a custom tool

- **Goal:** a contributor can copy an agent that works in a directory it is given, with read-only file tools and one custom tool whose logic lives in the core.
- **Requirements:** R1, R3, R5, R10, R11, R19, R21, R23, R24, R25, AE6; KTD1, KTD3, KTD7, KTD17, KTD18.
- **Dependencies:** U4.
- **Files:**
  - Create `src/corvo/core/agents/dir_summary.py` and `tests/core/agents/test_dir_summary.py`.
  - Create `src/corvo/agents/dir_summary/__init__.py`, `models.py`, `agent.py`, `tools.py` and `prompts/system.md`.
  - Create `tests/agents/dir_summary/__init__.py`, `test_agent.py` and `test_tools.py`.
  - Create `src/corvo/worker/agents/dir_summary.py` and `tests/worker/agents/test_dir_summary.py`.
  - Modify `src/corvo/worker/agent_runtime/spec.py` and `tests/worker/agent_runtime/test_spec.py`, only if this unit's proof needs KTD6's executable-tmpfs fallback.
  - Modify `src/corvo/worker/worker.py` (`WORKFLOWS`).
  - Modify `tests/agents/fake_claude.py` (canned output and the tool call) and `tests/integration/worker/test_agents.py`.
- **Approach:**
  1. The core twin counts the words in a text over plain `str`.
  2. `tools.py` declares `count_words` with the SDK's `@tool` and builds the SDK MCP server. Its body calls the core twin.
  3. `agent.py` passes `cwd=workdir` and `tools=["Read", "Glob", "Grep"]`. Its `allowed_tools` holds the three file tools as permission rules scoped to `/workspace`, plus `mcp__dir_summary__count_words`. Reads elsewhere, such as `/proc/self/environ`, which holds the credential, are then denied.
  4. The task's input model adds `workdir` to the agent's input (KTD17).
  5. The fake drives `count_words` through `mcp_message` and puts the tool's result into its structured output, so the integration test proves the tool ran inside the container.
  6. Header comments add the custom-tool rule (logic in the core twin, the tool only adapts it) and the read-only working-directory rule.
- **Patterns to follow:** the `tone` agent from U3 and its task from U4; the SDK's `custom-tools.md`.
- **Test scenarios:**
  - The core twin counts `"one two  three\n"` as 3 and an empty text as 0.
  - Calling the `count_words` tool handler with a text returns the core twin's count in the SDK's tool-result shape.
  - With `query` replaced, `run` passes `cwd` equal to the given directory. Its options pass the isolation helper with exactly the three built-ins, scoped to `/workspace`, and the one custom tool allowed.
  - The isolation helper rejects options whose `allowed_tools` holds an unscoped `Read`, `Glob` or `Grep`.
  - The task rejects a `workdir` outside the root before any container call, through the container piece's check.
  - Integration: `dir-summary` on a directory under `<root>/workdirs` holding two small files returns the fake's summary and a word count computed by the core twin inside the container.
  - Integration: the fake reports that `/workspace` is mounted read-only.
- **Verification:** unit and integration suites pass. The PR records the Haiku proof per KTD18, including AE6 and tool denial: the session's answer ignores the planted CLAUDE.md, no skill loads, and the out-of-list tool request is denied.

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

---

## Verification Contract

| Gate | Command | Proves |
|---|---|---|
| Lint, format, types, lockfile | `uv run prek run --all-files` | ruff, ruff format, mypy strict over `src` and `tests` (with `types-docker`), `uv lock --check`, zizmor, actionlint |
| Unit tests, no Docker or Podman | `uv run pytest tests/test_import_boundaries.py tests/test_settings.py tests/agents tests/core tests/worker` | R2, R3, R6 to R12, R15 to R17, R22, R23; AE1, AE2, AE3, AE8 |
| Integration on compose and rootless Podman | `uv run pytest tests/integration/worker` (needs Docker and Podman) | R13 to R16, R19, R20, R24; AE3, AE4, AE5, AE7 |
| Coverage floor, as CI runs it | `uv run --locked --with coverage==7.16.2 coverage run --branch --source=src -m pytest`, then `uv run --locked --with coverage==7.16.2 coverage report --fail-under=90` | the in-process tests reach the runner, the agents and the container piece |
| Images | `docker build --target agent .`; `docker build .` still runs uvicorn by default; `podman build` as the dedicated user per `docs/agents.md` | KTD13, and that compose's plain builds are unchanged |
| CI | the org workflow `tnmn.io: python` on the pull request | the same gates with CI's pinned ruff and mypy, on the runner's Podman |
| Manual Haiku proof | the runbook in `docs/agents.md`, once per example | R11 (AE6), R14, R25, and KTD16's reachability record |

For a failing or stuck run, `skills/hatchet-cli/references/debug-run.md` and `trigger-and-watch.md` describe inspecting runs with the Hatchet CLI. `podman --url unix://<socket> ps --filter label=corvo.managed=true` lists agent containers. Both are debugging aids, not gates.

---

## Definition of Done

- Every gate in the Verification Contract passes locally, and CI passes on each pull request.
- `corvo-worker` registers `hello`, `greeting`, `greeting-rounds`, `tone`, `dir-summary` and `dir-review` through `WORKFLOWS`.
- No module outside `corvo.agents` imports `claude_agent_sdk`, and nothing the worker imports reaches it, as the boundary test proves.
- Each example file opens with the header comment R21 asks for, and `defaults.py` states KTD9's values with their reasons.
- No `corvo.managed` container remains after the test suite or after a proof, and no run directory is created at any point (agent-request-stdin plan, KTD6).
- Each example's PR records its Haiku proof with KTD18's evidence.
- No abandoned attempt remains in the diff: no unused helpers, commented-out code, or leftover tests or images from approaches that did not pan out.
- Per unit:
  - U1: the Podman proof passes on CI and Arch;
  - U2: an SDK import in the worker fails the suite by name;
  - U3: the agent image and the test image build, and the contract test passes;
  - U4: `tone`'s integration tests pass;
  - U5: a provisioned worker logs agents as enabled;
  - U6 and U7: their integration tests pass and their proofs are recorded.

---

## Split into parts

Each unit has its own plan, built to be enough on its own to deliver that unit; this file stays the whole picture. The parts ship as one `gh stack` stack, bottom to top: `docs/agents-skeleton-plan` (the plans), then one branch per part.

| Part | Plan | Branch | Depends on |
|---|---|---|---|
| U1 rootless Podman fixture | `docs/plans/2026-10-15-0020-feat-agents-skeleton-u1-podman-fixture-plan.md` | `feat/agents-u1-podman-fixture` | none |
| U2 boundaries, settings and guard | `docs/plans/2026-10-15-0020-feat-agents-skeleton-u2-boundaries-plan.md` | `feat/agents-u2-boundaries` | none |
| U3 `tone` agent and entrypoint | `docs/plans/2026-10-15-0020-feat-agents-skeleton-u3-tone-agent-plan.md` | `feat/agents-u3-tone-agent` | U2 |
| U4 container piece and `tone` task | `docs/plans/2026-10-15-0020-feat-agents-skeleton-u4-container-piece-plan.md` | `feat/agents-u4-container-piece` | U1, U3 |
| U5 operations | `docs/plans/2026-10-15-0020-feat-agents-skeleton-u5-operations-plan.md` | `feat/agents-u5-operations` | U4 |
| U6 `dir-summary` agent | `docs/plans/2026-10-15-0020-feat-agents-skeleton-u6-dir-summary-plan.md` | `feat/agents-u6-dir-summary` | U4 |
| U7 `dir-review` workflow | `docs/plans/2026-10-15-0020-feat-agents-skeleton-u7-dir-review-plan.md` | `feat/agents-u7-dir-review` | U6 |

The stack is linear in the order of the table. U2 sits above U1 even though it does not depend on it, so that U1's CI proof lands first.
