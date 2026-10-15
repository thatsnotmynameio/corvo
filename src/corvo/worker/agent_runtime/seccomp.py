"""Writes the agent worker's seccomp profile, seccomp.json, from Docker's own.

seccomp-moby-default.json is moby's
vendor/github.com/moby/profiles/seccomp/default.json at docker-v29.7.2, with a
final newline added, under the Apache License 2.0 in
seccomp-moby-default.LICENSE. Docker's default refuses the user namespaces
bubblewrap builds its sandboxes with; this profile allows those few calls and
nothing else, and refuses the netfilter sockets those namespaces would
otherwise open to every command (KTD23).

Run it after refreshing the vendored copy, and review the difference:
`uv run python -m corvo.worker.agent_runtime.seccomp`. Its test fails while the
committed profile differs from what this writes.
"""

import copy
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
UPSTREAM = HERE / "seccomp-moby-default.json"
PROFILE = HERE / "seccomp.json"

# What bubblewrap needs beyond Docker's default, which allows these only to a
# container with CAP_SYS_ADMIN: new namespaces, and the mounts and the root
# switch it builds a sandbox with.
BUBBLEWRAP_CALLS = ["clone", "unshare", "mount", "umount2", "pivot_root", "setns"]

AF_NETLINK = 16
NETLINK_NETFILTER = 12
LOW_32_BITS = 0xFFFFFFFF

# With user namespaces allowed, nf_tables is open to every command, and it is
# the kernel area most unprivileged-namespace exploits have used, such as
# CVE-2024-1086; bubblewrap needs only NETLINK_ROUTE. The kernel reads
# socket()'s family and protocol as 32-bit ints, so the rule compares their
# low 32 bits alone: a value with high bits set is still a netfilter socket to
# the kernel. libseccomp refuses a rule whose action is the profile's default,
# EPERM, so it answers EPROTONOSUPPORT, as a kernel without netfilter does.
NETFILTER_SOCKET_RULE = {
    "names": ["socket"],
    "action": "SCMP_ACT_ERRNO",
    "errnoRet": 93,
    "args": [
        {
            "index": 0,
            "value": LOW_32_BITS,
            "valueTwo": AF_NETLINK,
            "op": "SCMP_CMP_MASKED_EQ",
        },
        {
            "index": 2,
            "value": LOW_32_BITS,
            "valueTwo": NETLINK_NETFILTER,
            "op": "SCMP_CMP_MASKED_EQ",
        },
    ],
}

# 32-bit x86 reaches socket() through socketcall, with its arguments in memory
# where no filter reads them. Without x86 among x86-64's sub-architectures,
# every 32-bit call ends in the filter's bad-architecture action.
DROPPED_SUBARCHITECTURE = "SCMP_ARCH_X86"


def generate(upstream: dict[str, Any]) -> dict[str, Any]:
    """Docker's profile with bubblewrap's calls allowed and netfilter sockets
    refused. A vendored copy whose rules have moved fails here, so a refresh
    is reviewed rather than silently missing a block."""
    profile = copy.deepcopy(upstream)
    rules: list[dict[str, Any]] = profile["syscalls"]

    unconditional = [rule for rule in rules if rule.keys() == {"names", "action"}]
    if len(unconditional) != 1 or unconditional[0]["action"] != "SCMP_ACT_ALLOW":
        raise ValueError("the vendored profile has no single unconditional allow")
    allowed: list[str] = unconditional[0]["names"]
    allowed += [name for name in BUBBLEWRAP_CALLS if name not in allowed]

    x86_64 = [
        entry
        for entry in profile["archMap"]
        if entry["architecture"] == "SCMP_ARCH_X86_64"
    ]
    if len(x86_64) != 1 or DROPPED_SUBARCHITECTURE not in x86_64[0]["subArchitectures"]:
        raise ValueError("the vendored profile's x86-64 architectures have changed")
    x86_64[0]["subArchitectures"].remove(DROPPED_SUBARCHITECTURE)

    rules.append(copy.deepcopy(NETFILTER_SOCKET_RULE))
    return profile


def render(profile: dict[str, Any]) -> str:
    return json.dumps(profile, indent="\t") + "\n"


def main() -> None:
    PROFILE.write_text(render(generate(json.loads(UPSTREAM.read_text()))))


if __name__ == "__main__":
    main()
