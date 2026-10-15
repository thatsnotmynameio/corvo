---
title: Agents Skeleton U5 Credential Proxy, Operations Doc and Tone Proof - Plan
type: feat
date: 2026-10-15
topic: agents-skeleton-u5-operations
artifact_contract: ce-unified-plan/v1
product_contract_source: ce-brainstorm
origin: docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md
execution: code
---

# Agents Skeleton U5 Credential Proxy, Operations Doc and Tone Proof - Plan

## Goal Capsule

- **Objective:** An operator runs agents from `compose.yaml` and one document. The credential sits only in the proxy, and `tone` is proven once against real Haiku.
- **Parent:** `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` holds the whole plan; this is part 7 of 9 in stack order (unit U5). This file is meant to be enough: open the parent only when something you need is missing here. When the two differ, the parent wins.
- **Depends on:** U8; it sits on `feat/agents-u8-isolation-probe` in the stack. **Blocks:** U6 builds on this part directly; U7 through it.
- **Stop conditions:** stop and ask when Caddy 2.11.7 cannot express KTD22's rules without expanding a request-derived value, or when a stream longer than 60 seconds does not reach the client whole.

## Builds on

Read the code on the branches named here, not the plans that produced it.

- U8: the isolation probe and `scripted-api`, which become the proxy's upstream in tests.
- U9: the `agent-worker` service and the `agents` network.
- On `main`: `compose.yaml`'s and `.env.example`'s comment style, and `README.md`.

## Product Contract

### Summary

Adds the Caddy credential proxy as `claude-proxy`, puts it between the agent worker and the Claude API, re-runs the isolation probe through it, writes `docs/agents.md`, the repository's first operations doc, and records `tone`'s Haiku proof.

### Context

R12 and R16 keep the Claude credential out of the agent worker. Until this part, the stack's sessions talk to the scripted API directly. R25 is completed for `tone` here; U6 and U7 record their own proofs.

### Key Decisions

- **The agent worker is a compose service of its own.** (session-settled: user-approved — chosen over a systemd service on the host: it keeps one deploy path and the Hatchet engine's gRPC internal, at the cost of R27's container settings and a profile kept in step with Docker's.) Governs R13, R27.
- **The Claude credential lives in a proxy and the agent worker's egress is cut, from the first run.** Without both, a session that reads its own engine's credential could send it out. (session-settled: user-approved — chosen over deferring the proxy and `--network none`, as the Podman design did.) Governs R12, R16.
- **The Claude credential is either an API key or a subscription OAuth token, chosen per environment.** (session-settled: user-directed — chosen over an API key only and over a subscription token only.) Governs R12.
- **No automated test calls Claude; a manual run on Haiku proves each example.** (session-settled: user-directed — chosen over an e2e job against real Claude on every push to main, and over an on-demand e2e job.) Governs R22, R25.

### Requirements

**Agent execution**

- R12. The Claude credential is set in the deployment's environment, as an API key or a subscription OAuth token, and each environment chooses which. Only the proxy of R16 receives it; corvo's settings hold only which kind it is.

**Isolation**

- R13. Agent tasks run only on a dedicated agent worker, which holds the Hatchet token but neither the database password nor the Claude credential.
- R16. A proxy outside the agent worker holds the Claude credential, puts it in place of the placeholder each session sends, and forwards only to the Claude API. The agent worker's network reaches only the proxy and the Hatchet engine.
- R27. The agent worker's container keeps a syscall filter: Docker's default profile plus only the calls bubblewrap needs. The profile is generated from the upstream one, and a CI check fails when the generated and the committed profiles differ.

**Tests**

- R25. Each example is proven once against real Claude Haiku with a small prompt, through a documented manual command whose run is recorded in the pull request.
- R31. An automated test runs the real SDK engine in the real sandbox against a scripted Messages API that makes a session try each escape of AE5, and fails when any succeeds.

### Acceptance Examples

- AE5. **Covers R13, R14, R15, R16, R26, R31.** **Given** a session whose shell command follows a prompt injection, **when** it tries to read the Hatchet token or the Claude credential from any process, write a result into its engine's output, list another run's or the host's files, or reach the internet, **then** every attempt fails and the task returns only the session's real output.

### Scope Boundaries

Not in this part:

- No run-scoped proxy authentication and no per-run spend ceiling: the Console workspace's spend limit bounds spend (KTD18).
- No credential rotation flow beyond what `docs/agents.md` states.

The parent's Scope Boundaries hold for every part.

### Dependencies / Assumptions

- Measured on 2026-10-15 with the bundled engine against a local stand-in for the Messages API that scripted Bash and Read calls (Arch, kernel 7.2, bubblewrap 0.12.0, Docker 29.7.2):
  - Without a sandbox, and with the outer bubblewrap alone, a shell command forged a `ResultMessage` that the SDK yielded before the real one. With the SDK's sandbox alone, the command still read the Hatchet token and the Claude credential in its environment and listed other checkouts. With both layers and the scrub, every attempt failed.
  - The scrub forces `permission_mode` from `dontAsk` to `default`; with explicit `allowed_tools`, every other call was still denied. On the development host, the scrub's own bubblewrap fails outside an outer sandbox because `/run/containerd` exists but is unreadable, and it then runs nothing.
  - The Read tool refuses `/proc/*/environ` as a device file. That is an engine check, not an OS boundary.
  - The engine refuses to run with no credential. With a placeholder it sends `x-api-key: <placeholder>` for an API key, or `Authorization: Bearer <placeholder>` with `anthropic-beta: oauth-2025-04-20` for an OAuth token, to `ANTHROPIC_BASE_URL` alone, with `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
  - Docker's default seccomp profile refuses the user namespaces bubblewrap needs. That profile plus `clone`, `unshare`, `mount`, `umount2`, `pivot_root` and `setns` lets bubblewrap start, while `keyctl`, `add_key`, `request_key`, `perf_event_open`, `kexec_load` and `open_by_handle_at` stay refused.
  - A fresh `/proc` also needs Docker's `/proc` masks lifted (`systempaths=unconfined`). uid 1000 then still cannot read `/proc/kcore` or `/proc/timer_list` and gains no write.
  - With `writable-cgroups=true`, a root entrypoint delegated a cgroup subtree to uid 1000 and dropped root. A session in a child cgroup stopped at its process limit and was killed at its memory limit, while the worker's cgroup was untouched.
- The subscription OAuth token is, by Anthropic's terms, for ordinary individual use by the subscriber. Products and services built on the Agent SDK must use API keys (`legal-and-compliance.md`; Agent SDK `overview.md`). A `claude setup-token` token lasts one year.

## Planning Contract

### Key Technical Decisions

Copied from the parent; a KTD cited here but not copied is in the parent.

- KTD12. **Agent settings are `CORVO_AGENT_*` fields for the root, the kind, the proxy, the cgroup root and the engine.**
  - Removed: `agent_podman_socket`, `agent_image`, `agent_require_egress_block` and `agent_credential`. The credential moves to the proxy's environment (R12).
  - Kept: `agent_root` and `agent_credential_kind: Literal["api_key", "oauth_token"]`.
  - Added: `agent_proxy_url` (the sessions' `ANTHROPIC_BASE_URL`), `agent_cgroup_root` (default `/sys/fs/cgroup/agents`) and `agent_engine`, the engine's path. The `agent-worker` image sets it to the engine KTD13 moved; the integration overlay points it at the fake CLI, and KTD10 logs it at start.
  - Each session gets a fixed placeholder as `ANTHROPIC_API_KEY` for `api_key`, or as `CLAUDE_CODE_OAUTH_TOKEN` for `oauth_token`, never both. The engine then sends `x-api-key` or `Authorization: Bearer`, which the proxy replaces (KTD22).
  - The settings comment and `docs/agents.md` carry the OAuth terms (Dependencies).

  Governs R12, R13.
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
- KTD22. **Caddy 2.11.7 holds the Claude credential, as the `claude-proxy` service.**
  - It runs from the official `caddy:2.11.7-alpine` image with `src/corvo/agents/Caddyfile`, and its admin API is off.
  - It accepts only `POST /v1/messages` and `POST /v1/messages/count_tokens`, with their query, and answers 404 to anything else, `HEAD /api/hello` included.
  - It removes the incoming `x-api-key` and `Authorization`, and sets `CORVO_AGENT_CREDENTIAL` in the header `CORVO_AGENT_CREDENTIAL_KIND` names: `x-api-key`, or `Authorization: Bearer`. Every `anthropic-*` header and the body pass unchanged, including the OAuth beta value without which the API answers 401.
  - It refuses an `anthropic-beta` value naming `mcp-client` or `web-fetch`, which would let a request make the API itself fetch from an address the request names, and it caps the request body at 32 MiB. Web search needs no beta header, so `docs/agents.md` requires web search and web fetch turned off in the API key's Console organization. It also states that an `oauth_token` deployment cannot turn them off.
  - The upstream is `CORVO_AGENT_UPSTREAM`, `https://api.anthropic.com` by default, with `Host` set to it. Responses stream as they arrive, with no total timeout and idle limits above the engine's 300-second watchdogs. Its log never holds headers or bodies.
  - The Caddyfile expands no value that comes from a request, only `{env.…}` of its own configuration, which keeps GHSA-wwhq-w58m-w29c's class of leak out.
  - It is pinned at 2.11.7 or later, because 2.11.6 cut streams opened by a `POST` 60 seconds after the request body was read.
  - Apache-2.0, read at the source.
  - (session-settled: user-directed — chosen over a corvo-owned Python proxy and Envoy: no corvo code sits on the credential's path, and Caddy's streaming is mature.)

  Governs R12, R16.
- KTD23. **The agent worker's seccomp profile is generated from Docker's, vendored at a pinned tag, and checked in CI.**
  - `src/corvo/worker/agent_runtime/seccomp-moby-default.json` is moby's `vendor/github.com/moby/profiles/seccomp/default.json` at `docker-v29.7.2`, with its Apache-2.0 license beside it in `seccomp-moby-default.LICENSE`. `corvo.worker.agent_runtime.seccomp` adds `clone`, `unshare`, `mount`, `umount2`, `pivot_root` and `setns` to its allow rule, and writes `seccomp.json` beside it.
  - It also denies `socket(AF_NETLINK, …, NETLINK_NETFILTER)`, and takes `socketcall` off the allow rule: 32-bit x86 would open the same socket through it, with arguments no filter reads. Allowing user namespaces opens nf_tables to every command, the kernel area most unprivileged-namespace exploits have used, such as CVE-2024-1086. bubblewrap needs only `NETLINK_ROUTE`, and U1 confirms the SDK's sandbox needs nothing more. This is narrower than R27's floor, never wider.
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

- **Caddy regressions on streaming.** 2.11.6 broke exactly the engine's request shape. A stream longer than 60 seconds in `test_proxy.py` guards every bump.

### Deferred to Implementation

- How the Caddyfile picks the header from `CORVO_AGENT_CREDENTIAL_KIND`: an environment-chosen snippet or two matchers. Both kinds are tested either way.

## Implementation Units

### U5. Operations: the credential proxy, the operations doc and the `tone` proof

- **Goal:** an operator runs agents from `compose.yaml` and one document. The credential sits only in the proxy, and `tone` is proven once against real Haiku.
- **Requirements:** R12, R13, R16, R25, R27, R31; KTD18, KTD22, KTD23, KTD24, KTD25.
- **Dependencies:** U8.
- **Files:**
  - Create `src/corvo/agents/Caddyfile`.
  - Modify `compose.yaml` (`claude-proxy`, its networks, the agent worker's proxy address) and `.env.example` (the credential and its kind).
  - Modify `tests/integration/worker/compose.yaml` (the proxy's upstream on `scripted-api`, `agent-probe` through the proxy) and `tests/integration/worker/conftest.py` (`write_env_file`'s dummy credential).
  - Create `tests/integration/worker/test_proxy.py`, and modify `tests/agents/probe/probe.sh` (the attempts on the proxy).
  - Create `docs/agents.md`; modify `README.md` (one line pointing at the doc).
- **Approach:**
  1. The Caddyfile per KTD22, with a header comment in `compose.yaml`'s style.
  2. In the stack, the agent worker's and the probe's proxy address move from `scripted-api` to `claude-proxy`.
  3. The probe gains attempts on the proxy's other paths and its admin API.
  4. `docs/agents.md` in KTD18's order.
- **Execution note:** the proxy's behavior is proven by integration against the scripted upstream; the doc is proven by following it with the Haiku runbook.
- **Patterns to follow:** `compose.yaml`'s and `.env.example`'s comment style.
- **Test scenarios:**
  - With kind `api_key`, a request carrying the placeholder in `x-api-key` reaches the upstream with the dummy credential in `x-api-key` and no `Authorization`.
  - With kind `oauth_token`, a request carrying `Authorization: Bearer <placeholder>` and the OAuth beta value reaches the upstream with `Authorization: Bearer <dummy>` and the beta value unchanged.
  - `GET /v1/models`, `HEAD /api/hello` and `POST /v1/files` get 404 and never reach the upstream.
  - A request whose `anthropic-beta` names `mcp-client` or `web-fetch` is refused, and so is a body over 32 MiB.
  - A request header holding `{env.CORVO_AGENT_CREDENTIAL}` reaches the upstream unexpanded.
  - An upstream SSE stream that pauses between events and lasts more than 60 seconds after the request body reaches the client whole, event by event.
  - Integration: `tone` through `claude-proxy` returns the fake's verdict, and the scripted upstream saw only the dummy credential.
  - Covers AE5. Integration: the isolation probe, through `claude-proxy`, still has every shell-layer attempt `blocked`, and its attempts on the proxy's other paths and admin API fail.
- **Verification:** the suites pass. `docker compose config` validates. Following `docs/agents.md` on Arch gives an agent worker that logs its checks as passed. The pull request records `tone`'s Haiku run with KTD18's evidence.

## Verification Contract

- `uv run prek run --all-files`.
- `uv run pytest tests/integration/worker`: integration on compose, `test_proxy.py` included.
- `docker compose config` validates.
- Manual: the Haiku runbook in `docs/agents.md`, once for `tone`.
- CI: `tnmn.io: python` on the pull request.

## Definition of Done

- Every gate above passes locally, and CI passes on the pull request.
- The proxy's tests pass, and the isolation probe passes through it.
- Following `docs/agents.md` on Arch gives an agent worker that logs its checks as passed.
- The pull request records `tone`'s Haiku run with KTD18's evidence.
- No abandoned attempt remains in the diff: no unused helpers, no commented-out code, no leftover tests.

## Execution: gh stack

- **Stack, bottom to top:** `docs/agents-skeleton-plan` → `feat/agents-u1-isolation-gate` → `feat/agents-u2-boundaries` → `feat/agents-u3-tone-agent` → `feat/agents-u4-session-piece` → `feat/agents-u9-agent-worker` → `feat/agents-u8-isolation-probe` → `feat/agents-u5-operations` → `feat/agents-u6-dir-summary` → `feat/agents-u7-dir-review`.
- **This part:** branch `feat/agents-u5-operations`, on top of `feat/agents-u8-isolation-probe`, pull request new. Commit only this unit here; a fix a lower part needs goes on that part's branch, then `gh stack rebase`.
- **Start:** `gh stack checkout` this branch when it exists, or `gh stack add` it on top of the part below.
- **Publish and merge:** `gh stack submit` opens or updates one pull request per layer; `gh stack merge` merges bottom up.
