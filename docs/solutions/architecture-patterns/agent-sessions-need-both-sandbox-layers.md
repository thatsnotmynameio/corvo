---
title: Agent sessions need both sandbox layers, and why a container per run was dropped
date: 2026-10-16
category: architecture-patterns
module: agent worker isolation
problem_type: architecture_pattern
component: infrastructure
severity: critical
applies_when:
  - Changing how the agent worker starts a session's engine, or the sandbox settings an agent passes to the SDK
  - Proposing to drop either sandbox layer, or the credential scrub, as redundant
  - Proposing a container, VM or other runtime per agent run in place of bubblewrap
retire_when: "The Claude Agent SDK's command sandbox also isolates the engine itself, or corvo moves agent sessions to a runtime that isolates both; check the Claude Code sandboxing docs and re-run the isolation gate and probe before removing a layer"
tags: [agent-worker, bubblewrap, sandbox, claude-agent-sdk, isolation, podman, env-scrub, defense-in-depth]
---

# Agent sessions need both sandbox layers, and why a container per run was dropped

## Context

Every agent corvo plans has Bash. An agent with Bash in the worker's process sees the worker's environment, which holds the Hatchet token and the Claude credential. Hatchet provides no sandboxing and leaves it to the infrastructure, so corvo had to decide where a session runs.

**The first design ran each session in a fresh rootless Podman container driven from the worker** (closed PRs #32 and #36). Each review round found another hole:
- a request file that others in its group could read;
- a session result that any process in the container could forge;
- the Claude credential in every child process's environment;
- a container create that outlasted its bound, or that a cancel landed during, which could leave a container with no handle behind (a review fix on #36).

Each fix added transport code over the container's streams, and the host still needed a Podman of its own. The plan replaced the design (`docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md`, Problem Frame and Key Decisions).

## Guidance

A session runs in two nested bubblewrap layers, and neither one is optional.

1. **The Outer sandbox** (see `CONCEPTS.md`) runs the SDK's engine. `corvo-agent-sandbox` (`src/corvo/worker/agent_runtime/sandbox.py`) is the SDK's `cli_path`. It joins the run's cgroup, then replaces itself with bubblewrap started from an empty environment. The engine sees read-only system files, a temporary home, its own process table and the run's working directory, and nothing else of the worker.
2. **The Command sandbox**, the SDK's own, runs every shell command inside that, with `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`. The scrub strips credentials from a command's environment and gives the command its own PID namespace (Claude Code's env-vars doc). The wrapper sets the scrub on every session (`sandbox.py:44`).

**What each layer covers.** Both were measured on 2026-10-15 with the bundled engine against a scripted stand-in for the Messages API (the plan's Dependencies):
- **Neither layer, or the Outer sandbox alone:** a shell command could still tamper with the result the SDK reads from its own engine.
- **The Command sandbox alone:** commands still reached the worker's secrets in their environment, and other checkouts.
- **Both layers, plus the scrub:** none of the attempts succeeded.

The layers are not two copies of one protection. Each closes what the other leaves open.

**The wrapper refuses a session that would weaken the inner layer.** It refuses one whose SDK sandbox is off, does not fail when it cannot start, allows unsandboxed commands, excludes commands, or is the weaker nested one (`check_settings`, `sandbox.py:131-162`). `tests/support/isolation.py`'s `assert_isolated` holds every agent's options to the same rules, plus an empty network allowlist. Keep `failIfUnavailable`: without it, the Python SDK runs commands unsandboxed whenever its sandbox cannot start.

**Prove a change, don't argue it.** A change to either layer, to the wrapper or to the agent worker's container settings is proven the way the decision was:
- run the isolation gate in CI (`tests/integration/corvo/worker/test_isolation_gate.py`), which shows the image can still start both layers;
- run the isolation probe from the plan's U8 against the real engine, once it exists.

The negative tests involved must fail without their protection; see the related learning below.

## Why This Matters

Each layer looks redundant from the other side:
- Someone reading `sandbox.py` sees bubblewrap already isolating the engine, and may wonder why the SDK's sandbox is also required.
- Someone reading the SDK's sandboxing docs sees commands already sandboxed, and may wonder why the engine needs a sandbox too.

Removing either one brings back an opening the measurements found. Going back to a container per run brings back the class of hole that ended the first design: the session's own channels and environment, reachable from inside the container. Nothing in the code says why both layers exist, so this record is what stops the simplification.

## When to Apply

- Any change to `corvo-agent-sandbox`, to an agent's `sandbox` options, or to the variables the wrapper passes in.
- Any proposal to replace bubblewrap with a container runtime, a VM per run, or gVisor. The plan's Key Decisions say why each was declined: rootless gVisor, for one, drops cgroup limits and network namespaces.
- An upgrade of the Claude Agent SDK or its bundled engine, whose sandbox behavior can change between releases.

## Examples

Three refusals a reader is likely to meet, the first from the wrapper on one session, the other two from the agent worker's start:
- `corvo-agent-sandbox: refused: the sandbox allows unsandboxed commands`: an agent's options would let a command run outside the Command sandbox.
- `agents refused: the SDK's sandbox: ...`: the agent worker's start found that the nested bubblewrap, the one the SDK runs each command in, cannot start. The worker then registers no agent task (`docs/agents.md`, "When the agent worker refuses to start").
- `agents refused: bubblewrap: ...`: the Outer sandbox did not start, or shows more than it should.

## Related

- [A negative test must fail when the protection it proves is removed](../best-practices/negative-tests-must-fail-without-their-protection.md): how the sandbox's refusal tests were made to prove something.
- [Seccomp socket filter bypassed by high argument bits and 32-bit socketcall](../security-issues/seccomp-socket-filter-bypassed-by-high-bits-and-32-bit-socketcall.md): the agent worker's seccomp profile, which lets bubblewrap start and refuses netfilter sockets.
- #38 (open): give each session's engine a network namespace of its own. Today the Outer sandbox shares the agent worker's network.
- `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md`: Problem Frame, Key Decisions and Dependencies hold the full rationale and the measurements.
