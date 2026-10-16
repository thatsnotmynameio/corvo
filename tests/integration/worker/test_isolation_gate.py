"""The proof that the agent worker's image isolates a session as the plan
needs it to (U1).

Every later agent unit leans on it. The image runs with the security options
its compose service will have, on an internal network, and its driver
(gate/driver.py) reports what it found: bubblewrap starts clean, the real
engine's sandbox runs a Bash call nested in it, a run's cgroup limits apply,
and calls to other hosts fail fast. When bubblewrap is refused on CI, the
gate lifts the runner's AppArmor restrictions as KTD15 describes, and logs
which it needed.
"""

import json
import os
import subprocess
import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from corvo.worker.agent_runtime.sandbox import PLACEHOLDER
from corvo.worker.defaults import AGENT_PIDS_LIMIT

from .conftest import BUBBLEWRAP, ROOT, docker_available, lift_apparmor

IMAGE = "corvo-agent-worker:gate"
SECCOMP = ROOT / "src" / "corvo" / "worker" / "agent_runtime" / "seccomp.json"
DRIVER = "/app/tests/integration/worker/gate/driver.py"
UNCONFINED = ["--security-opt", "apparmor=unconfined"]

# The variables a session's engine may hold (KTD20), and the PWD bubblewrap
# sets for its --chdir.
ALLOWED = {
    "PWD",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_AGENT_SDK_VERSION",
    "CLAUDE_CODE_SDK_READS_SESSION_STATE",
    "HOME",
    "CLAUDE_CONFIG_DIR",
    "PATH",
    "CLAUDE_CODE_SUBPROCESS_ENV_SCRUB",
    "CLAUDE_CODE_DISABLE_AUTO_MEMORY",
    "CLAUDE_CODE_DISABLE_CLAUDE_MDS",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CODE_SKIP_PROMPT_HISTORY",
    "ENABLE_CLAUDEAI_MCP_SERVERS",
}


def run(options: list[str], *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "run", "--rm", *options, IMAGE, *command],
        capture_output=True,
        text=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def report(pytestconfig: pytest.Config) -> Iterator[dict[str, Any]]:
    if not docker_available():
        if os.environ.get("CI"):
            pytest.fail("Docker is not available on CI")
        pytest.skip("Docker is not available")

    subprocess.run(
        ["docker", "build", "--target", "agent-worker", "--tag", IMAGE, str(ROOT)],
        check=True,
    )
    network = f"corvo-gate-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "network", "create", "--internal", network],
        check=True,
        capture_output=True,
    )
    options = [
        "--init",
        "--security-opt",
        f"seccomp={SECCOMP}",
        "--security-opt",
        "systempaths=unconfined",
        "--security-opt",
        "writable-cgroups=true",
        "--network",
        network,
        "--volume",
        f"{ROOT / 'tests'}:/app/tests:ro",
    ]
    try:
        adjustments = lift_apparmor(
            lambda unconfined: run(
                options + UNCONFINED if unconfined else options, *BUBBLEWRAP
            ),
            "the agent worker",
        )
        if "apparmor=unconfined" in adjustments:
            options.extend(UNCONFINED)
        ran = run(options, "python", DRIVER)
        assert ran.returncode == 0, ran.stderr
        found: dict[str, Any] = json.loads(ran.stdout.splitlines()[-1])
        environment = found["environment"]
        reporter = pytestconfig.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(
                f"agent worker gate: {environment['bubblewrap']}, kernel "
                f"{environment['kernel']}, CI adjustment: "
                f"{', '.join(adjustments) or 'none'}"
            )
        yield found
    finally:
        subprocess.run(["docker", "network", "rm", network], capture_output=True)


def test_the_worker_runs_as_uid_1000_in_its_cgroup(report: dict[str, Any]) -> None:
    assert report["environment"]["uid"] == 1000
    assert report["environment"]["cgroup"] == "0::/agents/worker"


def test_the_cgroup_mount_delegates_by_namespace(report: dict[str, Any]) -> None:
    assert "nsdelegate" in report["environment"]["cgroup2 options"]


def test_the_worker_has_no_privilege_to_gain(report: dict[str, Any]) -> None:
    none = "0000000000000000"

    assert report["environment"]["privileges"] == {
        "NoNewPrivs": "1",
        "CapInh": none,
        "CapPrm": none,
        "CapEff": none,
        "CapBnd": none,
        "CapAmb": none,
    }
    assert report["environment"]["setuid files"] == []


def test_netfilter_sockets_are_refused(report: dict[str, Any]) -> None:
    # EPROTONOSUPPORT is the profile's own answer; a 32-bit call ends in the
    # filter's bad-architecture action, SIGSYS.
    assert report["netlink"] == {
        "route": "opened",
        "netfilter": "EPROTONOSUPPORT",
        "netfilter, protocol's high bits": "EPROTONOSUPPORT",
        "netfilter, family's high bits": "EPROTONOSUPPORT",
        "netfilter, 32-bit socketcall": "killed by signal 31",
    }


def test_a_call_to_another_host_fails_fast(report: dict[str, Any]) -> None:
    assert report["outside"]["outcome"] != "connected"
    assert report["outside"]["seconds"] < 5


def test_the_sandbox_sees_only_its_allowed_variables(report: dict[str, Any]) -> None:
    environ = report["probe"]["environ"]

    assert "1" in environ
    for pid, names in environ.items():
        assert isinstance(names, list), f"pid {pid}: {names}"
        assert set(names) <= ALLOWED, f"pid {pid}"


def test_the_sandbox_sees_only_its_own_processes(report: dict[str, Any]) -> None:
    processes = report["probe"]["processes"]

    assert sorted(processes.values()) == ["/usr/bin/bwrap", "/usr/local/bin/python3"]


def test_the_sandbox_works_in_its_working_directory_read_only(
    report: dict[str, Any],
) -> None:
    assert report["probe"]["cwd"] == report["probe"]["workdir"]
    assert report["probe"]["cwd writable"] is False


def test_the_wrapper_runs_the_engine_in_its_runs_cgroup(
    report: dict[str, Any],
) -> None:
    assert report["probe"]["pids.peak"] >= 1
    assert report["session"]["pids.peak"] >= 1


def test_the_sandbox_has_no_sys(report: dict[str, Any]) -> None:
    assert report["probe"]["sys"] is False
    assert report["probe"]["cgroup"] == "0::/"


def test_the_engine_runs_a_sandboxed_bash_call(report: dict[str, Any]) -> None:
    session = report["session"]

    assert session.get("error") is None, session
    assert session["subtype"] == "success", session
    # Only loopback: the SDK's own sandbox took the command off the network
    # the engine itself shares.
    assert session["result"] == "corvo-gate lo", session
    assert "eth0" in report["probe"]["interfaces"]
    assert session["seconds"] < 30


def test_the_engine_sends_only_the_placeholder(report: dict[str, Any]) -> None:
    requests = report["session"]["requests"]

    assert requests
    for request in requests:
        assert request["headers"].get("x-api-key") == PLACEHOLDER
        assert "authorization" not in {name.lower() for name in request["headers"]}


def test_the_hog_stops_at_its_process_limit_and_dies_at_its_memory_limit(
    report: dict[str, Any],
) -> None:
    hog = report["hog"]

    forks, created, error = hog["stdout"][0].split()
    assert (forks, error) == ("forks", "11"), hog
    assert int(created) < AGENT_PIDS_LIMIT
    assert hog["pids.events"]["max"] >= 1
    assert hog["returncode"] == -9, hog
    assert hog["memory.events"]["oom_kill"] >= 1


def test_the_hog_leaves_the_worker_alone(report: dict[str, Any]) -> None:
    assert report["hog"]["worker cgroup unchanged"] is True
    assert report["hog"]["worker memory.events"]["oom_kill"] == 0


def test_without_cli_path_the_sdk_finds_no_engine(report: dict[str, Any]) -> None:
    assert report["without cli_path"] == "CLINotFoundError"
