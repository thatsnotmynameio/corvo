---
title: Agents Skeleton U1 Rootless Podman Fixture - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u1-podman-fixture
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U1 Rootless Podman Fixture - Plan

## Goal Capsule

- **Objective:** The integration suite runs its own rootless Podman, and on the CI runner and on Arch it proves that a container with the agents' hardening and limits starts and that its limits apply.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 1 of 7. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** none. **Blocks:** U4 builds on this part directly; U5 to U7 through it.
- **Stop conditions:** stop and ask when rootless Podman on the GitHub runner cannot apply memory, CPU and process limits, even with the CI-only `sudo` branch of KTD15; when Podman's Docker-compatible API on 4.9.3 or 6.1 rejects or silently drops a field of KTD6's container spec; or when CI's 90% coverage floor cannot be held without excluding code.

## Product Contract

### Summary

Adds `docker` and `types-docker`, a session fixture that starts `podman system service --time=0` as the test user, and a test that starts one hardened, limited container and reads its limits from inside.

### Context

Every later agent unit depends on rootless Podman applying limits on the CI runner, which the repository cannot set up outside pytest. This part lands first so CI's evidence comes before anything is built on it. R14, R15 and R24 are completed by U4; this part proves the environment they need.

### Key Decisions

- **Each run executes in a fresh, hardened container.** It keeps a prompt-injected agent away from the worker's credentials. Following the Agent SDK's own docs, the whole agent runs inside the boundary, not just its commands. (session-settled: user-directed — chosen over running the agent as a subprocess of the worker, and over the SDK's built-in sandbox.) Governs R13, R15, R17.
- **Rootless Podman under a dedicated host user, with its socket mounted into the worker's container.** The worker stays a compose service. (session-settled: user-directed — chosen over the host's `docker.sock` (a compromised worker is host root), the worker running on the host, Docker-in-Docker and a hosted sandbox.) (session-settled: user-approved — Podman chosen over rootless Docker: it runs beside the compose stack's rootful Docker on its documented path, GitLab Runner documents the same setup, and the CI runner ships it.) Governs R14.
- **The container keeps network egress and receives the Claude credential, for now.** The SDK's docs recommend `--network none` behind a credential-injecting proxy; that is deferred. (session-settled: user-approved — chosen over building the proxy now.) Governs R15.

### Requirements

**Isolation**

- R14. Agent containers run on a rootless Podman under a dedicated host user, apart from the daemon that runs the compose stack. The worker stays a compose service and reaches Podman through that user's API socket, mounted into the worker's container and reachable by the worker's user through a shared group. When it starts, the worker checks that the host's cgroup controllers for memory, CPU and processes are available, and refuses agent runs when they are not.
- R15. The agent container drops every capability, has a read-only root filesystem, runs under the default seccomp profile, and is limited in memory, CPU and processes. Besides size-limited tmpfs mounts for `/tmp` and the agent user's home, it receives only the run directory mount that carries the request and the result, the working directory mount, and the Claude credential. The working directory is mounted read-only unless the agent declares that it writes to it, and a directory an agent may have written is untrusted output: the worker runs no hooks, config or code from it.

**Tests**

- R24. The integration suite runs every example on the real Hatchet and a real rootless Podman, with the SDK replaced inside the container, including the kill and removal on timeout. It creates its working directories under the agent-workdir root (R5), not in pytest's temporary directories.

### Scope Boundaries

- The container spec here is inline in the test. U4's `spec.py` replaces it.
- No agent, image or worker change.

### Dependencies / Assumptions

- Podman's Docker-compatible API translates labels, mounts, tmpfs, `CapDrop`, `SecurityOpt`, `ReadonlyRootfs`, `PidsLimit`, `Memory` and `NanoCPUs` (Podman `pkg/api/handlers/compat/containers_create.go`). It forces read-write tmpfs mounts on `/run` and `/var/tmp` under a read-only root, which the memory cgroup bounds. docker-py refuses to send a user-namespace mode other than `host`, so `keep-id` is out of reach. Running on 4.9.3 and 6.1 is unverified until U1.
- On cgroup v2, a rootless container that asks for a limit whose controller is not delegated fails to start. Only cgroup v1 drops limits with a warning, and Podman 6 refuses cgroup v1. systemd 252 or later delegates memory, CPU and processes to user sessions by default. A user without lingering has no session, and Podman then falls back to cgroupfs.
- Versions differ by machine. Arch ships Podman 6.1.4, which has pasta only, Docker API 1.44 and positive-only label filter semantics, and Podman is not yet installed on this development machine. CI runs on `ubuntu-latest`: today Ubuntu 24.04 with Podman 4.9.3 (slirp4netns, API 1.41), from November 2026 Ubuntu 26.04 with Podman 5.7 (pasta).
- CI runs the organization's reusable `python.yml`, which allows no services and no setup steps. It runs `uv run --locked … pytest` in a 20-minute job, with passwordless `sudo` on GitHub-hosted runners. Any Podman setup in CI happens inside pytest.
- The integration suite runs `corvo-worker` as a host subprocess of the pytest session, which inherits its environment (`tests/integration/worker/conftest.py`). The compose stack runs only Hatchet there, so the worker runs as the developer's or the CI runner's user, the same user that owns the test Podman (KTD15).

## Planning Contract

### Key Technical Decisions

- KTD3. **Each agent sets the isolation options itself, and the container piece sets the isolation environment.**
  - Every agent passes `tools=[…]` (its built-ins, `[]` for none), `allowed_tools` (its file tools as rules scoped to `/workspace`, its other built-ins by name, and its `mcp__<server>__<tool>` names), `permission_mode="dontAsk"`, `setting_sources=[]`, `skills=[]` and `strict_mcp_config=True`, with `model`, `max_turns` and `max_budget_usd` (R10).
  - The container piece sets `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1`, `HOME=/home/agent` and `CLAUDE_CONFIG_DIR=/home/agent/.claude`, both on the home tmpfs.
  - A test helper in `tests/agents/` asserts the isolation fields on the options an agent built. Every agent's unit test calls it, which keeps a corvo options builder out of the runtime code (R4).

  Governs R10, R11.
- KTD5. **The container piece talks to Podman through docker-py over the dedicated user's Docker-compatible socket.** Each blocking call runs in `asyncio.to_thread`, and `types-docker` types it. With no `keep-id`, the agent runs as uid 0 inside the container, which rootless Podman maps to the dedicated host user. Its files are therefore owned by that user, with every capability dropped and no-new-privileges. (session-settled: user-approved — chosen over aiodocker, a corvo client over Podman's libpod API with httpx, and podman-py: docker-py is the official SDK on the path Podman documents, aiodocker is unverified against Podman, and podman-py silently drops `nano_cpus` and rejects `tmpfs=`.) The choice stays inside one module, so it did not call for a bake-off. Governs R13, R14, R17.
- KTD6. **One function builds the container spec, used by every run and by the startup probe.**
  - Hardening: `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]` with Podman's default seccomp, `read_only=True` and `init=True`.
  - tmpfs through docker-py's `tmpfs=` mapping (a tmpfs `Mount` gets mode 0 on Podman):
    - `/tmp` as `rw,noexec,nosuid,nodev,size=100m`;
    - `/home/agent` as `rw,noexec,nosuid,nodev,size=500m`.

    These are the flags of Anthropic's hardened example. If the first proof that runs `Glob` or `Grep` (`dir-summary`'s, in U6) shows the bundled CLI needs an executable temp directory, the fallback is a third tmpfs, `/home/agent-exec` (`rw,nosuid,nodev,size=200m`, no `noexec`), with `CLAUDE_CODE_TMPDIR` pointing at it.
  - Limits: `AGENT_MEMORY` with swap equal to it, `AGENT_NANO_CPUS` and `AGENT_PIDS_LIMIT`.
  - Mounts:
    - the run directory, read-write at `/corvo/run`;
    - the working directory at `/workspace`, read-only unless `WRITES_WORKDIR`, when the run has one.

    A run without a working directory gets no `/workspace` mount, and its session runs in the image's empty `/workspace`.
  - Naming: the container is named `corvo-agent-<task_run_id>-<retry_count>`, and its labels are `corvo.managed=true`, `corvo.deployment`, `corvo.run_id` (the workflow run), `corvo.task_run_id`, `corvo.attempt` and `corvo.agent`.
  - Network: the compat API's default.
  - Environment: KTD3's isolation variables, plus exactly one credential variable when the spec is given a credential. The probe is given none.

  Governs R13, R15, R16.
- KTD7. **One setting, `CORVO_AGENT_ROOT`, holds both the working directories and the run directories, at the same absolute path for the worker and for Podman.**
  - **Working directories.** They must resolve, symlinks included, to an existing directory strictly below `<root>/workdirs/`. `<root>/workdirs` itself is refused, since it would expose every other working directory.
  - **Run directories.** The container piece creates `<root>/runs/<task_run_id>-<retry_count>/` exclusively, failing if it exists. Its mode is 0770, with the setgid group inherited. The group is the dedicated user's primary group, `corvo-agents`, the only group its container process keeps.
  - **Writing and removing the run directory.** `request.json` is written exclusively and without following links. Removing the directory after the run never follows a symlink.
  - **Output from an agent that writes.** A working directory an agent may have written is untrusted output (R15). The container piece's header and `docs/agents.md` state the rule: the worker runs no git, hooks, config or code from such a tree.
  - **The same-path rule.** Podman resolves bind sources on the host, so the compose worker mounts the root at its host path, the same rule Testcontainers states. The integration worker runs on the host, so its paths agree by construction.

  Governs R5, R13, R15.
- KTD10. **Before the worker starts serving, `main()` prepares agents in at most 45 seconds, and a failure only disables them.** When agents are configured (KTD12), it runs, in order:
  1. Check that the image is present.
  2. Run the probe: `corvo-agent probe` in a container built by KTD6's spec, with no credential, no working directory and a scratch run directory. It writes a report into that directory:
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
- KTD15. **The integration suite runs its own rootless Podman as the test user.**
  - **Podman.** A session fixture starts `podman system service --time=0` on a socket inside a fixture-made agent root (`tempfile.mkdtemp`, outside pytest's temporary directories, with KTD7's modes). It builds the agent image and the test image there.
  - **Worker.** The worker fixture passes `CORVO_AGENT_*` pointing at it, but only when Podman is present. Without Podman, the agent tests skip locally and fail when `CI` is set, and the other integration tests keep their worker.
  - **CI fallback.** When the runner has no systemd user session, the fixture's CI-only branch runs `sudo loginctl enable-linger` and sets `XDG_RUNTIME_DIR`. U1 decides whether that branch is needed.
  - **Timeout path.** AE4 is driven by `hatchet.runs.aio_cancel`, the same engine action a timeout sends (Dependencies), because a 15-minute timeout does not fit the 20-minute CI job.
  - **Teardown.** It removes every `corvo.managed` container in the test store.
  - **Health wait.** The worker fixture's health wait rises from 30 to 120 seconds, above KTD10's 45-second preparation and a cold first container start.

  The shared-group socket and the root-worker permissions exist only on the compose topology, which the manual proof covers (KTD18). Governs R24.
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
    - the agent root, setgid with a default ACL for the group. In production it sits on its own filesystem or quota, mounted `nodev,nosuid`;
    - building the agent image as that user on every deploy, and recording its image ID. KTD10 refuses stale images, and a changed ID between deploys is then visible;
    - KTD16's nftables rule;
    - the credential terms and the OAuth token's one-year expiry.
  - **The manual proof runbook.** It triggers an example on the compose topology with real Haiku, and records in the pull request:
    - cost, turns and session ID;
    - peak process count;
    - that `/tmp` with `noexec` did not break the CLI;
    - that the worker read the envelope across the root/rootless boundary;
    - the agent root's mount flags and the worker's dropped capabilities;
    - what the container could reach.

    `dir-summary`'s proof also carries AE6 and tool denial: its working directory holds a CLAUDE.md, a `.claude/skills/` entry and a prompt that asks for a tool outside the list and for a read of `/proc/self/environ`. A fake CLI cannot prove those.

  Governs R14, R16, R25.

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

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict with `types-docker`, lockfile.
- `uv run pytest tests/integration/worker`: integration on compose and the test's rootless Podman (needs Docker and Podman).

## Definition of Done

- Every gate above passes locally and in CI.
- U1 when the Podman proof passes on CI and on Arch, and the PR notes which network mode and Podman version each ran.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-podman-fixture` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-container-piece` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u1-podman-fixture`, on top of `docs/agents-skeleton-plan`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
