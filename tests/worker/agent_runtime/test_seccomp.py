"""The agent worker's seccomp profile is what corvo.worker.agent_runtime's
seccomp writes from Docker's, and still refuses what Docker's refuses
(KTD23)."""

import json
from typing import Any

import pytest

from corvo.worker.agent_runtime import seccomp

# Docker's default capabilities, which the agent worker's container keeps:
# a rule that includes another capability does not apply to it.
DOCKER_CAPS = {
    "CAP_AUDIT_WRITE",
    "CAP_CHOWN",
    "CAP_DAC_OVERRIDE",
    "CAP_FOWNER",
    "CAP_FSETID",
    "CAP_KILL",
    "CAP_MKNOD",
    "CAP_NET_BIND_SERVICE",
    "CAP_NET_RAW",
    "CAP_SETFCAP",
    "CAP_SETGID",
    "CAP_SETPCAP",
    "CAP_SETUID",
    "CAP_SYS_CHROOT",
}

AF_INET = 2
AF_NETLINK = 16
NETLINK_ROUTE = 0
NETLINK_NETFILTER = 12
HIGH_BIT = 1 << 32
IPPROTO_TCP = 6

REFUSED = [
    "keyctl",
    "add_key",
    "request_key",
    "perf_event_open",
    "kexec_load",
    "open_by_handle_at",
]


def upstream() -> dict[str, Any]:
    profile: dict[str, Any] = json.loads(seccomp.UPSTREAM.read_text())
    return profile


@pytest.fixture(scope="module")
def profile() -> dict[str, Any]:
    generated: dict[str, Any] = seccomp.generate(upstream())
    return generated


def applies(rule: dict[str, Any]) -> bool:
    """Whether Docker loads the rule for an x86-64 container with its default
    capabilities, as moby's profiles/seccomp does."""
    includes, excludes = rule.get("includes", {}), rule.get("excludes", {})
    if "arches" in includes and "amd64" not in includes["arches"]:
        return False
    if "caps" in includes and not set(includes["caps"]) <= DOCKER_CAPS:
        return False
    if "amd64" in excludes.get("arches", []):
        return False
    return not set(excludes.get("caps", [])) & DOCKER_CAPS


def holds(condition: dict[str, Any], args: dict[int, int]) -> bool:
    value = args.get(condition["index"], 0)
    wanted: int = condition["value"]
    match condition["op"]:
        case "SCMP_CMP_EQ":
            return value == wanted
        case "SCMP_CMP_NE":
            return value != wanted
        case "SCMP_CMP_LT":
            return value < wanted
        case "SCMP_CMP_GT":
            return value > wanted
        case "SCMP_CMP_MASKED_EQ":
            return value & wanted == int(condition.get("valueTwo", 0))
    raise AssertionError(f"no evaluation for {condition['op']}")


def matches(rule: dict[str, Any], args: dict[int, int]) -> bool:
    """runc's reading of a rule: conditions on different arguments must all
    hold, and conditions on the same argument become rules of their own."""
    by_index: dict[int, list[dict[str, Any]]] = {}
    for condition in rule.get("args") or []:
        by_index.setdefault(condition["index"], []).append(condition)
    return all(
        any(holds(condition, args) for condition in conditions)
        for conditions in by_index.values()
    )


def allowed(profile: dict[str, Any], name: str, **args: int) -> bool:
    """Whether the call, with arguments given as a0=…, a2=…, is allowed."""
    values = {int(key[1:]): value for key, value in args.items()}
    actions = {
        rule["action"]
        for rule in profile["syscalls"]
        if name in rule["names"] and applies(rule) and matches(rule, values)
    }
    return actions == {"SCMP_ACT_ALLOW"}


def test_the_committed_profile_is_the_generated_one() -> None:
    committed = seccomp.PROFILE.read_text()

    assert committed == seccomp.render(seccomp.generate(upstream()))


def test_a_change_in_the_vendored_allow_list_changes_the_profile(
    profile: dict[str, Any],
) -> None:
    changed = upstream()
    changed["syscalls"][0]["names"].append("keyctl")

    assert seccomp.generate(changed) != profile


def test_moved_architectures_fail_the_generation() -> None:
    changed = upstream()
    for entry in changed["archMap"]:
        if entry["architecture"] == "SCMP_ARCH_X86_64":
            entry["subArchitectures"].remove("SCMP_ARCH_X86")

    with pytest.raises(ValueError, match="x86-64 architectures"):
        seccomp.generate(changed)


def test_32_bit_x86_is_not_an_architecture_of_the_profile(
    profile: dict[str, Any],
) -> None:
    (x86_64,) = [
        entry
        for entry in profile["archMap"]
        if entry["architecture"] == "SCMP_ARCH_X86_64"
    ]

    assert x86_64["subArchitectures"] == ["SCMP_ARCH_X32"]


@pytest.mark.parametrize("name", seccomp.BUBBLEWRAP_CALLS)
def test_bubblewraps_calls_are_allowed(profile: dict[str, Any], name: str) -> None:
    assert not allowed(upstream(), name, a0=0x10000000)
    assert allowed(profile, name, a0=0x10000000)


@pytest.mark.parametrize("name", REFUSED)
def test_dockers_refusals_stay(profile: dict[str, Any], name: str) -> None:
    assert not allowed(profile, name)


def test_netfilter_sockets_are_refused(profile: dict[str, Any]) -> None:
    assert allowed(upstream(), "socket", a0=AF_NETLINK, a2=NETLINK_NETFILTER)

    assert not allowed(profile, "socket", a0=AF_NETLINK, a2=NETLINK_NETFILTER)


@pytest.mark.parametrize(
    ("family", "protocol"),
    [
        (AF_NETLINK, HIGH_BIT | NETLINK_NETFILTER),
        (HIGH_BIT | AF_NETLINK, NETLINK_NETFILTER),
        (HIGH_BIT | AF_NETLINK, HIGH_BIT | NETLINK_NETFILTER),
    ],
)
def test_high_bits_do_not_reopen_netfilter_sockets(
    profile: dict[str, Any], family: int, protocol: int
) -> None:
    # The kernel reads both arguments as 32-bit ints, so these are netfilter
    # sockets too.
    assert not allowed(profile, "socket", a0=family, a2=protocol)


def test_other_sockets_stay_allowed(profile: dict[str, Any]) -> None:
    assert allowed(profile, "socket", a0=AF_NETLINK, a2=NETLINK_ROUTE)
    assert allowed(profile, "socket", a0=AF_INET, a2=IPPROTO_TCP)
    assert allowed(profile, "socket", a0=AF_INET, a2=NETLINK_NETFILTER)
