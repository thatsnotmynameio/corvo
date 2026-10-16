---
title: Agents Skeleton U8 Isolation Probe - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u8-isolation-probe
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U8 Isolation Probe - Plan

## Goal Capsule

- **Objective:** CI proves AE5 with the operating system enforcing it: a session whose shell commands follow a scripted prompt injection gets nothing it tries, and what an escape into the engine would reach is measured.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 6 of 9 in stack order (unit U8). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U9; it sits on `feat/agents-u9-agent-worker` in the stack. **Blocks:** U5 builds on this part directly and re-runs the probe through the proxy.
- **Stop conditions:** stop and report on any `LEAKED` line from the shell layer, rather than weakening the probe; this is the whole plan's second stop condition. An engine-layer reach beyond KTD25's list, or a listed one that gives something usable, goes to the owner before the plan moves on (KTD24, #38).

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U1: `tests/agents/scripted_api.py` and the gate's driver.
- U9: the `agent-worker` compose service, the integration overlay and `serve`.
- The brainstorm's measured `probe.sh` and Messages API stand-in (Dependencies), on which this probe's attempts are modeled.

## Product Contract

### Summary

Adds the isolation probe: a test-only agent worker that runs the real engine against a scripted Messages API, a session whose Bash, Read and Grep calls try each escape of AE5, and a second probe that measures what an escape into the engine would reach.

### Context

R31 asks for an automated proof of AE5 with the real engine in the real sandbox. It runs before the proxy exists, against `scripted-api` directly; U5 runs it again through `claude-proxy`.

### Key Decisions

- **Each session's SDK engine runs in a fresh bubblewrap sandbox, and the SDK's sandbox with its credential scrub isolates every shell command inside it.** Measured together, the two layers stopped every escape a scripted shell command tried; either layer alone left some open. (session-settled: user-directed — chosen over the per-run Podman container, which left the forged result open, and over the SDK's sandbox alone, which leaves the worker's environment within every command's reach.) Governs R14, R15, R17, R26.
- **bubblewrap for both layers.** The SDK's sandbox already depends on it, and Flatpak, Claude Code and Codex use it. (session-settled: user-directed — chosen over runc, youki, nsjail and gVisor for the outer layer: each adds a second isolation tool without removing bubblewrap, and rootless gVisor drops cgroup limits and network namespaces.) Governs R14.
- **The agent worker is a compose service of its own.** (session-settled: user-approved — chosen over a systemd service on the host: it keeps one deploy path and the Hatchet engine's gRPC internal, at the cost of R27's container settings and a profile kept in step with Docker's.) Governs R13, R27.
- **The Claude credential lives in a proxy and the agent worker's egress is cut, from the first run.** Without both, a session that reads its own engine's credential could send it out. (session-settled: user-approved — chosen over deferring the proxy and `--network none`, as the Podman design did.) Governs R12, R16.

### Requirements

**Isolation**

- R13. Agent tasks run only on a dedicated agent worker, which holds the Hatchet token but neither the database password nor the Claude credential.
- R14. Each session's SDK engine runs in a fresh bubblewrap sandbox started for its run and ended with it, in a process namespace of its own and an environment that holds only what the session needs.
- R15. Every shell command a session runs goes through the SDK's sandbox with its subprocess credential scrub, and a command that cannot be sandboxed does not run. Command network reaches only an allowlist, which is empty for every example.
- R16. A proxy outside the agent worker holds the Claude credential, puts it in place of the placeholder each session sends, and forwards only to the Claude API. The agent worker's network reaches only the proxy and the Hatchet engine.
- R26. A session sees only its run's working directory, a temporary home and read-only system files, and its own cgroup limits its memory, CPU and processes. The working directory is read-only unless the agent declares that it writes to it.

**Tests**

- R31. An automated test runs the real SDK engine in the real sandbox against a scripted Messages API that makes a session try each escape of AE5, and fails when any succeeds.

### Acceptance Examples

- AE5. **Covers R13, R14, R15, R16, R26, R31.** **Given** a session whose shell command follows a prompt injection, **when** it tries to read the Hatchet token or the Claude credential from any process, write a result into its engine's output, list another run's or the host's files, or reach the internet, **then** every attempt fails and the task returns only the session's real output.

### Scope Boundaries

Not in this part:

- No proxy attempts (U5).
- No network namespace of the engine's own (#38).

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- Per the Claude Code sandboxing doc, the SDK's sandbox covers only the commands of Bash, PowerShell and Monitor, and file tools follow permission rules. The Python SDK runs commands unsandboxed when the sandbox cannot start, unless `failIfUnavailable` is set. Per the env-vars doc, `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips credentials from commands' environments and runs them in their own PID namespace.
- Measured on 2026-10-15 with the bundled engine against a local stand-in for the Messages API that scripted Bash and Read calls (Arch, kernel 7.2, bubblewrap 0.12.0, Docker 29.7.2):
  - Without a sandbox, and with the outer bubblewrap alone, a shell command forged a `ResultMessage` that the SDK yielded before the real one. With the SDK's sandbox alone, the command still read the Hatchet token and the Claude credential in its environment and listed other checkouts. With both layers and the scrub, every attempt failed.
  - The scrub forces `permission_mode` from `dontAsk` to `default`; with explicit `allowed_tools`, every other call was still denied. On the development host, the scrub's own bubblewrap fails outside an outer sandbox because `/run/containerd` exists but is unreadable, and it then runs nothing.
  - The Read tool refuses `/proc/*/environ` as a device file. That is an engine check, not an OS boundary.
  - The engine refuses to run with no credential. With a placeholder it sends `x-api-key: <placeholder>` for an API key, or `Authorization: Bearer <placeholder>` with `anthropic-beta: oauth-2025-04-20` for an OAuth token, to `ANTHROPIC_BASE_URL` alone, with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
  - Docker's default seccomp profile refuses the user namespaces bubblewrap needs. That profile plus `clone`, `unshare`, `mount`, `umount2`, `pivot_root` and `setns` lets bubblewrap start, while `keyctl`, `add_key`, `request_key`, `perf_event_open`, `kexec_load` and `open_by_handle_at` stay refused.
  - A fresh `/proc` also needs Docker's `/proc` masks lifted (`systempaths=unconfined`). uid 1000 then still cannot read `/proc/kcore` or `/proc/timer_list` and gains no write.
  - With `writable-cgroups=true`, a root entrypoint delegated a cgroup subtree to uid 1000 and dropped root. A session in a child cgroup stopped at its process limit and was killed at its memory limit, while the worker's cgroup was untouched.

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD14. **Tests replace the SDK at the same seams, and the compose stack is the guard for the agent worker.**
  - **The pytest guard** in `tests/conftest.py` is unchanged. It removes the credential variables, points `ANTHROPIC_BASE_URL` at a closed port, and fails any unreplaced transport `connect`, except in `fake_cli` tests (R22, AE8).
  - **Unit seam.** `ScriptedQuery` replaces `query` on an agent's module and records the options (R23).
  - **Fake CLI.** `tests/agents/fake_claude.py` stays the engine stand-in. It gains a `fake:hog` scenario that allocates past its memory limit. It reports the environment names, the processes `/proc` lists, and whether its working directory is writable, all to stderr. In integration, the overlay bind-mounts it read-only into the agent worker and points `CORVO_AGENT_ENGINE` at it; `tests/agents/fake/Containerfile` goes.
  - **The out-of-process guard.** The agent worker in compose runs the real transport, outside pytest's guard. What keeps it from Claude is the test stack itself: no service holds a real credential, every upstream is `tests/agents/scripted_api.py`, and the `agents` network has no route out. A test asserts the scripted API received only the dummy credential. R31's real engine runs in that stack alone, so the pytest guard admits nothing new.

  Governs R22, R23, R24, R31.
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
- KTD23. **The agent worker's seccomp profile is generated from Docker's, vendored at a pinned tag, and checked in CI.**
  - `src/corvo/worker/agent_runtime/seccomp-moby-default.json` is moby's `vendor/github.com/moby/profiles/seccomp/default.json` at `docker-v29.7.2`, with its Apache-2.0 license beside it in `seccomp-moby-default.LICENSE`. `corvo.worker.agent_runtime.seccomp` adds `clone`, `unshare`, `mount`, `umount2`, `pivot_root` and `setns` to its allow rule, and writes `seccomp.json` beside it.
  - It also denies `socket(AF_NETLINK, …, NETLINK_NETFILTER)` with `EPROTONOSUPPORT`, comparing the low 32 bits of both arguments, which the kernel reads as ints, and drops 32-bit x86 from x86-64's sub-architectures, whose `socketcall` would open the same socket with arguments no filter reads. Allowing user namespaces opens nf_tables to every command, the kernel area most unprivileged-namespace exploits have used, such as CVE-2024-1086. bubblewrap needs only `NETLINK_ROUTE`, and U1 confirms the SDK's sandbox needs nothing more. This is narrower than R27's floor, never wider.
  - `tests/worker/agent_runtime/test_seccomp.py` regenerates the profile in memory and fails on any difference from the committed one. It also fails when `keyctl`, `add_key`, `request_key`, `perf_event_open`, `kexec_load` or `open_by_handle_at` become allowed, or when the netfilter rule is gone.
  - Compose sets `seccomp=src/corvo/worker/agent_runtime/seccomp.json`, `systempaths=unconfined` and `writable-cgroups=true` on `agent-worker` only. Refreshing the vendored copy when the host's Docker moves to a new major is a step in `docs/agents.md`.

  Governs R27.
- KTD24. **The `agents` compose network is internal, and only the proxy also reaches the outside.**
  - Its members are `agent-worker`, `claude-proxy` and `hatchet-engine`, and `scripted-api` in tests. `claude-proxy` also joins the default network for its upstream.
  - The engine shares the agent worker's network namespace (`--share-net`). It reaches those services, and on loopback the worker's healthcheck and other runs' sandbox proxies. (session-settled: user-directed — chosen over a network namespace of the engine's own: none of that reach gives an engine anything usable, which U8 asserts, and the separate namespace is follow-up work in #38.) Shell commands get their own namespace from the SDK's sandbox, with an empty allowlist (R15).
  - The engine also calls `api.anthropic.com` directly for its fast-mode check, and its other hosts are off by KTD20's flags. With no route out, those calls fail; U1's gate asserts they fail fast and never stall a session.
  - The engine's own reach is measured, not assumed: U8's engine-layer probe records it (KTD25).

  Governs R15, R16.
- KTD25. **R31's probe runs the real engine on a test-only agent worker built from the same image and settings, against a scripted Messages API, through Hatchet.**
  - The overlay's service `agent-probe` runs the `agent-worker` image with the same entrypoint, security options, network, Hatchet token and healthcheck. Its command starts `tests/agents/probe/worker.py`, which calls `serve` with the `agents` profile's hooks and slots and one test-only task, `agent-probe`, whose agent has `Bash`, `Read` and `Grep`. The task stays off every profile. The test triggers it by name, so the task layer and the worker's healthcheck listener are both present.
  - `tests/agents/scripted_api.py`, grown from the Messages API stand-in measured on 2026-10-15, scripts the turns:
    - a Bash call running `tests/agents/probe/probe.sh`;
    - Read and Grep calls on `/proc/self/environ`, `/proc/1/environ`, a working-directory symlink to `/proc/1/environ`, and a path outside the working directory.
  - **The shell layer.** The Bash probe tries every escape of AE5:
    - reading the Hatchet token or a credential from any process's environment;
    - writing a forged result into the engine's output;
    - listing another run's or the host's files;
    - reaching the internet;
    - mounting cgroup2 in a new namespace, writing its own limits, or writing another run's `cgroup.kill`;
    - finding `/sys`;
    - opening a netfilter socket in a nested namespace;
    - writing the engine's home, its `CLAUDE_CONFIG_DIR` or its `/tmp`, so that the engine would later run what it wrote. The probe asserts nothing it wrote ran.
  - **The engine layer.** A second probe runs `probe.sh` straight through the wrapper, without the SDK's sandbox, to measure what an escape into the engine would reach. It expects no token and no writable cgroup file. Because the engine shares the agent worker's network (KTD24), it expects to reach the proxy, the Hatchet engine's gRPC, the worker's healthcheck and other runs' SDK-sandbox proxies on loopback, and nothing else. It asserts that each of those gives nothing usable: the healthcheck serves only health and metrics, another run's sandbox proxy forwards nowhere under the empty allowlist, and the gRPC refuses calls without the token. Any other reach is a failure.
  - Two runs execute at once, so each probe has another run to try.
  - The test fails when any attempt succeeds, or when a session's result differs from the scripted one. U5 runs it again with `claude-proxy` in the path, adding attempts on its other paths and its admin API.

  Governs R31; AE5.

### Risks

- **Sessions share the host's kernel and may create user namespaces.** A kernel bug reachable from an unprivileged user namespace would defeat every layer above it, which is the price of no VM. KTD23 closes the netfilter route most such exploits used, and `docs/agents.md` asks for a patched kernel.

## Implementation Units

### U8. The isolation probe: the real engine against a scripted Messages API

- **Goal:** CI proves AE5 with the operating system enforcing it: a session whose shell commands follow a scripted prompt injection gets nothing it tries, and what an escape into the engine would reach is measured.
- **Requirements:** R13, R14, R15, R16, R26, R31; AE5; KTD14, KTD20, KTD21, KTD23, KTD24, KTD25.
- **Dependencies:** U9.
- **Files:**
  - Create `tests/agents/probe/__init__.py`, `tests/agents/probe/worker.py`, `tests/agents/probe/agent.py` and `tests/agents/probe/probe.sh`.
  - Modify `tests/agents/scripted_api.py` (the probe's turns and the record of tool results) and `tests/integration/worker/compose.yaml` (`agent-probe`).
  - Create `tests/integration/worker/test_isolation_probe.py`.
- **Approach:**
  1. The probe's service, worker, agent and script per KTD25. The script prints one line per attempt, `blocked` or `LEAKED <what>`, and never the value it found.
  2. The working directory holds a symlink to `/proc/1/environ` for the Read and Grep calls.
  3. The test triggers two `agent-probe` runs at once, then reads the tool results the scripted API recorded, each run's result and the engine-layer probe's lines.
- **Execution note:** stop per the Goal Capsule on any `LEAKED` line from the shell layer, rather than weakening the probe. An engine-layer reach beyond KTD25's list, or a listed one that gives something usable, goes to the owner before the plan moves on, since it bears on the shared network (KTD24, #38).
- **Patterns to follow:** the brainstorm's measured `probe.sh` and Messages API stand-in (Dependencies), on which this probe's attempts are modeled.
- **Test scenarios:**
  - Covers AE5. The Bash probe finds no Hatchet token and no credential in its own environment or in any `/proc/*/environ` it can read.
  - Covers AE5. A result the probe writes to every descriptor it can reach never appears among the session's messages, and the session returns the scripted result.
  - Covers AE5. The probe cannot list the agent root's other working directories, the worker's files or the host's.
  - Covers AE5. The probe reaches no outside address.
  - The probe's nested cgroup2 mount gives it no writable limit, its write to the other run's `cgroup.kill` fails, `/sys` is absent, and its netfilter socket is refused.
  - A file the probe writes under the engine's home, its `CLAUDE_CONFIG_DIR` or its `/tmp` is never run by the engine.
  - The Read and Grep calls on `/proc/self/environ`, `/proc/1/environ`, the symlink to it, and a path outside the working directory return nothing secret.
  - The engine-layer probe finds no token and no writable cgroup file. It reaches the proxy, the Hatchet engine's gRPC, the worker's healthcheck and the other run's sandbox proxy, and nothing else. The healthcheck returns only health and metrics, the other run's sandbox proxy refuses every destination, and the gRPC refuses an unauthenticated call.
  - The scripted API received only the placeholder as a credential.
- **Verification:** the probe passes on CI and on Arch with every shell-layer attempt `blocked` and the engine layer's reach as expected.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/integration/worker/test_isolation_probe.py`, on compose, which needs Docker.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- Every shell-layer attempt is `blocked`, on CI and on Arch.
- The engine layer reaches only what KTD25 expects, and each reach is asserted harmless.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u8-isolation-probe`, on top of `feat/agents-u9-agent-worker`, pull request new. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
