"""Each session's cgroup, made before the session and removed after it (KTD21).

A run's cgroup is <root>/run-<task run ID>, under the subtree the agent
worker's entrypoint delegated to it. Its limits come from
corvo.worker.defaults: memory without swap, killed as one group when it runs
out, one CPU and a process limit. The wrapper moves itself into it before it
starts bubblewrap, so every process of the session runs there.

Every operation takes the cgroup's path, so tests drive them on a plain
directory tree.
"""

import contextlib
from dataclasses import dataclass
from pathlib import Path

from corvo.worker.defaults import AGENT_CPUS, AGENT_MEMORY, AGENT_PIDS_LIMIT

# The CFS period cpu.max is written with, in microseconds.
CPU_PERIOD = 100_000

LIMITS = {
    "memory.max": str(AGENT_MEMORY),
    "memory.swap.max": "0",
    # The kernel kills every process of the session when one runs it out of
    # memory, not one at random.
    "memory.oom.group": "1",
    "cpu.max": f"{AGENT_CPUS * CPU_PERIOD} {CPU_PERIOD}",
    "pids.max": str(AGENT_PIDS_LIMIT),
}

# The controllers the limits need in every run's cgroup.
CONTROLLERS = "+cpu +memory +pids"


@dataclass(frozen=True)
class Cgroup:
    path: Path

    def kill(self) -> None:
        """Kills every process in the cgroup, and every one joining it while
        the kill runs."""
        (self.path / "cgroup.kill").write_text("1")

    def populated(self) -> bool:
        return read_keyed(self.path / "cgroup.events").get("populated") != 0

    def oom_kills(self) -> int:
        """How many processes the kernel killed for lack of memory."""
        return read_keyed(self.path / "memory.events").get("oom_kill", 0)

    def remove(self) -> None:
        """Removes the emptied cgroup, whose control files go with it."""
        self.path.rmdir()


def create(root: Path, task_run_id: str) -> Cgroup:
    """The run's cgroup, with every limit written, or none at all."""
    # Enabling them again is harmless, and spares the worker's start the order.
    (root / "cgroup.subtree_control").write_text(CONTROLLERS)
    cgroup = Cgroup(root / f"run-{task_run_id}")
    cgroup.path.mkdir()
    try:
        for name, value in LIMITS.items():
            (cgroup.path / name).write_text(value)
    except BaseException:
        # One the kernel will not remove is left for the next start's sweep.
        with contextlib.suppress(OSError):
            cgroup.remove()
        raise
    return cgroup


def read_keyed(path: Path) -> dict[str, int]:
    """A flat keyed file such as cgroup.events: one "key value" per line."""
    keyed = {}
    for line in path.read_text().splitlines():
        key, _, value = line.partition(" ")
        keyed[key] = int(value)
    return keyed
