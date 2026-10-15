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
AF_ALG = 38
NETLINK_NETFILTER = 12

# Docker's rule for the address families below AF_ALG, AF_NETLINK among them.
UPSTREAM_SOCKET_RULE = {
    "names": ["socket"],
    "action": "SCMP_ACT_ALLOW",
    "args": [{"index": 0, "value": AF_ALG, "op": "SCMP_CMP_LT"}],
}

# It becomes two: the families below AF_NETLINK with any protocol, and the
# families below AF_ALG with any protocol but 12. With user namespaces
# allowed, nf_tables is open to every command, and it is the kernel area most
# unprivileged-namespace exploits have used, such as CVE-2024-1086; bubblewrap
# needs only NETLINK_ROUTE. The families from AF_PACKET to AF_ALG lose
# protocol 12 too, which none of them uses: a rule cannot hold two conditions
# on the same argument.
SOCKET_RULES = [
    {
        "names": ["socket"],
        "action": "SCMP_ACT_ALLOW",
        "args": [{"index": 0, "value": AF_NETLINK, "op": "SCMP_CMP_LT"}],
    },
    {
        "names": ["socket"],
        "action": "SCMP_ACT_ALLOW",
        "args": [
            {"index": 0, "value": AF_ALG, "op": "SCMP_CMP_LT"},
            {"index": 2, "value": NETLINK_NETFILTER, "op": "SCMP_CMP_NE"},
        ],
    },
]

# socketcall multiplexes every socket call of 32-bit x86, with its arguments
# in memory where a filter cannot read them: a 32-bit binary would open a
# netfilter socket through it.
MULTIPLEXED_SOCKET_CALL = "socketcall"


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
    if MULTIPLEXED_SOCKET_CALL not in allowed:
        raise ValueError("the vendored profile no longer allows socketcall")
    allowed.remove(MULTIPLEXED_SOCKET_CALL)
    allowed += [name for name in BUBBLEWRAP_CALLS if name not in allowed]

    if UPSTREAM_SOCKET_RULE not in rules:
        raise ValueError("the vendored profile's socket rule has changed")
    at = rules.index(UPSTREAM_SOCKET_RULE)
    rules[at : at + 1] = copy.deepcopy(SOCKET_RULES)
    return profile


def render(profile: dict[str, Any]) -> str:
    return json.dumps(profile, indent="\t") + "\n"


def main() -> None:
    PROFILE.write_text(render(generate(json.loads(UPSTREAM.read_text()))))


if __name__ == "__main__":
    main()
