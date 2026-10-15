---
title: Agents Skeleton U1 Agent Worker Image, Seccomp Profile, Sandbox Wrapper and Isolation Gate - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u1-isolation-gate
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U1 Agent Worker Image, Seccomp Profile, Sandbox Wrapper and Isolation Gate - Plan

## Goal Capsule

- **Objective:** The `agent-worker` image exists, and a gate proves on the CI runner and on Arch that, inside it under compose's security options, the wrapper's bubblewrap starts clean, the real engine's sandbox runs a Bash call nested in it, a run's cgroup limits apply, and calls to other hosts fail fast.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 1 of 9 in stack order (unit U1). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** none; it sits on the plans branch in the stack. **Blocks:** every later part. U2 builds on this part directly.
- **Stop conditions:** stop and report, without working around it, when the gate shows on CI or on Arch that the SDK's sandbox cannot run nested in the outer bubblewrap, or that a run's cgroup limits do not apply. This is the whole plan's first stop condition. Also stop and ask when the SDK, Docker or bubblewrap behaves differently from this plan on the pinned versions.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- `docs/agents-skeleton-plan` (#31): the plans only, no code.
- From #32, which closes: 19840cd, the `[tool.uv] environments` block that resolves the lock for Linux only. Carry it with its Podman wording removed. Nothing else of #32 comes: no docker-py, no `types-docker`, no Podman fixture. Its `tests/integration/worker/test_podman.py`, still readable on the `feat/agents-u1-podman-fixture` branch, is the gate's shape.
- From #34: 5ee4c09's `claude-agent-sdk==0.2.167` pin and its lock, only. The three empty agent areas stay in U2.
- On `main`: `tests/integration/worker/conftest.py`, its session fixture and `docker_available`; the `Dockerfile`'s `app` stage.

## Product Contract

### Summary

Adds the `agent-worker` stage of the `Dockerfile` with its root entrypoint, the seccomp profile generated from Docker's with its diff test, the `corvo-agent-sandbox` wrapper, and a gate that runs the image under compose's security options and proves the isolation the rest of the plan relies on. It also carries the SDK pin and the Linux-only lock down from the closed Podman parts.

### Context

Every later part assumes that the two bubblewrap layers nest and that a run's cgroup limits hold inside the container. Claude Code issues report the SDK's sandbox failing nested, or under Ubuntu's AppArmor, and only the real runner can tell, so this part proves the environment before any agent code lands, as #32 did for Podman. R14, R15, R26 and R27 are completed by later parts: U4 gives each run its cgroup, U9 runs the wrapper from the agent worker, and U8 proves the escapes fail.

### Key Decisions

- **Each session's SDK engine runs in a fresh bubblewrap sandbox, and the SDK's sandbox with its credential scrub isolates every shell command inside it.** Measured together, the two layers stopped every escape a scripted shell command tried; either layer alone left some open. (session-settled: user-directed — chosen over the per-run Podman container, which left the forged result open, and over the SDK's sandbox alone, which leaves the worker's environment within every command's reach.) Governs R14, R15, R17, R26.
- **bubblewrap for both layers.** The SDK's sandbox already depends on it, and Flatpak, Claude Code and Codex use it. (session-settled: user-directed — chosen over runc, youki, nsjail and gVisor for the outer layer: each adds a second isolation tool without removing bubblewrap, and rootless gVisor drops cgroup limits and network namespaces.) Governs R14.
- **No VM.** The sessions share the host's kernel, as the Podman design did. (session-settled: user-directed — chosen over a dedicated VM for the agent worker and over a microVM per run.)
- **The agent worker is a compose service of its own.** (session-settled: user-approved — chosen over a systemd service on the host: it keeps one deploy path and the Hatchet engine's gRPC internal, at the cost of R27's container settings and a profile kept in step with Docker's.) Governs R13, R27.
- **Every tool corvo runs or ships has its license read at the source before it is adopted.** bubblewrap's files are LGPL-2.0-or-later and LGPL-2.1-or-later, and socat is GPL-2.0-only. Both run as separate, unmodified programs from distribution packages, which their licenses leave unrestricted. (session-settled: user-approved — chosen over permissive-only tools for the outer layer, after the license texts were read.)

### Requirements

**Isolation**

- R14. Each session's SDK engine runs in a fresh bubblewrap sandbox started for its run and ended with it, in a process namespace of its own and an environment that holds only what the session needs.
- R15. Every shell command a session runs goes through the SDK's sandbox with its subprocess credential scrub, and a command that cannot be sandboxed does not run. Command network reaches only an allowlist, which is empty for every example.
- R26. A session sees only its run's working directory, a temporary home and read-only system files, and its own cgroup limits its memory, CPU and processes. The working directory is read-only unless the agent declares that it writes to it.
- R27. The agent worker's container keeps a syscall filter: Docker's default profile plus only the calls bubblewrap needs. The profile is generated from the upstream one, and a CI check fails when the generated and the committed profiles differ.

### Scope Boundaries

Not in this part:

- No agent, task, session piece or settings field (U2 to U4): the gate drives the wrapper and the engine itself.
- No `agent-worker` compose service (U9): the gate runs the image with KTD23's options directly.
- No credential proxy (U5): the gate's session talks to `tests/agents/scripted_api.py`.

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- claude-agent-sdk 0.2.167 (2026-10-14, bundling CLI 2.1.300) ships only `manylinux_2_17` wheels, which `python:3.14.7-slim` satisfies, and bundles a native `claude` binary of about 250 MB. It releases almost daily. `query()` runs that engine as a subprocess over stdio, and `ClaudeAgentOptions.env` is merged over the inherited environment (`_internal/transport/subprocess_cli.py`), so only a sandbox that starts from an empty environment keeps the worker's variables out of the engine.
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

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD2. **R2 stays an AST test over `src/corvo`, with its transitive rule narrowed to the main profile.** Three rules stay: no module outside `corvo.agents` imports `claude_agent_sdk`; `corvo.agents` imports neither `hatchet_sdk` nor `corvo.worker`; `corvo.core` imports neither `corvo.agents` nor the SDK. The fourth rule now reads: no module the main profile imports reaches a module that imports the SDK. The main profile means `corvo.worker.worker`, `corvo.worker.profiles`, `corvo.worker.profiles.main`, `corvo.worker.tasks`, `corvo.worker.workflows`, `corvo.worker.agent_calls` and everything they import (KTD26); `corvo.server`, which will trigger agents through the same stubs, is held to the same rule. `corvo.worker.agents`, `corvo.worker.agent_runtime` and `corvo.worker.profiles.agents` reach the SDK through `corvo.agents`, and never import it themselves. A fifth rule keeps `corvo.worker.agent_runtime.sandbox`, and anything it imports, to the standard library: it runs as the wrapper process before it has joined its cgroup (KTD20). Governs R2, R6.
- KTD3. **Each agent sets the options it owns; the session supplies the isolation it does not.**
  - The agent passes `tools=[…]`, `allowed_tools` (its file tools as rules scoped to `session.cwd`, its other built-ins by name, its `mcp__<server>__<tool>` names), `permission_mode="dontAsk"`, `setting_sources=[]`, `skills=[]`, `strict_mcp_config=True`, `model`, `max_turns` and `max_budget_usd`.
  - The session supplies `cli_path`, `cwd`, `env` (KTD20) and `sandbox`. `sandbox` is `enabled`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands: false`, `failIfUnavailable: true`, and a network allowlist that is empty for every example.
  - SDK 0.2.167's `SandboxSettings` type lacks `failIfUnavailable`, which the bundled engine reads. `corvo.agents.session` builds that one dictionary, with the one typed cast it needs. A fake-CLI test asserts the key reaches the engine's `--settings`.
  - `tests/agents/isolation.py` asserts both halves on every agent's options, which keeps a corvo options builder out of the runtime code (R4). It also rejects `WebFetch` and `WebSearch` until a network decision covers what the engine itself may reach (KTD24). An agent that leaves out a session value still cannot run unsandboxed: KTD13 moves the engine out of the SDK's package, and the wrapper checks the sandbox settings itself (KTD20).

  Governs R10, R11, R15.
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
- KTD20. **The wrapper `corvo-agent-sandbox` is the SDK's `cli_path`, and it starts the engine in a fresh bubblewrap of its own.**
  - It lives in `corvo.worker.agent_runtime.sandbox`, which imports only the standard library (KTD2): a pure function builds bubblewrap's arguments, and `main` only checks and execs.
  - It reads its run's values from variables the session piece puts in `options.env`: `CORVO_SANDBOX_CGROUP`, `CORVO_SANDBOX_WORKDIR` (empty for an agent without one), `CORVO_SANDBOX_WRITES`, `CORVO_SANDBOX_ENGINE` and `CORVO_SANDBOX_TMPFS`. A call without them exits non-zero.
  - It refuses to start unless the `--settings` argument the SDK passes holds `sandbox.enabled`, `failIfUnavailable: true` and `allowUnsandboxedCommands: false`. An agent that left out `session.sandbox` therefore never runs.
  - It writes its PID into the run's `cgroup.procs`, and exits non-zero if it cannot, so nothing starts outside the cgroup.
  - It then execs `bwrap` with an **empty environment**. bubblewrap's own pid 1 inside the sandbox is a fork that never execs, so the environment `bwrap` was started with stays readable at `/proc/1/environ`; `--clearenv` alone would leave the worker's Hatchet token there. Its arguments:
    - `--unshare-all --unshare-cgroup --share-net --die-with-parent --new-session --clearenv`. `--unshare-cgroup` is explicit, because `--unshare-all` only tries it;
    - each allowed variable by `--setenv`: the placeholder's variable, `ANTHROPIC_BASE_URL`, `HOME`, `CLAUDE_CONFIG_DIR`, `PATH`, the SDK's own `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_AGENT_SDK_VERSION` and `CLAUDE_CODE_SDK_READS_SESSION_STATE`, and the isolation flags, which the wrapper sets itself whatever `options.env` held;
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

### Risks

- **The SDK's sandbox nested inside the outer bubblewrap on Ubuntu.** Claude Code issues report `apply-seccomp` and loopback setup failing nested or under AppArmor. It worked on Arch, kernel 7.2, bubblewrap 0.12 and Debian's packaged bubblewrap. U1's gate runs it on CI first, and the Goal Capsule stops on failure. `enableWeakerNestedSandbox` is not a fallback, because it gives the engine the outer `/proc`.
- **Sessions share the host's kernel and may create user namespaces.** A kernel bug reachable from an unprivileged user namespace would defeat every layer above it, which is the price of no VM. KTD23 closes the netfilter route most such exploits used, and `docs/agents.md` asks for a patched kernel.
- **AppArmor on `ubuntu-latest`**, including its move to 26.04. U1 finds which of KTD15's two CI adjustments is needed. The runner image is the canary when it moves.
- **The seccomp profile goes stale.** Moby's profile changes a few times a year, and a stale copy silently misses new blocks. The vendored tag, the diff test and the doc's refresh step make a refresh deliberate, not automatic.
- **CI time.** Building the `agent-worker` image and running a real engine against the scripted API add minutes to the 20-minute integration job; the image caches within a session but not across runs.

### Deferred to Implementation

- Which CI adjustment KTD15 needs, if any. U1 decides.
- How the wrapper opens the working directory without following a symlink at any step: per-component `O_NOFOLLOW` opens, or a check of the opened descriptor's real path.

## Implementation Units

### U1. The agent worker's image, its seccomp profile, the sandbox wrapper and the isolation gate on CI

- **Goal:** the `agent-worker` image exists. On the CI runner and on Arch, a gate proves four things inside it under compose's security options: the wrapper's bubblewrap starts clean, the real engine's sandbox runs a Bash call nested in it, a run's cgroup limits apply, and calls to other hosts fail fast.
- **Requirements:** R14, R15, R26, R27; KTD2, KTD13, KTD15, KTD20, KTD23, KTD24.
- **Dependencies:** none.
- **Files:**
  - Modify `pyproject.toml` and `uv.lock`: `claude-agent-sdk==0.2.167`, the Linux-only `[tool.uv] environments` block without its Podman wording, and the `corvo-agent-sandbox` script.
  - Modify `Dockerfile` (`agent-worker` stage).
  - Create `deploy/agent-worker/entrypoint.sh`, `deploy/agent-worker/seccomp.py`, `deploy/agent-worker/seccomp-moby-default.json` and `deploy/agent-worker/seccomp.json`.
  - Create `src/corvo/worker/agent_runtime/__init__.py` and `src/corvo/worker/agent_runtime/sandbox.py`.
  - Create `tests/test_seccomp_profile.py`, `tests/worker/agent_runtime/__init__.py` and `tests/worker/agent_runtime/test_sandbox.py`.
  - Create `tests/agents/__init__.py`, `tests/agents/scripted_api.py`, `tests/integration/worker/test_isolation_gate.py` and the gate's driver under `tests/integration/worker/gate/`.
- **Approach:**
  1. The `agent-worker` stage and its entrypoint per KTD13, with the closing `FROM app` kept.
  2. The profile generator and its diff test per KTD23.
  3. The wrapper per KTD20, its argument builder a pure function over the standard library.
  4. The gate builds the image, then runs it with KTD23's options and the gate driver as its command, with the tests directory mounted read-only. The driver does four things:
     - creates a run cgroup;
     - runs a probe command through the wrapper;
     - runs one real-engine session whose scripted turn is a Bash `echo`;
     - runs a memory and fork hog in a run cgroup.
  5. The gate applies KTD15's CI-only branch when bubblewrap is refused, and logs which branch it used.
- **Execution note:** this unit is mostly an environment proof. Push it first, read the CI run's output before starting U2, and stop per the Goal Capsule when the nested sandbox or the limits fail.
- **Patterns to follow:** the removed `tests/integration/worker/test_podman.py`, a module-scoped proof with a session log line that describes the environment; `tests/integration/worker/conftest.py`'s `docker_available`.
- **Test scenarios:**
  - The generated profile equals the committed one, and changing the vendored copy's allow list makes the test fail.
  - The generated profile allows `unshare` and `pivot_root`. It still denies `keyctl`, `add_key`, `request_key`, `perf_event_open`, `kexec_load` and `open_by_handle_at`, and denies a `NETLINK_NETFILTER` socket.
  - The wrapper's arguments carry `--unshare-all`, `--unshare-cgroup`, `--share-net`, `--die-with-parent`, `--new-session` and `--clearenv`, no `/sys`, and only the allowlisted variables by `--setenv`. A stray `ANTHROPIC_API_KEY` or `CLAUDE_CODE_SYNC_PLUGIN_INSTALL` in its input environment is left out, and the placeholder's variable is kept.
  - The isolation flags are set to KTD20's values even when the input environment sets them otherwise.
  - The environment the wrapper hands to `bwrap`'s exec is empty.
  - The working directory is bound read-only by descriptor, or read-write when `CORVO_SANDBOX_WRITES` is set. With no working directory, the engine starts in its home. No other host path is writable.
  - A working directory replaced by a symlink to `/proc` after the task's check is refused, with no exec.
  - The wrapper exits non-zero, with no exec, when its per-run variables are missing, when its cgroup cannot be joined, or when `--settings` lacks `failIfUnavailable: true` or sets `allowUnsandboxedCommands`.
  - Gate: inside the sandbox, every `/proc/*/environ`, `/proc/1/environ` included, holds only the allowed names, `/proc` lists only the sandbox's own processes, and `/sys` is absent.
  - Gate: the real engine's session, against the scripted API, completes with the Bash call's output in its result and the call sandboxed. It finishes within 30 seconds, with the internal network giving it no route out.
  - Gate: a hog in a run cgroup stops at `pids.max` and is killed at `memory.max`, with `oom_kill` counted, while the driver's own cgroup is untouched.
  - Gate: the cgroup2 mount carries `nsdelegate`.
  - Gate: inside the image as uid 1000, `query()` with options that leave out `cli_path` raises `CLINotFoundError`.
- **Verification:** the gate passes on the CI runner and on Arch. The pull request notes the bubblewrap version, the kernel, and which CI adjustment, if any, each host needed.

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict, lockfile, zizmor, actionlint.
- `uv run pytest tests/test_seccomp_profile.py tests/worker/agent_runtime`: the profile's diff and the wrapper's arguments, no Docker.
- `uv run pytest tests/integration/worker/test_isolation_gate.py`: the gate, which needs Docker.
- `docker build --target agent-worker .`, and `docker build .` still runs uvicorn by default.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- The gate passes on the CI runner and on Arch.
- The pull request notes the bubblewrap version, the kernel, and which CI adjustment, if any, each host needed, so U9's fixture and `docs/agents.md` can use it.
- No Podman, docker-py or `types-docker` remains in the diff.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u1-isolation-gate`, on top of `docs/agents-skeleton-plan`, pull request new. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
