import asyncio
import json
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
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from hatchet_sdk import ClientConfig, ClientTLSConfig, Hatchet, V1TaskStatus
from hatchet_sdk.clients.admin import TaskRunDetail
from hatchet_sdk.runnables.workflow import Standalone

from corvo.agents.dir_summary.models import DirSummaryOutput
from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.worker.agent_calls import DirSummaryTaskInput

HERE = Path(__file__).parent
ROOT = HERE.parents[3]
# The tenant hatchet-admin quickstart creates, in Hatchet's Docker Compose
# guide.
TENANT_ID = "707d0855-80ab-4e1f-a156-f1c4546cbf52"

# KTD15's CI-only overlay, and the agent worker without its seccomp profile.
APPARMOR = HERE / "compose.apparmor.yaml"
NO_SECCOMP = HERE / "compose.no-seccomp.yaml"

USERNS_SYSCTL = Path("/proc/sys/kernel/apparmor_restrict_unprivileged_userns")

# The credential the test stack's proxy holds, which reaches only the scripted
# API.
TEST_CREDENTIAL = "corvo-test-credential"

# What bubblewrap needs from the container, and nothing more of the host.
BUBBLEWRAP = [
    "bwrap",
    "--unshare-all",
    "--die-with-parent",
    "--ro-bind",
    "/usr",
    "/usr",
    "--symlink",
    "usr/lib",
    "/lib",
    "--symlink",
    "usr/lib64",
    "/lib64",
    "--proc",
    "/proc",
    "--dev",
    "/dev",
    "/usr/bin/true",
]

DONE = {V1TaskStatus.COMPLETED, V1TaskStatus.FAILED, V1TaskStatus.CANCELLED}

# Run in the agent worker: the command of every session process, its
# wrappers, bubblewraps and engines, the container's pid namespace shows.
SESSION_PROCESSES = """
import os
from pathlib import Path
names = ("corvo-agent-sandbox", "bwrap", "fake/claude")
for pid in Path("/proc").iterdir():
    if pid.name.isdigit() and int(pid.name) != os.getpid():
        try:
            command = (pid / "cmdline").read_bytes().replace(b"\\0", b" ").decode()
        except OSError:
            continue
        if any(name in command for name in names):
            print(command)
"""


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


def docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0


def write_env_file(path: Path, grpc_port: int, api_port: int, agent_root: Path) -> None:
    """.env.example, with the engine and the API on the host's free ports,
    the agents' root the tests made, and the test credential."""
    overrides = {
        "HATCHET_TEST_GRPC_PORT": str(grpc_port),
        "HATCHET_TEST_API_PORT": str(api_port),
        "HATCHET_GRPC_BROADCAST_ADDRESS": f"localhost:{grpc_port}",
        "HATCHET_SERVER_URL": f"http://localhost:{api_port}",
        "HATCHET_AUTH_COOKIE_DOMAIN": f"localhost:{api_port}",
        "CORVO_TEST_AGENT_ROOT": str(agent_root),
        "CORVO_AGENT_CREDENTIAL": TEST_CREDENTIAL,
    }
    lines = [
        line
        for line in (ROOT / ".env.example").read_text().splitlines()
        if line.partition("=")[0] not in overrides
    ]
    lines += [f"{key}={value}" for key, value in overrides.items()]
    path.write_text("\n".join(lines) + "\n")


def lift_apparmor(
    bubblewrap: Callable[[bool], subprocess.CompletedProcess[str]], where: str
) -> list[str]:
    """KTD15's CI-only branch: each adjustment, in order, until bubblewrap
    starts. bubblewrap(unconfined) starts it, under apparmor=unconfined when
    asked. It returns the adjustments made."""
    adjustments: list[str] = []
    started = bubblewrap(False)
    if started.returncode == 0:
        return adjustments
    if not os.environ.get("CI"):
        pytest.fail(f"bubblewrap is refused in {where}: {started.stderr}")
    if USERNS_SYSCTL.exists() and USERNS_SYSCTL.read_text().strip() == "1":
        subprocess.run(
            ["sudo", "sysctl", "-w", "kernel.apparmor_restrict_unprivileged_userns=0"],
            check=True,
        )
        adjustments.append("kernel.apparmor_restrict_unprivileged_userns=0")
        started = bubblewrap(False)
    if started.returncode != 0:
        adjustments.append("apparmor=unconfined")
        started = bubblewrap(True)
    if started.returncode != 0:
        pytest.fail(
            f"bubblewrap is refused in {where} after {adjustments}: {started.stderr}"
        )
    return adjustments


def report_line(config: pytest.Config, line: str) -> None:
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(line)


async def finished_tasks(
    hatchet: Hatchet, run_id: str, count: int
) -> dict[str, TaskRunDetail]:
    """Polls the run's details until its `count` tasks are done, keyed by
    name, as Hatchet's on_failure test does. The caller bounds the wait."""
    while True:
        details = await hatchet.runs.aio_get_details(run_id)
        tasks = {task.readable_id: task for task in details.task_runs.values()}
        if len(tasks) == count and all(task.status in DONE for task in tasks.values()):
            return tasks
        await asyncio.sleep(1)


@dataclass(frozen=True)
class Stack:
    """This session's compose project, and the token its workers share."""

    # docker compose, with the project's name, its .env and its files.
    command: list[str]
    token: str
    agent_root: Path

    def compose(self, *args: str, overlays: Sequence[Path] = ()) -> list[str]:
        files = [arg for overlay in overlays for arg in ("--file", str(overlay))]
        return [*self.command, *files, *args]


@pytest.fixture(scope="session")
def stack(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Stack]:
    """Hatchet, run from compose.yaml for this session alone, and a token.

    The project has a name of its own and its own .env, and opens only free
    ports on the host, so it never meets a compose project already running.
    The agents' root is a directory of its own, readable by the agent
    worker's uid 1000, which the runner's user may not be.
    """
    if not docker_available():
        if os.environ.get("CI"):
            pytest.fail("Docker is not available on CI")
        pytest.skip("Docker is not available")

    agent_root = Path(tempfile.mkdtemp(prefix="corvo-agents-"))
    (agent_root / "workdirs").mkdir()
    for directory in (agent_root, agent_root / "workdirs"):
        directory.chmod(0o755)
    env_file = tmp_path_factory.mktemp("compose") / ".env"
    write_env_file(
        env_file, grpc_port=free_port(), api_port=free_port(), agent_root=agent_root
    )
    command = [
        "docker",
        "compose",
        "--project-name",
        f"corvo-test-{uuid.uuid4().hex[:8]}",
        "--env-file",
        str(env_file),
        "--file",
        str(ROOT / "compose.yaml"),
        "--file",
        str(HERE / "compose.yaml"),
    ]
    try:
        subprocess.run(
            [
                *command,
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
                *command,
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
        token = created.stdout.strip().splitlines()[-1]
        yield Stack(command=command, token=token, agent_root=agent_root)
    finally:
        subprocess.run([*command, "down", "--volumes"], check=True)
        shutil.rmtree(agent_root, ignore_errors=True)


@pytest.fixture(scope="session")
def hatchet_token(stack: Stack) -> str:
    return stack.token


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


@dataclass
class AgentWorker:
    """The agent worker's compose service, in this session's stack."""

    stack: Stack
    # The overlays it runs with: on CI, the AppArmor one when bubblewrap
    # needs it.
    overlays: list[Path] = field(default_factory=list)
    # What triggering tone did before any agent worker had registered: the
    # run's ID, or the error it raised.
    first_run: str | Exception | None = None

    def compose(self, *args: str, extra: Sequence[Path] = ()) -> list[str]:
        # The CI overlay last, so it adds to what extra overrides.
        return self.stack.compose(*args, overlays=[*extra, *self.overlays])

    def run(
        self, *args: str, extra: Sequence[Path] = (), check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.compose(*args, extra=extra),
            env={**os.environ, "HATCHET_CLIENT_TOKEN": self.stack.token},
            check=check,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def up(self) -> None:
        """Starts it, or starts it again as compose.yaml has it, and waits
        until its start checks pass and its healthcheck answers."""
        started = self.run(
            "up", "--detach", "--wait", "agent-worker", "scripted-api", check=False
        )
        if started.returncode != 0:
            logs = self.logs()
            pytest.fail(f"the agent worker did not start:\n{started.stderr}\n{logs}")

    def logs(self) -> str:
        return self.run("logs", "--no-log-prefix", "agent-worker").stdout

    def api_requests(self) -> list[dict[str, Any]]:
        """Each request the scripted API received, through the proxy."""
        read = self.run(
            "exec", "-T", "scripted-api", "sh", "-c", "cat /tmp/log.jsonl || true"
        )
        return [json.loads(line) for line in read.stdout.splitlines()]

    def run_cgroups(self) -> list[str]:
        listed = self.run("exec", "-T", "agent-worker", "ls", "/sys/fs/cgroup/agents")
        return sorted(name for name in listed.stdout.split() if name.startswith("run-"))

    def session_processes(self) -> list[str]:
        found = self.run(
            "exec", "-T", "agent-worker", "python", "-c", SESSION_PROCESSES
        )
        return found.stdout.splitlines()


def tone_stub(hatchet: Hatchet) -> Standalone[ToneInput, ToneOutput]:
    return hatchet.stubs.task(
        name="tone", input_validator=ToneInput, output_validator=ToneOutput
    )


def dir_summary_stub(
    hatchet: Hatchet,
) -> Standalone[DirSummaryTaskInput, DirSummaryOutput]:
    return hatchet.stubs.task(
        name="dir-summary",
        input_validator=DirSummaryTaskInput,
        output_validator=DirSummaryOutput,
    )


@pytest.fixture
def workdir(stack: Stack) -> Iterator[Path]:
    """A working directory below <root>/workdirs, as a caller creates one
    (KTD7), removed after. Anyone may write it, the agent worker's uid 1000
    included whatever the runner's uid, so only the sandbox's read-only bind
    keeps a session from writing there."""
    path = Path(tempfile.mkdtemp(dir=stack.agent_root / "workdirs"))
    path.chmod(0o777)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session")
def agent_worker(
    stack: Stack, hatchet: Hatchet, pytestconfig: pytest.Config
) -> AgentWorker:
    """The agent worker, started once its image builds and, on CI, once
    bubblewrap runs in it. A tone run is triggered first, before any agent
    worker has ever registered, for test_agents to record what Hatchet did."""
    worker = AgentWorker(stack)
    try:
        worker.first_run = (
            tone_stub(hatchet)
            .run(ToneInput(text="the first deployment"), wait_for_result=False)
            .workflow_run_id
        )
    except Exception as error:
        worker.first_run = error

    worker.run("build", "agent-worker")

    def bubblewrap(unconfined: bool) -> subprocess.CompletedProcess[str]:
        return worker.run(
            "run",
            "--rm",
            "--no-deps",
            "-T",
            "agent-worker",
            *BUBBLEWRAP,
            extra=[APPARMOR] if unconfined else [],
            check=False,
        )

    adjustments = lift_apparmor(bubblewrap, "the agent worker's compose service")
    if "apparmor=unconfined" in adjustments:
        worker.overlays.append(APPARMOR)
    report_line(
        pytestconfig,
        f"agent worker: CI adjustment: {', '.join(adjustments) or 'none'}",
    )
    worker.up()
    return worker
