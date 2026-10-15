---
title: Agents Skeleton U5 Agent Operations - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u5-operations
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U5 Agent Operations - Plan

## Goal Capsule

- **Objective:** An operator can switch agents on for the compose stack from one document, and `tone` is proven once against real Haiku on that topology.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 5 of 7. This file is meant to be enough: open the parent only when something you need is missing here.
- **Depends on:** U4. **Blocks:** none; U6 sits above it in the stack.
- **Stop conditions:** stop and ask when the bundled `claude` CLI fails under KTD6's read-only root and `noexec` tmpfs in the manual proof, and `CLAUDE_CODE_TMPDIR` on an exec-allowed tmpfs does not fix it; or when CI's 90% coverage floor cannot be held without excluding code.

## Builds on

Already in the stack below; read the code, not those plans.

- U4: the container piece, the `tone` task and the worker's preparation, with the `CORVO_AGENT_*` settings it reads.

## Product Contract

### Summary

Adds `compose.agents.yaml`, `docs/agents.md` (provisioning, credentials, nftables rule, manual proof runbook) and the agent variables in `.env.example`, then proves `tone` on real Haiku.

### Context

The skeleton is only usable once a host can be provisioned for it. R14's shared-group socket and the root-worker permissions exist only on this topology, so this part's proof is their only check. R25 is completed for `tone` here.

### Key Decisions

- **Rootless Podman under a dedicated host user, with its socket mounted into the worker's container.** The worker stays a compose service. (session-settled: user-directed — chosen over the host's `docker.sock` (a compromised worker is host root), the worker running on the host, Docker-in-Docker and a hosted sandbox.) (session-settled: user-approved — Podman chosen over rootless Docker: it runs beside the compose stack's rootful Docker on its documented path, GitLab Runner documents the same setup, and the CI runner ships it.) Governs R14.
- **The Claude credential is either an API key or a subscription OAuth token, chosen per environment.** (session-settled: user-directed — chosen over an API key only and over a subscription token only.) Governs R12.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.

### Requirements

**Agent execution**

- R12. The Claude credential comes from corvo's settings, as an API key or a subscription OAuth token, and each environment chooses which.

**Isolation**

- R14. Agent containers run on a rootless Podman under a dedicated host user, apart from the daemon that runs the compose stack. The worker stays a compose service and reaches Podman through that user's API socket, mounted into the worker's container and reachable by the worker's user through a shared group. When it starts, the worker checks that the host's cgroup controllers for memory, CPU and processes are available, and refuses agent runs when they are not.
- R16. When Hatchet times out or cancels an agent task, the task kills and removes its container. Every container carries labels with its run's ID and its Hatchet deployment (server and tenant). A worker that starts removes only containers of its own deployment whose run Hatchet reports as finished, failed or cancelled.

**Tests**

- R25. Each example is proven once against real Claude Haiku with a small prompt, through a documented manual command whose run is recorded in the pull request.

### Scope Boundaries

- No code change beyond configuration and documentation.

### Dependencies / Assumptions

- The subscription OAuth token is, by Anthropic's terms, for ordinary individual use by the subscriber. Products and services built on the Agent SDK must use API keys (`legal-and-compliance.md`; Agent SDK `overview.md`). A `claude setup-token` token lasts one year.
- The default rootless network relays traffic through sockets the dedicated user opens on the host. The container therefore reaches the LAN, the cloud metadata endpoint and the compose stack's bridge addresses, not only the internet (passt and Podman network docs).

## Planning Contract

### Key Technical Decisions

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

## Verification Contract

- `uv run prek run --all-files`: ruff, format, mypy strict with `types-docker`, lockfile.
- The manual Haiku proof in `docs/agents.md`, recorded in the PR.

## Definition of Done

- Every gate above passes locally and in CI.
- U5 when a worker provisioned from `docs/agents.md` logs agents as enabled, and the PR records `tone`'s Haiku run with KTD18's evidence.
- No abandoned attempt remains in the diff.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-podman-fixture` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-container-piece` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u5-operations`, on top of `feat/agents-u4-container-piece`. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack init` with the branches above, in order, when the stack does not exist yet (it adopts the existing plans branch); otherwise `gh stack checkout` this branch.
- **Publish and merge:** `gh stack submit` opens one pull request per layer; `gh stack merge` merges bottom up.
