import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from docker import DockerClient
from hatchet_sdk import ClientConfig, ClientTLSConfig, Hatchet

from .podman import (
    describe_podman,
    podman_available,
    podman_service,
    user_session_env,
)

ROOT = Path(__file__).parents[3]
# The tenant hatchet-admin quickstart creates, in Hatchet's Docker Compose
# guide.
TENANT_ID = "707d0855-80ab-4e1f-a156-f1c4546cbf52"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def write_env_file(path: Path, grpc_port: int, api_port: int) -> None:
    """.env.example, with the engine and the API on the host's free ports."""
    overrides = {
        "HATCHET_TEST_GRPC_PORT": str(grpc_port),
        "HATCHET_TEST_API_PORT": str(api_port),
        "HATCHET_GRPC_BROADCAST_ADDRESS": f"localhost:{grpc_port}",
        "HATCHET_SERVER_URL": f"http://localhost:{api_port}",
        "HATCHET_AUTH_COOKIE_DOMAIN": f"localhost:{api_port}",
    }
    lines = [
        line
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line.partition("=")[0] not in overrides
    ]
    lines += [f"{key}={value}" for key, value in overrides.items()]
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture(scope="session")
def hatchet_token(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A token for Hatchet, run from compose.yaml for this session alone.

    The project has a name of its own and its own .env, and opens only free
    ports on the host, so it never meets a compose project already running.
    """
    if not docker_available():
        pytest.skip("Docker is not available")

    env_file = tmp_path_factory.mktemp("compose") / ".env"
    write_env_file(env_file, grpc_port=free_port(), api_port=free_port())
    compose = [
        "docker",
        "compose",
        "--project-name",
        f"corvo-test-{uuid.uuid4().hex[:8]}",
        "--env-file",
        str(env_file),
        "--file",
        str(ROOT / "compose.yaml"),
        "--file",
        str(Path(__file__).parent / "compose.yaml"),
    ]
    try:
        subprocess.run(
            [
                *compose,
                "up",
                "--detach",
                "--wait",
                "hatchet-engine",
                "hatchet-dashboard",
            ],
            check=True,
        )
        created = subprocess.run(
            [
                *compose,
                "run",
                "--rm",
                "--no-deps",
                "hatchet-setup",
                "/hatchet/hatchet-admin",
                "token",
                "create",
                "--config",
                "/hatchet/config",
                "--tenant-id",
                TENANT_ID,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        yield created.stdout.strip().splitlines()[-1]
    finally:
        subprocess.run([*compose, "down", "--volumes"], check=True)


def wait_for_health(port: int, worker: subprocess.Popen[bytes]) -> None:
    """Waits for the worker's healthcheck, as Hatchet's own tests do."""
    for _ in range(30):
        if worker.poll() is not None:
            raise RuntimeError(f"The worker exited with {worker.returncode}")
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health") as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("The worker was not healthy within 30 seconds")


@pytest.fixture(scope="session")
def worker(hatchet_token: str) -> Iterator[None]:
    """corvo-worker, run as its compose service runs it, with the session's
    token and its healthcheck on a free port."""
    port = free_port()
    process = subprocess.Popen(
        [str(Path(sys.executable).parent / "corvo-worker")],
        env={
            **os.environ,
            "CORVO_HATCHET_TOKEN": hatchet_token,
            "HATCHET_CLIENT_WORKER_HEALTHCHECK_ENABLED": "True",
            "HATCHET_CLIENT_WORKER_HEALTHCHECK_PORT": str(port),
        },
        # Its own process group: the worker runs its tasks in processes of its
        # own, which stop with it.
        start_new_session=True,
    )
    try:
        wait_for_health(port, process)
        yield
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()


@pytest.fixture(scope="session")
def hatchet(hatchet_token: str) -> Hatchet:
    """A client of the tests' own, as another service triggers corvo's tasks."""
    return Hatchet(
        config=ClientConfig(
            token=hatchet_token,
            tls_config=ClientTLSConfig(strategy="none"),
        )
    )


@pytest.fixture(scope="session")
def podman(pytestconfig: pytest.Config) -> Iterator[DockerClient]:
    """A client of the session's own rootless Podman, as the test user.

    Its socket sits in an agent root of the session's, made with mkdtemp
    rather than under pytest's temporary directories (KTD15). Without Podman
    the tests that need it skip, but on CI, where Podman ships with the
    runner, they fail.
    """
    if not podman_available():
        if os.environ.get("CI"):
            pytest.fail("Podman is not available on CI")
        pytest.skip("Podman is not available")

    session_env = user_session_env()
    env = {**os.environ, **session_env}
    session = "found" if session_env else "none"
    # Written as the session runs, not captured: the pull request records
    # which Podman, network and user session each machine ran.
    reporter = pytestconfig.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(f"{describe_podman(env)}, user session {session}")
    root = Path(tempfile.mkdtemp(prefix="corvo-agents-"))
    try:
        with podman_service(root, env) as client:
            yield client
    finally:
        shutil.rmtree(root)
