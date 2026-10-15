"""What an agent container is, and the checks around it, as pure functions.

container_spec builds docker-py's arguments for every agent container, the
startup probe's included (KTD6): every capability dropped, no new
privileges, Podman's default seccomp profile, a read-only root, an init, two
size-limited tmpfs mounts with Anthropic's hardened flags, and the memory,
CPU and process limits from corvo.worker.defaults. The container receives
the run directory, the working directory when the run has one, the
isolation variables and at most one credential, and nothing else. Its
network is the API's default (KTD16).

The rest decides what the container piece does with what it reads: which
working directories a run may mount, what the deployment label is, which
containers the sweep removes, and whether the probe's report matches this
spec.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from docker.types import Mount
from hatchet_sdk import V1TaskStatus

from corvo.agents.envelope import ProbeReport
from corvo.worker.defaults import (
    AGENT_DEADLINE_MARGIN,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_MEMORY,
    AGENT_NANO_CPUS,
    AGENT_PIDS_LIMIT,
)

# Where the container sees the run directory and the working directory.
RUN_MOUNT = "/corvo/run"
WORKSPACE = "/workspace"

# Every agent container carries it, and every lookup filters on it.
MANAGED = "corvo.managed=true"

# The agent user's home, on its tmpfs, and the CLI's configuration in it.
HOME = "/home/agent"

# Keeps the session from reading or writing anything it would keep across
# runs, and from calling home beyond the API (KTD3).
ISOLATION_ENV = {
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1",
    "HOME": HOME,
    "CLAUDE_CONFIG_DIR": f"{HOME}/.claude",
}

type CredentialKind = Literal["api_key", "oauth_token"]

# The one variable each kind of credential reaches the CLI under.
CREDENTIAL_VARIABLES: dict[CredentialKind, str] = {
    "api_key": "ANTHROPIC_API_KEY",
    "oauth_token": "CLAUDE_CODE_OAUTH_TOKEN",
}

# The tmpfs mounts' sizes in MiB, and the flags of Anthropic's hardened
# example. docker-py's tmpfs mapping, since a tmpfs Mount gets mode 0 on
# Podman.
TMPFS_MIB = {"/tmp": 100, HOME: 500}
TMPFS_FLAGS = ("noexec", "nosuid", "nodev")

# The CFS period Podman sets for nano_cpus, in microseconds.
CPU_PERIOD = 100_000

# The capability mask of a process that holds none.
NO_CAPABILITIES = "0" * 16


@dataclass(frozen=True)
class Credential:
    kind: CredentialKind
    value: str


@dataclass(frozen=True)
class Run:
    """One attempt of an agent task, which its container is named and
    labelled after."""

    deployment: str
    # The workflow run, whose status the sweep reads.
    run_id: str
    task_run_id: str
    # Hatchet's retry count for the attempt.
    attempt: int
    agent: str

    @property
    def name(self) -> str:
        return f"corvo-agent-{self.task_run_id}-{self.attempt}"

    @property
    def labels(self) -> dict[str, str]:
        return {
            "corvo.managed": "true",
            "corvo.deployment": self.deployment,
            "corvo.run_id": self.run_id,
            "corvo.task_run_id": self.task_run_id,
            "corvo.attempt": str(self.attempt),
            "corvo.agent": self.agent,
        }


def container_spec(
    *,
    image: str,
    name: str,
    labels: dict[str, str],
    command: list[str],
    run_dir: Path,
    workdir: Path | None = None,
    writes_workdir: bool = False,
    credential: Credential | None = None,
) -> dict[str, Any]:
    """docker-py's arguments to containers.create, for one agent container."""
    mounts = [Mount(RUN_MOUNT, str(run_dir), type="bind", read_only=False)]
    if workdir is not None:
        mounts.append(
            Mount(WORKSPACE, str(workdir), type="bind", read_only=not writes_workdir)
        )
    environment = dict(ISOLATION_ENV)
    if credential is not None:
        environment[CREDENTIAL_VARIABLES[credential.kind]] = credential.value
    return {
        "image": image,
        "command": command,
        "name": name,
        "labels": labels,
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "read_only": True,
        "init": True,
        "tmpfs": {
            point: f"rw,{','.join(TMPFS_FLAGS)},size={mib}m"
            for point, mib in TMPFS_MIB.items()
        },
        "mem_limit": AGENT_MEMORY,
        "memswap_limit": AGENT_MEMORY,
        "nano_cpus": AGENT_NANO_CPUS,
        "pids_limit": AGENT_PIDS_LIMIT,
        "mounts": mounts,
        "environment": environment,
    }


class InvalidWorkdir(ValueError):
    """A working directory a run may not mount."""


def check_workdir(root: Path, workdir: Path) -> Path:
    """The working directory, resolved, when it is a directory strictly below
    <root>/workdirs once every link is followed (KTD7).

    <root>/workdirs itself is refused: it would expose every other run's.
    """
    workdirs = (root / "workdirs").resolve()
    try:
        resolved = workdir.resolve(strict=True)
    except OSError as error:
        raise InvalidWorkdir(f"{workdir} does not exist") from error
    if workdirs not in resolved.parents or not resolved.is_dir():
        raise InvalidWorkdir(f"{workdir} is not a directory below {workdirs}")
    return resolved


def deployment_label(tenant_id: str, server_url: str) -> str:
    """The Hatchet deployment a container belongs to: its tenant on its server."""
    return f"{tenant_id}@{server_url}"


# A run's status, or why the sweep could not read it.
type Lookup = V1TaskStatus | Literal["not_found", "timed_out"]

ENDED = {V1TaskStatus.COMPLETED, V1TaskStatus.FAILED, V1TaskStatus.CANCELLED}


def sweep_decision(lookup: Lookup) -> Literal["remove", "keep", "warn"]:
    """Remove a container whose run ended, keep one whose run goes on, and
    keep but warn of one whose run could not be read: a 404 does not prove
    the run ended, since Hatchet fills its read model asynchronously (KTD11).
    """
    if lookup in ("not_found", "timed_out"):
        return "warn"
    return "remove" if lookup in ENDED else "keep"


def session_budget(elapsed: float) -> float:
    """The seconds the session may take, given the seconds the task has run:
    it ends AGENT_DEADLINE_MARGIN before Hatchet's timeout (KTD4)."""
    return (AGENT_EXECUTION_TIMEOUT - AGENT_DEADLINE_MARGIN).total_seconds() - elapsed


def probe_problems(report: ProbeReport, fingerprint: str) -> list[str]:
    """Where the probe's report differs from this spec and from the worker's
    own fingerprint, one line each (KTD10)."""
    expected = {
        "memory.max": (report.memory_max, str(AGENT_MEMORY)),
        "cpu.max": (
            report.cpu_max,
            f"{AGENT_NANO_CPUS * CPU_PERIOD // 10**9} {CPU_PERIOD}",
        ),
        "pids.max": (report.pids_max, str(AGENT_PIDS_LIMIT)),
    }
    found = [
        f"{name} is {read!r}, not {wanted!r}"
        for name, (read, wanted) in expected.items()
        if read != wanted
    ]
    if report.cap_eff != NO_CAPABILITIES:
        found.append(f"the effective capabilities are {report.cap_eff}, not none")
    if not report.root_read_only:
        found.append("the root filesystem is writable")
    for point, mib in TMPFS_MIB.items():
        options = report.mounts.get(point, [])
        missing = [flag for flag in TMPFS_FLAGS if flag not in options]
        if missing:
            found.append(f"{point} lacks {', '.join(missing)}")
        # The kernel reports the size in KiB.
        if f"size={mib * 1024}k" not in options:
            found.append(f"{point} is not size={mib * 1024}k")
    found += [
        f"the environment lacks {name}"
        for name in ISOLATION_ENV
        if name not in report.env_names
    ]
    found += [
        f"the environment holds {name}"
        for name in CREDENTIAL_VARIABLES.values()
        if name in report.env_names
    ]
    if report.fingerprint != fingerprint:
        found.append("the image's fingerprint differs from the worker's: rebuild it")
    return found


def egress_open(report: ProbeReport) -> bool:
    """Whether the container reached its gateway or the metadata address,
    which the production nftables rule blocks (KTD16)."""
    return bool(report.gateway_reachable) or report.metadata_reachable
