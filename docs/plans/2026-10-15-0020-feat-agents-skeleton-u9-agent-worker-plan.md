---
title: Agents Skeleton U9 Agent Worker Start, Compose Service and Tone End to End - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u9-agent-worker
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U9 Agent Worker Start, Compose Service and Tone End to End - Plan

## Goal Capsule

- **Objective:** `tone` runs end to end on Hatchet in the `agent-worker` container. Timeout, cancel, SIGTERM, an OOM and a missing profile each end as the Product Contract says, and leave no process behind.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 5 of 9 in stack order (unit U9). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U4; it sits on `feat/agents-u4-session-piece` in the stack. **Blocks:** U8 builds on this part directly; U5 to U7 through it.
- **Stop conditions:** stop and ask when the gate's CI adjustment from U1 no longer holds in compose, or when Hatchet's behavior for a run of a never-registered task contradicts AE10.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U1: the `agent-worker` stage, its entrypoint, the seccomp profile and the gate's CI adjustment.
- U2: `serve`, the `agents` profile and the registration test.
- U4: the session piece and the `tone` task.
- `src/corvo/worker/agent_runtime/startup.py` on `feat/agents-u4-container-piece`: `Disabled`, the bounded `prepare` and the SIGTERM hook.
- On `main`: `tests/integration/worker/conftest.py`'s session fixture and `write_env_file`, and `tests/integration/worker/test_workflows.py`'s triggering by name and `finished_tasks` polling.

## Product Contract

### Summary

Adds the agent worker's start: the `agents` profile's `before_start` with KTD10's checks and sweep, its `on_sigterm` with KTD19's hook, the `agent-worker` compose service on the internal `agents` network, and the integration tests that run `tone` end to end.

### Context

This is the first time the pieces run together on the real Hatchet in the real container. The scripted API stands in for the proxy until U5. R17 and R28 are completed here.

### Key Decisions

- **Each session's SDK engine runs in a fresh bubblewrap sandbox, and the SDK's sandbox with its credential scrub isolates every shell command inside it.** Measured together, the two layers stopped every escape a scripted shell command tried; either layer alone left some open. (session-settled: user-directed — chosen over the per-run Podman container, which left the forged result open, and over the SDK's sandbox alone, which leaves the worker's environment within every command's reach.) Governs R14, R15, R17, R26.
- **bubblewrap for both layers.** The SDK's sandbox already depends on it, and Flatpak, Claude Code and Codex use it. (session-settled: user-directed — chosen over runc, youki, nsjail and gVisor for the outer layer: each adds a second isolation tool without removing bubblewrap, and rootless gVisor drops cgroup limits and network namespaces.) Governs R14.
- **The agent worker is a compose service of its own.** (session-settled: user-approved — chosen over a systemd service on the host: it keeps one deploy path and the Hatchet engine's gRPC internal, at the cost of R27's container settings and a profile kept in step with Docker's.) Governs R13, R27.

### Requirements

**Isolation**

- R13. Agent tasks run only on a dedicated agent worker, which holds the Hatchet token but neither the database password nor the Claude credential.
- R14. Each session's SDK engine runs in a fresh bubblewrap sandbox started for its run and ended with it, in a process namespace of its own and an environment that holds only what the session needs.
- R17. One piece of the agent worker starts, bounds and ends each session's sandbox, and every agent task uses it. When Hatchet times out or cancels an agent task, no process of that run survives.
- R26. A session sees only its run's working directory, a temporary home and read-only system files, and its own cgroup limits its memory, CPU and processes. The working directory is read-only unless the agent declares that it writes to it.
- R28. When the agent worker starts and its isolation cannot apply in full, it logs which part failed (bubblewrap, the SDK's sandbox, the cgroup delegation or the proxy) and exits without registering agent tasks, so its runs wait for an agent worker that can isolate them.

**Tests**

- R24. The integration suite runs every example on the real Hatchet and real bubblewrap with the SDK's engine replaced, including the end of a run on timeout. It creates its working directories below `<root>/workdirs` (R5), not in pytest's temporary directories.

### Acceptance Examples

- AE3. **Covers R8.** **Given** an agent that reaches its turn limit, **when** its task finishes, **then** the run is marked failed without a retry, and its log holds the cost, turns and session ID.
- AE4. **Covers R17, R24.** **Given** an agent run that is still working, **when** the task's execution timeout passes, **then** its sandbox ends and no process of that run remains.
- AE9. **Covers R26.** **Given** a session that allocates memory past its limit, **when** the limit is reached, **then** that run fails, and the agent worker and the other runs keep going.
- AE10. **Covers R27, R28.** **Given** an agent worker whose container lacks R27's profile, so bubblewrap cannot create its namespaces, **when** it starts, **then** it logs that bubblewrap failed and exits without registering agent tasks, and an agent run triggered meanwhile stays queued.

### Scope Boundaries

Not in this part:

- No credential proxy (U5): the agent worker's proxy address points at `scripted-api`.
- No isolation probe (U8).
- No `docs/agents.md` (U5); this part records the never-registered run's behavior for it.

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- hatchet-sdk 1.42.1 cancels a running async task's asyncio task on cancellation and timeout (`hatchet_sdk/worker/runner/runner.py:920-944`). It sets the context's cancellation flag, sleeps one second, cancels the task, and frees the task's slot without waiting for its `finally`. Engine timeout and cancel reach the worker as the same `CANCEL_STEP_RUN` action. The SDK also has an unpinned `claude` extra and `mcp_tool` (`hatchet_sdk/runnables/workflow.py:831`), neither used here.
- The engine re-queues a task whose worker misses heartbeats for 30 seconds as an internal failure, up to `MaxInternalRetryCount` times, which is 10, whatever its `retries` (engine v0.110.5 `pkg/repository/task.go`, `pkg/repository/sqlcv1/tasks.sql`). `ctx.retry_count` is above zero on such a re-run.
- Hatchet API tokens are scoped per tenant, with no per-worker or narrower token (Hatchet security docs). A task goes only to workers that registered it, and worker labels attract tasks without keeping others away (Hatchet worker and worker-affinity docs). In hatchet-sdk 1.42.1, `DesiredWorkerLabel.required` defaults to `False` (`hatchet_sdk/types/labels.py:69`), so isolation by registration is the only exclusion this plan relies on.
- Ubuntu 24.04 and later restrict unprivileged user namespaces through AppArmor (`kernel.apparmor_restrict_unprivileged_userns`), and the sandboxing doc says bubblewrap needs an AppArmor profile there. Whether that blocks bubblewrap on CI's `ubuntu-latest` runner, on the host or inside Docker there is unverified.
- CI runs the organization's reusable `python.yml`, which allows no services and no setup steps. It runs `uv run --locked … pytest` in a 20-minute job, with passwordless `sudo` on GitHub-hosted runners. Any sandbox setup in CI happens inside pytest.

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD10. **Before the agent worker registers, the `agents` profile's `before_start` checks its isolation within 45 seconds, and a failure exits the process.**
  - **The checks, in order:**
    1. Settings: `CORVO_AGENT_ROOT` and the proxy address are set.
    2. Credentials: none of `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` or `CLAUDE_CODE_OAUTH_TOKEN` is in the worker's environment (R13). Sessions get their placeholder through `options.env` alone.
    3. Cgroup delegation: the cgroup2 mount carries `nsdelegate`, so a session that mounts its own cgroup namespace cannot rewrite its limits; then create a probe cgroup under `CORVO_AGENT_CGROUP_ROOT`, write its limits, and remove it.
    4. bubblewrap: the wrapper's sandbox, in a probe cgroup, runs a check. Every `/proc/*/environ` it can read holds only the allowed names, bubblewrap's own pid 1 included. Its `/proc` shows only its own processes, `/sys` is absent, and the worker's files are absent.
    5. The SDK's sandbox: inside that sandbox, a nested `bwrap` with user and network namespaces starts, and `socat` is present.
    6. The proxy: a TCP connect to it succeeds, retried within the bound, since compose may start it later.
  - **Then:** kill and remove every `run-*` cgroup a previous run left (KTD21), log the result, and return to `serve`, which creates the Hatchet worker and starts it (KTD26).
  - **On failure:** log `agents refused: <part>: <detail>`, with the part named as R28 lists it plus `settings` and `credential in environment`, and exit with status 1 before the Hatchet worker exists. Compose restarts the service with backoff, so a passing cause clears on its own and a lasting one shows as a restarting container.
  - **What it does not prove:** step 5 is weaker than a real engine's sandbox start. U1's gate and U8's probe prove that with the real engine on CI.

  Governs R13, R14, R15, R28; AE10.
- KTD13. **The agent worker's image is an `agent-worker` stage of the repository's `Dockerfile`, entered as root only to delegate cgroups.**
  - The stage builds `FROM app`. It installs Debian trixie's `bubblewrap` and `socat`, creates the user `agent` with uid 1000, and strips every setuid and setgid bit from the image. It moves the SDK's bundled engine out of the SDK's package to `/opt/corvo/engine/claude`, which `CORVO_AGENT_ENGINE` names. That path is off `PATH` and outside every place the SDK's CLI discovery looks, `/usr/local/bin/claude` and `~/.local/bin/claude` among them. An agent that forgets `cli_path` then fails with the SDK's `CLINotFoundError` instead of starting the engine outside any sandbox with the worker's environment. Its entrypoint is `deploy/agent-worker/entrypoint.sh`, and `CMD ["corvo-worker"]`; compose sets `CORVO_WORKER_PROFILE=agents` (KTD26).
  - The entrypoint runs as root and does five things:
    1. moves the container's processes into an `init` cgroup;
    2. enables `+cpu +memory +pids` for the subtree;
    3. creates `agents/`, giving uid 1000 only the directory, `cgroup.procs`, `cgroup.threads` and `cgroup.subtree_control`, with `agents/worker` inside;
    4. moves itself into `agents/worker`;
    5. runs `exec setpriv --reuid=1000 --regid=1000 --clear-groups --no-new-privs` with every capability dropped, on its arguments.
  - Compose runs the service with `init: true`, so tini reaps the processes a cancelled session leaves. It also sets the container's own memory and pids limits for cap + 1 sessions plus the worker, a backstop under the per-run cgroups. Its healthcheck runs as uid 1000.
  - The file still ends with a closing `FROM app`, so `docker build .` and compose's `build: .` still produce the app image.
  - `claude-agent-sdk==0.2.167` stays an exact-pinned runtime dependency; `docker` and `types-docker` never enter this stack.
  - `setpriv` comes from the base image's util-linux, GPL-2.0-or-later, and is run, not linked. bubblewrap's and socat's licenses are covered by the Key Decision.

  Governs R13, R14, R26, R27.
- KTD15. **The integration suite runs the agent worker in its compose service, on the stack the session fixture already starts.**
  - The fixture adds `agent-worker` (built), `claude-proxy` and `scripted-api` to the services it brings up. The overlay `tests/integration/worker/compose.yaml` does four things: points the proxy's upstream at `scripted-api`, mounts a `tempfile.mkdtemp` agent root, mounts the fake CLI, and sets `CORVO_AGENT_ENGINE`. Directories the tests create there are made readable by uid 1000, since the CI runner's user is uid 1001.
  - The main worker stays a host subprocess, as today.
  - **CI-only branch.** When the agent worker logs `agents refused: bubblewrap` and the host reports `kernel.apparmor_restrict_unprivileged_userns=1`, the fixture sets it to 0 through `sudo`. If Docker's `docker-default` AppArmor profile still blocks bubblewrap, the overlay adds `apparmor=unconfined`. U1 decides which is needed, and production on Arch needs neither.
  - Agent integration tests fail when `CI` is set and the stack cannot isolate, and skip locally without Docker.
  - AE4 is driven by `hatchet.runs.aio_cancel`, the engine's own timeout action, because a 15-minute timeout does not fit the 20-minute CI job.

  Governs R24, R27, R31.
- KTD18. **Agents come with the stack: `compose.yaml` runs the agent worker and the proxy, and `docs/agents.md` is the repository's first operations doc.**
  - Compose services:
    - `agent-worker`: the `agent-worker` stage with `CORVO_WORKER_PROFILE=agents` (KTD26), KTD23's security options, `init: true`, the agent root volume, the Hatchet token and no database variable;
    - `claude-proxy`: the credential and its kind, required with `:?`;
    - an internal `agents` network (KTD24).
  - `docs/agents.md` covers, in order:
    - what agents need from the host: cgroup v2, a Docker at or past the profile's tag, and on Ubuntu the AppArmor settings U1 found;
    - credentials and their terms: an API key from a Console workspace with a spend limit, and for an OAuth token the data terms that apply to the code it sends;
    - that a session's output and run log carry repository content by design, so a workflow that publishes them treats them as confidential;
    - keeping the host kernel patched, since sessions may create user namespaces;
    - the first deployment, when the engine has never seen an agent task registered (U9 checks how a run triggered then behaves);
    - sizing, at cap + 1 sessions of `AGENT_MEMORY` plus the worker;
    - what each refusal reason means and its fix;
    - how an OOM or a dead proxy shows in the run log;
    - the re-run rule and its recovery (KTD8);
    - the working-directory rules (KTD7);
    - refreshing the seccomp profile (KTD23);
    - the manual Haiku proof runbook and its evidence: cost, turns, session ID, peak processes, and what the session reached.

  Governs R12, R13, R16, R25, R27.
- KTD19. **When the agent worker gets SIGTERM, the `agents` profile's `on_sigterm` stops taking runs, then kills its in-flight sessions, then hands over to Hatchet's graceful exit.**
  - The hook first marks agents refused, so a run assigned in the gap fails at once with "worker stopping". It then writes `cgroup.kill` for every in-flight run.
  - Those runs fail while the worker is alive, so the engine records a failure instead of re-queuing them. `stop_grace_period` is 30 seconds.
  - A SIGKILL, an OOM kill of the worker or a host crash skips the hook; KTD8's re-run rule covers those.
  - (session-settled: user-directed — chosen over sizing host memory for twice the cap plus one: a redeploy must not leave paid sessions running.)

  Governs R17.
- KTD21. **Each run gets a cgroup, `<agent_cgroup_root>/run-<task_run_id>`, made before the session and removed after it.**
  - It sets `memory.max` to `AGENT_MEMORY`, `memory.swap.max` to 0, `memory.oom.group` to 1, `cpu.max` from `AGENT_CPUS` and `pids.max` to `AGENT_PIDS_LIMIT`.
  - After the end, the piece reads `memory.events`. A non-zero `oom_kill` turns the failure's reason into `out of memory`, in the error and in the run log (AE9).
  - The worker owns each `run-*` cgroup's files, and a session runs as the same uid. What keeps a session from rewriting its own limits is the cgroup namespace bubblewrap gives it, under `nsdelegate` (KTD10), and the absence of `/sys` in its sandbox. U8 tries both ways around them.
  - Leftovers come only from a cleanup that failed while the worker lived, because a worker restart is a container restart and drops the subtree. KTD10 sweeps them at start.

  Governs R17, R26.
- KTD23. **The agent worker's seccomp profile is generated from Docker's, vendored at a pinned tag, and checked in CI.**
  - `deploy/agent-worker/seccomp-moby-default.json` is moby's `vendor/github.com/moby/profiles/seccomp/default.json` at `docker-v29.7.2`. `deploy/agent-worker/seccomp.py` adds `clone`, `unshare`, `mount`, `umount2`, `pivot_root` and `setns` to its allow rule, and writes `deploy/agent-worker/seccomp.json`.
  - It also denies `socket(AF_NETLINK, …, NETLINK_NETFILTER)`. Allowing user namespaces opens nf_tables to every command, the kernel area most unprivileged-namespace exploits have used, such as CVE-2024-1086. bubblewrap needs only `NETLINK_ROUTE`, and U1 confirms the SDK's sandbox needs nothing more. This is narrower than R27's floor, never wider.
  - `tests/test_seccomp_profile.py` regenerates the profile in memory and fails on any difference from the committed one. It also fails when `keyctl`, `add_key`, `request_key`, `perf_event_open`, `kexec_load` or `open_by_handle_at` become allowed, or when the netfilter rule is gone.
  - Compose sets `seccomp=deploy/agent-worker/seccomp.json`, `systempaths=unconfined` and `writable-cgroups=true` on `agent-worker` only. Refreshing the vendored copy when the host's Docker moves to a new major is a step in `docs/agents.md`.

  Governs R27.
- KTD24. **The `agents` compose network is internal, and only the proxy also reaches the outside.**
  - Its members are `agent-worker`, `claude-proxy` and `hatchet-engine`, and `scripted-api` in tests. `claude-proxy` also joins the default network for its upstream.
  - The engine shares the agent worker's network namespace (`--share-net`). It reaches those services, and on loopback the worker's healthcheck and other runs' sandbox proxies. (session-settled: user-directed — chosen over a network namespace of the engine's own: none of that reach gives an engine anything usable, which U8 asserts, and the separate namespace is follow-up work in #38.) Shell commands get their own namespace from the SDK's sandbox, with an empty allowlist (R15).
  - The engine also calls `api.anthropic.com` directly for its fast-mode check, and its other hosts are off by KTD20's flags. With no route out, those calls fail; U1's gate asserts they fail fast and never stall a session.
  - The engine's own reach is measured, not assumed: U8's engine-layer probe records it (KTD25).

  Governs R15, R16.
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

- **AppArmor on `ubuntu-latest`**, including its move to 26.04. U1 finds which of KTD15's two CI adjustments is needed. The runner image is the canary when it moves.
- **CI time.** Building the `agent-worker` image and running a real engine against the scripted API add minutes to the 20-minute integration job; the image caches within a session but not across runs.

### Deferred to Implementation

- How KTD19's hook runs ahead of the SIGTERM handler that Hatchet's `Worker.start()` installs: by wrapping that handler, or through the worker's lifespan.
- Whether the engine queues or rejects a run of a task name no worker has registered yet. U9 checks it; AE10's "stays queued" is tested after one successful start, and `docs/agents.md` states the first-deployment case.

## Implementation Units

### U9. The agent worker's start, its compose service and `tone` end to end

- **Goal:** `tone` runs end to end on Hatchet in the `agent-worker` container. Timeout, cancel, SIGTERM, an OOM and a missing profile each end as the Product Contract says, and leave no process behind.
- **Requirements:** R13, R14, R17, R24, R26, R28; AE3, AE4, AE9, AE10; KTD10, KTD15, KTD18, KTD19, KTD24, KTD26.
- **Dependencies:** U4.
- **Files:**
  - Create `src/corvo/worker/agent_runtime/startup.py` and `tests/worker/agent_runtime/test_startup.py`.
  - Modify `src/corvo/worker/profiles/agents.py` (`before_start` and `on_sigterm`) and `tests/worker/test_profiles.py`.
  - Modify `compose.yaml`:
    - the `agent-worker` service, with `CORVO_WORKER_PROFILE=agents`, its healthcheck as uid 1000, `HATCHET_CLIENT_WORKER_HEALTHCHECK_ENABLED` and `HATCHET_CLIENT_HOST_PORT=hatchet-engine:7070`;
    - the `agents` network;
    - `hatchet-engine` on both `default` and `agents`.
  - Modify `.env.example` with every variable the new service interpolates.
  - Modify `tests/integration/worker/compose.yaml` (`scripted-api`, the agent root, the fake CLI, the agent worker's proxy address on `scripted-api`).
  - Modify `tests/integration/worker/conftest.py` (services, `write_env_file`'s new variables, the agent root, KTD15's CI-only branch) and create `tests/integration/worker/test_agents.py`.
- **Approach:**
  1. `startup.py` checks and sweeps per KTD10, and installs KTD19's hook, keeping `Disabled` as the refusal's reason.
  2. The `agents` profile's `before_start` runs the checks and the sweep, and its `on_sigterm` installs the hook; `serve` from U2 runs both in order (KTD26).
  3. The `agent-worker` compose service per KTD13 and KTD18, with the scripted API standing in for the proxy until U5.
  4. The session fixture waits on the agent worker's healthcheck, so `up --wait` returns only after its checks and its registration.
- **Patterns to follow:** `src/corvo/worker/agent_runtime/startup.py` on `feat/agents-u4-container-piece`; `tests/integration/worker/test_workflows.py` for triggering by name and `finished_tasks` polling.
- **Test scenarios:**
  - Each failing check logs `agents refused: <part>` and exits with status 1 before a Hatchet worker exists. That holds for the missing `nsdelegate` and for a credential variable in the environment, which refuses as `credential in environment`.
  - All checks passing sweeps two leftover `run-*` cgroups, and an unreachable proxy is retried within the bound.
  - The SIGTERM hook marks agents refused before it kills, kills every in-flight cgroup and none other, then hands over to the previous handler.
  - Integration: `tone` triggered by name returns the fake's canned verdict with `friendly` true, and no `run-*` cgroup remains.
  - Covers AE3. Integration: `tone` with `fake:max-turns` fails without a retry, and its run log holds the cost, turns and session ID.
  - Covers AE4. Integration: `tone` with `fake:hang`, cancelled through `aio_cancel` once running, leaves no process of that run within 5 seconds.
  - Covers AE9. Integration: `tone` with `fake:hog` fails as `out of memory`, and a second run started alongside completes.
  - Integration: SIGTERM to the agent worker during a `fake:hang` run ends that run `FAILED`, and the run is not re-queued.
  - Covers AE10. Integration, after one successful start: an agent worker restarted without the seccomp profile logs `agents refused: bubblewrap`, exits, and registers nothing. A `tone` run triggered meanwhile stays queued.
  - Integration: the engine's behavior for a run of an agent task triggered before any agent worker ever registered is recorded, for `docs/agents.md`.
- **Verification:** the unit and integration suites pass on compose, and coverage of `src` stays at 90% or above.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/worker`: unit tests, no Docker.
- `uv run pytest tests/integration/worker`: integration on compose, which needs Docker.
- `docker compose config` validates.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- `tone`'s integration tests pass, and coverage of `src` stays at 90% or above.
- No `run-*` cgroup and no session process remains after the suite.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u9-agent-worker`, on top of `feat/agents-u4-session-piece`, pull request new. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
