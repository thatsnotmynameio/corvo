---
title: Seccomp socket filter bypassed by high argument bits and 32-bit socketcall
date: 2026-10-15
category: security-issues
module: agent worker seccomp profile
problem_type: security_issue
component: infrastructure
symptoms:
  - "socket(AF_NETLINK, SOCK_RAW, 0x10000000c) opens a NETLINK_NETFILTER socket despite a rule refusing protocol 12"
  - "socket(0x100000010, SOCK_RAW, 12) opens one too, through Docker's own `a0 > 40` allow rule"
  - "A 32-bit int 0x80 socketcall(SYS_SOCKET, [16, 3, 12]) opens one with no argument check at all"
  - "A deny rule whose action is ERRNO(EPERM) is silently dropped, since libseccomp rejects it with EACCES"
root_cause: wrong_api
resolution_type: code_fix
severity: high
framework_version: docker 29.7.2, libseccomp 2.6.0
tags: [seccomp, libseccomp, docker, netlink, netfilter, bubblewrap, agent-worker, x86-32]
---

# Seccomp socket filter bypassed by high argument bits and 32-bit socketcall

## Problem

The agent worker's seccomp profile is Docker's (moby's) default plus the calls bubblewrap needs, and it must refuse `socket(AF_NETLINK, …, NETLINK_NETFILTER)`: user namespaces open nf_tables to every command, the kernel area most unprivileged-namespace exploits have used. The first version passed its JSON-level tests, yet a command in the container could still open a netfilter socket three ways. The fix is on #39, unmerged as of this writing.

## Symptoms

Measured in the `agent-worker` image under the first profile, with the probes now in `tests/integration/corvo/worker/gate/driver.py:134-176`:

- a raw `socket()` syscall with protocol `0x10000000c` opened a netfilter socket;
- one with family `0x100000010` opened one too;
- a 32-bit `socketcall(SYS_SOCKET)` through `int 0x80` opened one.

The plain call, `socket(16, 3, 12)`, was refused, and the JSON-level evaluator in the unit tests said all four were refused.

## What Didn't Work

- **Splitting Docker's `a0 < 38` socket rule** into `a0 < 16` and `a0 < 38 AND a2 != 12`. This held only for exact values. A Docker/runc rule cannot put two conditions on the same argument, because runc turns same-index conditions into separate rules, which ORs them. So the protocol can only be compared once, and that compare is 64-bit.
- **Removing `socketcall` from the unconditional allow list.** It did nothing. In this session's export of the compiled filter (libseccomp 2.6.0), libseccomp compiled every argument-filtered `socket` rule for the x86 sub-architecture into `if ($syscall == 102) if ($a0 == 1) action ALLOW;`, which is `socketcall(SYS_SOCKET)` with no family or protocol check, whether `socketcall` is listed or not.
- **A deny rule with Docker's default errno.** libseccomp 2.6.0 refused a rule whose action equals the filter's default action, `ERRNO(1)`: `seccomp_rule_add_array` returned `-13` (`-EACCES`) in this session's export. runc's JSON gives no sign of this: the rule simply does not exist.
- **Trusting the JSON evaluator in `tests/unit/corvo/worker/agent_runtime/test_seccomp.py:72-111`.** It models what the JSON says, not what libseccomp compiles: Python ints are unbounded, and the evaluator has no notion of architecture.

## Solution

Keep Docker's socket rules, append a deny rule that compares only the low 32 bits of both arguments, and drop 32-bit x86 from x86-64's sub-architectures (`src/corvo/worker/agent_runtime/seccomp.py:30-89`):

```python
NETFILTER_SOCKET_RULE = {
    "names": ["socket"],
    "action": "SCMP_ACT_ERRNO",
    "errnoRet": 93,  # EPROTONOSUPPORT; EPERM is the default action, which libseccomp refuses
    "args": [
        {"index": 0, "value": 0xFFFFFFFF, "valueTwo": 16, "op": "SCMP_CMP_MASKED_EQ"},
        {"index": 2, "value": 0xFFFFFFFF, "valueTwo": 12, "op": "SCMP_CMP_MASKED_EQ"},
    ],
}
# ...and in generate():
x86_64["subArchitectures"].remove("SCMP_ARCH_X86")  # leaves ["SCMP_ARCH_X32"]
rules.append(NETFILTER_SOCKET_RULE)
```

For Docker's JSON, `SCMP_CMP_MASKED_EQ` holds when `(arg & value) == valueTwo`. Afterwards the container refuses the plain call and both high-bit encodings with `EPROTONOSUPPORT`, the 32-bit call dies with SIGSYS (the filter's bad-architecture action), and `NETLINK_ROUTE` still opens. `tests/integration/corvo/worker/test_isolation_gate.py:181-191` asserts all five.

## Why This Works

- The kernel declares `socket()` as `SYSCALL_DEFINE3(socket, int, int, int)`, so it reads only the low 32 bits of each register. libseccomp compares the whole 64-bit register on x86-64. Every `LT`/`NE`/`GT` rule on an `int` argument therefore has a high-bit twin that the filter sees as a different value and the kernel as the same one. A mask on the low 32 bits compares what the kernel will actually use. Docker's own socket rules that exclude `AF_ALG` (38) and `AF_VSOCK` (40), namely `a0 < 38`, `a0 == 39` and `a0 > 40`, have the same gap upstream; this profile's deny rule closes it only for netfilter.
- In the PFC that libseccomp exports, the deny rule's chain is tested before the allow branches for the same syscall, so `ERRNO(93)` wins wherever both match. This was observed by exporting the compiled filter with libseccomp 2.6.0, and confirmed in the container.
- Removing the sub-architecture removes the only path in which arguments sit in memory where no filter can read them. x32 keeps the direct, filtered `socket` syscall.

## Prevention

- **Check the compiled filter, not the JSON.** Compile the profile with libseccomp the way runc does, and read the PFC for the syscalls you touched. The exporter used here was a throwaway script, not committed; a minimal one through ctypes against `libseccomp.so.2` follows runc's rules: one `seccomp_rule_add_array` per JSON rule; same-index conditions split into separate rules; caps rules applied for Docker's default caps; each sub-architecture added with `seccomp_arch_add`; then `seccomp_export_pfc`. A rule-add return of `-13` means the action equals the default.
- **Probe in the container, for every encoding.** For any argument rule on an `int` argument:
  - one probe with the exact value;
  - one with bit 32 set, as a raw `syscall()` through ctypes with `c_long` arguments, because Python's `socket` module truncates;
  - for `socket` on x86, a 32-bit `int 0x80` call from a `MAP_32BIT` mapping (`driver.py:61-78`).

  Run the probes under the old profile as well. Each one opening a socket there is what proves the probe can detect a regression.
- **Never give a deny rule the profile's default errno.**
- **On refreshing the vendored moby profile,** regenerate, then re-run the gate's netlink probes. `generate()` fails loudly if x86 is no longer a sub-architecture.

## Related Issues

- #39: the agents skeleton's U1 (agent worker image, seccomp profile, sandbox wrapper, isolation gate), where this was found in review and fixed.
- KTD23 in `docs/plans/2026-10-15-0020-feat-agents-skeleton-plan.md` states the resulting profile.
