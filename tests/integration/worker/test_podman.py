"""The proof that rootless Podman runs the agents' container as KTD6 specifies.

Every later agent unit leans on it: a container with every capability
dropped, a read-only root, size-limited tmpfs mounts and memory, CPU and
process limits starts, and the limits apply inside it. The flags are written
out here, since there is no container piece yet; its spec replaces them.
"""

import json
import uuid
from typing import Any

import pytest
from docker import DockerClient

from .podman import MANAGED, MANAGED_KEY

# The Python the app's image is built on, named in full: Podman resolves no
# short name without a registries.conf that allows it.
IMAGE = "docker.io/library/python:3.14.7-slim"
GIB = 1024**3

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
def image(podman: DockerClient) -> str:
    podman.images.pull(IMAGE)
    return IMAGE


def agent_container(**labels: str) -> dict[str, Any]:
    """docker-py's arguments for a container with KTD6's hardening and
    limits, and the managed label teardown removes it by."""
    return {
        "cap_drop": ["ALL"],
        "security_opt": ["no-new-privileges"],
        "read_only": True,
        "init": True,
        "tmpfs": {
            "/tmp": "rw,noexec,nosuid,nodev,size=100m",
            "/home/agent": "rw,noexec,nosuid,nodev,size=500m",
        },
        "mem_limit": 2 * GIB,
        "memswap_limit": 2 * GIB,
        "nano_cpus": 1_000_000_000,
        "pids_limit": 256,
        "labels": {MANAGED_KEY: "true", **labels},
        "name": f"corvo-test-{uuid.uuid4().hex[:8]}",
    }


def test_the_hardened_container_applies_its_limits(
    podman: DockerClient, image: str
) -> None:
    container = podman.containers.run(
        image, ["python", "-c", PROBE], detach=True, **agent_container()
    )
    try:
        assert container.wait(timeout=60)["StatusCode"] == 0
        report = json.loads(container.logs(stderr=False))
    finally:
        container.remove(force=True)

    assert report == {
        "memory.max": str(2 * GIB),
        "cpu.max": "100000 100000",
        "pids.max": "256",
        "CapEff": "0000000000000000",
        "root writable": False,
        "tmp writable": True,
    }


def test_positive_label_filters_find_the_deployment(
    podman: DockerClient, image: str
) -> None:
    container = podman.containers.create(
        image, ["true"], **agent_container(**{"corvo.deployment": "x"})
    )

    def listed(deployment: str) -> list[str | None]:
        filters: dict[str, str | list[str] | bool] = {
            "label": [MANAGED, f"corvo.deployment={deployment}"]
        }
        return [c.id for c in podman.containers.list(all=True, filters=filters)]

    try:
        assert container.id in listed("x")
        assert container.id not in listed("y")
    finally:
        container.remove(force=True)


def test_kill_and_force_remove_leave_no_container(
    podman: DockerClient, image: str
) -> None:
    settings = agent_container()
    container = podman.containers.run(image, ["sleep", "300"], detach=True, **settings)
    container.kill()
    container.remove(force=True)

    left = podman.containers.list(all=True, filters={"name": settings["name"]})
    assert left == []
