"""A run's cgroup in place of cgroupfs, which the session piece's tests use.

It creates the cgroup with corvo's own cgroups.create on a plain directory, so
its limits are the ones a real run writes, and scripts the kernel's side:
whether the cgroup is still populated on each poll, and its OOM kills. It
records each kill and the removal, in one list that a test's agent writes
to as well, so a test reads their order.
"""

import shutil
from collections.abc import Callable
from pathlib import Path

from corvo.worker.agent_runtime import cgroups

CREATE = cgroups.create


class Tree:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "unmade"
        self.events: list[str] = []
        # What populated() returns on each poll, then False.
        self.polls: list[bool] = []
        self.oom = 0
        # The cgroup's files as they were when it was removed.
        self.removed: dict[str, str] | None = None
        # Runs once the cgroup is made.
        self.after_create: Callable[[], object] = lambda: None

    def create(self, root: Path, task_run_id: str) -> Tree:
        self.path = CREATE(root, task_run_id).path
        self.events.append("create")
        self.after_create()
        return self

    def kill(self) -> None:
        self.events.append("kill")

    def populated(self) -> bool:
        return self.polls.pop(0) if self.polls else False

    def oom_kills(self) -> int:
        return self.oom

    def remove(self) -> None:
        # cgroupfs drops its control files on rmdir; a directory keeps them.
        self.removed = {path.name: path.read_text() for path in self.path.iterdir()}
        shutil.rmtree(self.path)
        self.events.append("remove")
