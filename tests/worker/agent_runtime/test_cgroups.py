"""A run's cgroup carries every KTD21 limit, driven here on a plain directory
tree in place of cgroupfs."""

from pathlib import Path

import pytest

from corvo.worker.agent_runtime import cgroups
from corvo.worker.agent_runtime.cgroups import Cgroup


def test_a_run_s_cgroup_carries_every_limit(tmp_path: Path) -> None:
    cgroup = cgroups.create(tmp_path, "task-1")

    assert cgroup.path == tmp_path / "run-task-1"
    assert (tmp_path / "cgroup.subtree_control").read_text() == "+cpu +memory +pids"
    written = {name: (cgroup.path / name).read_text() for name in cgroups.LIMITS}
    assert written == {
        "memory.max": str(2 * 1024**3),
        "memory.swap.max": "0",
        "memory.oom.group": "1",
        "cpu.max": "100000 100000",
        "pids.max": "256",
    }


def test_a_limit_that_fails_leaves_no_cgroup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(path: Path, value: str) -> int:
        if path.name == "cpu.max":
            raise PermissionError(13, "Permission denied")
        # cgroupfs writes no file of its own, so rmdir finds the directory
        # empty.
        return 0

    monkeypatch.setattr(Path, "write_text", refuse)

    with pytest.raises(PermissionError):
        cgroups.create(tmp_path, "task-1")

    assert not (tmp_path / "run-task-1").exists()


def test_kill_writes_cgroup_kill(tmp_path: Path) -> None:
    Cgroup(tmp_path).kill()

    assert (tmp_path / "cgroup.kill").read_text() == "1"


@pytest.mark.parametrize(
    ("events", "populated"),
    [("populated 1\nfrozen 0\n", True), ("populated 0\nfrozen 0\n", False)],
)
def test_populated_reads_cgroup_events(
    tmp_path: Path, events: str, populated: bool
) -> None:
    (tmp_path / "cgroup.events").write_text(events)

    assert Cgroup(tmp_path).populated() is populated


def test_oom_kills_reads_memory_events(tmp_path: Path) -> None:
    (tmp_path / "memory.events").write_text(
        "low 0\nhigh 0\nmax 4\noom 1\noom_kill 2\noom_group_kill 1\n"
    )

    assert Cgroup(tmp_path).oom_kills() == 2


def test_remove_removes_the_emptied_cgroup(tmp_path: Path) -> None:
    path = tmp_path / "run-task-1"
    path.mkdir()

    Cgroup(path).remove()

    assert not path.exists()
