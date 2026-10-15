"""The integration suite's own rootless Podman, as the test user (KTD15).

The tests reach it as the worker will: through docker-py, over the socket of
`podman system service`, the Docker-compatible API Podman documents for
Docker's clients. The service runs for the session, with no idle timeout
(`--time=0`), on a socket in the session's agent root.
"""

import json
import os
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import docker
from docker import DockerClient
from docker.errors import DockerException

# The label every container the agents start carries, and that teardown
# removes by.
MANAGED_KEY = "corvo.managed"
MANAGED = f"{MANAGED_KEY}=true"


def podman_available() -> bool:
    if shutil.which("podman") is None:
        return False
    return subprocess.run(["podman", "info"], capture_output=True).returncode == 0


def user_session_env() -> dict[str, str]:
    """The environment of the test user's systemd session, when there is one.

    Rootless Podman sets a container's cgroup limits through the user's
    systemd. Without a session it falls back to cgroupfs, where cgroup v2
    gives an unprivileged user no controller and a limited container fails
    to start. GitHub's runners already have one, as a CI run showed, so the
    suite starts none of its own.
    """
    runtime_dir = Path(f"/run/user/{os.getuid()}")
    bus = runtime_dir / "bus"
    if not bus.exists():
        return {}
    return {
        "XDG_RUNTIME_DIR": str(runtime_dir),
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}",
    }


def describe_podman(env: dict[str, str]) -> str:
    """Podman's version, network and cgroup setup, for the session's log."""
    info = json.loads(
        subprocess.run(
            ["podman", "info", "--format", "json"],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
    )
    host = info["host"]
    # Podman 4 does not report its rootless network command; 5 added it.
    network = host.get("rootlessNetworkCmd", "unreported")
    return (
        f"podman {info['version']['Version']}, network "
        f"{host['networkBackend']}/{network}, cgroups "
        f"{host['cgroupVersion']} through {host['cgroupManager']}"
    )


@contextmanager
def podman_service(root: Path, env: dict[str, str]) -> Iterator[DockerClient]:
    """`podman system service` on `<root>/podman.sock`, and a client of it.

    On the way out it removes every container the tests left with the
    managed label, then stops the service.
    """
    socket = root / "podman.sock"
    service = subprocess.Popen(
        ["podman", "system", "service", "--time=0", f"unix://{socket}"],
        env=env,
        start_new_session=True,
    )
    try:
        client = wait_for_service(socket, service)
        try:
            yield client
        finally:
            for container in client.containers.list(
                all=True, filters={"label": MANAGED}
            ):
                container.remove(force=True)
            client.close()
    finally:
        service.terminate()
        try:
            service.wait(timeout=10)
        except subprocess.TimeoutExpired:
            service.kill()
            service.wait()


def wait_for_service(socket: Path, service: subprocess.Popen[bytes]) -> DockerClient:
    for _ in range(30):
        if service.poll() is not None:
            raise RuntimeError(
                f"podman system service exited with {service.returncode}"
            )
        if socket.exists():
            client = docker.DockerClient(base_url=f"unix://{socket}")
            try:
                client.ping()
                return client
            except DockerException:
                client.close()
        time.sleep(1)
    raise RuntimeError("podman system service did not answer within 30 seconds")
