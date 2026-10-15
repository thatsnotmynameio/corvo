"""The proof that rootless Podman runs the agents' container as KTD6 specifies.

Every agent run leans on it: a container built by the container piece's own
spec, with every capability dropped, a read-only root, size-limited tmpfs
mounts and memory, CPU and process limits, starts, and the limits apply
inside it.
"""

import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from corvo.worker.agent_runtime.spec import MANAGED, container_spec
from corvo.worker.defaults import AGENT_MEMORY

from .conftest import Podman

# The Python the app's image is built on, named in full: Podman resolves no
# short name without a registries.conf that allows it.
IMAGE = "docker.io/library/python:3.14.7-slim"

# What the agents' container reports from inside it: its cgroup's limits, its
# effective capabilities, and whether the root and /tmp take a write.
PROBE = """
import json

def read(path):
    with open(path) as f:
        return f.read().strip()

def writable(path):
    try:
        with open(path, "w"):
            pass
    except OSError:
        return False
    return True

status = dict(line.split(":", 1) for line in read("/proc/self/status").splitlines())
print(json.dumps({
    "memory.max": read("/sys/fs/cgroup/memory.max"),
    "cpu.max": read("/sys/fs/cgroup/cpu.max"),
    "pids.max": read("/sys/fs/cgroup/pids.max"),
    "CapEff": status["CapEff"].strip(),
    "root writable": writable("/probe"),
    "tmp writable": writable("/tmp/probe"),
}))
"""


@pytest.fixture(scope="module")
def image(podman: Podman) -> str:
    podman.client.images.pull(IMAGE)
    return IMAGE


@pytest.fixture
def run_dir(podman: Podman) -> Iterator[Path]:
    path = podman.root / f"test-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path
    path.rmdir()


def agent_container(
    image: str, command: list[str], run_dir: Path, **labels: str
) -> dict[str, Any]:
    """The container piece's spec for a container of the tests' own."""
    return container_spec(
        image=image,
        name=f"corvo-test-{uuid.uuid4().hex[:8]}",
        labels={"corvo.managed": "true", **labels},
        command=command,
        run_dir=run_dir,
    )


def test_the_hardened_container_applies_its_limits(
    podman: Podman, image: str, run_dir: Path
) -> None:
    container = podman.client.containers.run(
        detach=True, **agent_container(image, ["python", "-c", PROBE], run_dir)
    )
    try:
        assert container.wait(timeout=60)["StatusCode"] == 0
        report = json.loads(container.logs(stderr=False))
    finally:
        container.remove(force=True)

    assert report == {
        "memory.max": str(AGENT_MEMORY),
        "cpu.max": "100000 100000",
        "pids.max": "256",
        "CapEff": "0000000000000000",
        "root writable": False,
        "tmp writable": True,
    }


def test_positive_label_filters_find_the_deployment(
    podman: Podman, image: str, run_dir: Path
) -> None:
    container = podman.client.containers.create(
        **agent_container(image, ["true"], run_dir, **{"corvo.deployment": "x"})
    )

    def listed(deployment: str) -> list[str | None]:
        filters: dict[str, str | list[str] | bool] = {
            "label": [MANAGED, f"corvo.deployment={deployment}"]
        }
        return [c.id for c in podman.client.containers.list(all=True, filters=filters)]

    try:
        assert container.id in listed("x")
        assert container.id not in listed("y")
    finally:
        container.remove(force=True)


def test_kill_and_force_remove_leave_no_container(
    podman: Podman, image: str, run_dir: Path
) -> None:
    settings = agent_container(image, ["sleep", "300"], run_dir)
    container = podman.client.containers.run(detach=True, **settings)
    container.kill()
    container.remove(force=True)

    left = podman.client.containers.list(all=True, filters={"name": settings["name"]})
    assert left == []
