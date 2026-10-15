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
from contextlib import contextmanager
from dataclasses import dataclass
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

AGENT_IMAGE = "localhost/corvo-agent:latest"
FAKE_IMAGE = "localhost/corvo-agent-fake:latest"


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


@dataclass
class Podman:
    """The session's rootless Podman, as the test user."""

    client: DockerClient
    # The agent root its socket sits in, which the worker runs agents under.
    root: Path
    socket: Path
    # The environment the podman commands run with.
    env: dict[str, str]


@pytest.fixture(scope="session")
def podman_store(pytestconfig: pytest.Config) -> Iterator[Podman | None]:
    """The session's own rootless Podman, or None where there is none.

    Its socket sits in an agent root of the session's, made with mkdtemp
    rather than under pytest's temporary directories (KTD15).
    """
    if not podman_available():
        yield None
        return

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
            yield Podman(client=client, root=root, socket=root / "podman.sock", env=env)
    finally:
        shutil.rmtree(root)


@pytest.fixture(scope="session")
def podman(podman_store: Podman | None) -> Podman:
    """The session's Podman, for the tests that need it. Without Podman they
    skip, but on CI, where Podman ships with the runner, they fail."""
    if podman_store is None:
        if os.environ.get("CI"):
            pytest.fail("Podman is not available on CI")
        pytest.skip("Podman is not available")
    return podman_store


@pytest.fixture(scope="session")
def agent_image(
    podman_store: Podman | None, tmp_path_factory: pytest.TempPathFactory
) -> str | None:
    """The agent image with the fake claude CLI in place of the real one,
    built from the repository in the session's Podman, or None without it."""
    if podman_store is None:
        return None
    build = ["podman", "build", "--quiet"]
    subprocess.run(
        [*build, "--target", "agent", "--tag", AGENT_IMAGE, str(ROOT)],
        env=podman_store.env,
        check=True,
    )
    # The fake image's build context holds only the fake.
    context = tmp_path_factory.mktemp("fake-image")
    shutil.copy(ROOT / "tests" / "agents" / "fake_claude.py", context)
    shutil.copy(ROOT / "tests" / "agents" / "fake" / "Containerfile", context)
    subprocess.run(
        [
            *build,
            "--build-arg",
            f"AGENT_IMAGE={AGENT_IMAGE}",
            "--tag",
            FAKE_IMAGE,
            str(context),
        ],
        env=podman_store.env,
        check=True,
    )
    return FAKE_IMAGE


@pytest.fixture(scope="session")
def worker_env(
    hatchet_token: str, podman_store: Podman | None, agent_image: str | None
) -> dict[str, str]:
    """corvo-worker's environment, as its compose service runs it, with the
    session's token. Where there is Podman, agents run on it, with a
    credential the fake ignores."""
    env = {
        **os.environ,
        "CORVO_HATCHET_TOKEN": hatchet_token,
        "HATCHET_CLIENT_WORKER_HEALTHCHECK_ENABLED": "True",
    }
    if podman_store is not None and agent_image is not None:
        env |= {
            "CORVO_AGENT_PODMAN_SOCKET": str(podman_store.socket),
            "CORVO_AGENT_ROOT": str(podman_store.root),
            "CORVO_AGENT_IMAGE": agent_image,
            "CORVO_AGENT_CREDENTIAL": "not-a-credential",
        }
    return env


@dataclass
class WorkerProcess:
    process: subprocess.Popen[bytes]
    # Where its output goes.
    log: Path


def wait_for_health(port: int, worker: WorkerProcess) -> None:
    """Waits for the worker's healthcheck, as Hatchet's own tests do. The
    worker prepares agents first, within 45 seconds, and a first container
    starts cold."""
    for _ in range(120):
        if worker.process.poll() is not None:
            raise RuntimeError(
                f"The worker exited with {worker.process.returncode}:\n"
                + worker.log.read_text()[-4000:]
            )
        try:
            with urllib.request.urlopen(f"http://localhost:{port}/health") as r:
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("The worker was not healthy within 120 seconds")


@contextmanager
def running_worker(env: dict[str, str], log: Path) -> Iterator[WorkerProcess]:
    """corvo-worker, with its healthcheck on a free port, until the block
    ends. Its output goes to log."""
    port = free_port()
    with log.open("wb") as output:
        worker = WorkerProcess(
            process=subprocess.Popen(
                [str(Path(sys.executable).parent / "corvo-worker")],
                env={**env, "HATCHET_CLIENT_WORKER_HEALTHCHECK_PORT": str(port)},
                stdout=output,
                stderr=subprocess.STDOUT,
                # Its own process group: the worker runs its tasks in
                # processes of its own, which stop with it.
                start_new_session=True,
            ),
            log=log,
        )
    try:
        wait_for_health(port, worker)
        yield worker
    finally:
        if worker.process.poll() is None:
            os.killpg(worker.process.pid, signal.SIGTERM)
        try:
            worker.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(worker.process.pid, signal.SIGKILL)
            worker.process.wait()


@pytest.fixture(scope="session")
def worker(
    worker_env: dict[str, str], tmp_path_factory: pytest.TempPathFactory
) -> Iterator[WorkerProcess]:
    """The session's corvo-worker."""
    log = tmp_path_factory.mktemp("worker") / "worker.log"
    with running_worker(worker_env, log) as worker:
        yield worker


@pytest.fixture(scope="session")
def hatchet(hatchet_token: str) -> Hatchet:
    """A client of the tests' own, as another service triggers corvo's tasks."""
    return Hatchet(
        config=ClientConfig(
            token=hatchet_token,
            tls_config=ClientTLSConfig(strategy="none"),
        )
    )
