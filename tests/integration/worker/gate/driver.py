"""The isolation gate's driver: runs inside the agent worker's image, as the
worker would, and prints what it found as one JSON report (U1).

It makes run cgroups under the subtree the entrypoint delegated, runs a probe
in the engine's place through corvo-agent-sandbox, runs one real engine
session against the scripted API, and runs a fork and memory hog in a run's
cgroup. test_isolation_gate.py asserts on the report.
"""

import asyncio
import errno
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, cast

from claude_agent_sdk import (
    ClaudeAgentOptions,
    CLINotFoundError,
    ResultMessage,
    SandboxSettings,
    query,
)

from corvo.worker.agent_runtime.sandbox import PLACEHOLDER

HERE = Path(__file__).parent
TESTS = HERE.parents[2]
AGENTS = Path("/sys/fs/cgroup/agents")
WRAPPER = str(Path(sys.executable).parent / "corvo-agent-sandbox")
ENGINE = os.environ["CORVO_AGENT_ENGINE"]
MIB = 1024**2

# A secret the worker holds, which nothing in the sandbox may see.
WORKER_SECRET = "gate-hatchet-token"

SANDBOX = cast(
    SandboxSettings,
    {
        "enabled": True,
        "autoAllowBashIfSandboxed": True,
        "allowUnsandboxedCommands": False,
        "failIfUnavailable": True,
        "network": {"allowedDomains": []},
    },
)

# The session's one Bash call: a marker, then the network interfaces the
# command sees, which only the SDK's own sandbox narrows to loopback.
COMMAND = "echo corvo-gate $(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ')"

HOG = """
import os, sys, time
with open(os.path.join(sys.argv[1], "cgroup.procs"), "w") as procs:
    procs.write(str(os.getpid()))
children = []
try:
    for _ in range(80):
        pid = os.fork()
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        children.append(pid)
except OSError as error:
    print("forks", len(children), error.errno, flush=True)
for pid in children:
    os.kill(pid, 9)
    os.waitpid(pid, 0)
held = []
for _ in range(1024):
    held.append(b"x" * (1024 * 1024))
print("allocated", len(held), flush=True)
"""


def environment() -> dict[str, Any]:
    mount = next(
        line.split(" - ", 1)[1].split()
        for line in Path("/proc/self/mountinfo").read_text().splitlines()
        if " /sys/fs/cgroup " in line
    )
    version = subprocess.run(["bwrap", "--version"], capture_output=True, text=True)
    return {
        "uid": os.getuid(),
        "kernel": os.uname().release,
        "bubblewrap": version.stdout.strip(),
        "cgroup": Path("/proc/self/cgroup").read_text().strip(),
        "cgroup2 options": mount[2].split(",") if mount[0] == "cgroup2" else mount,
    }


def netlink() -> dict[str, str]:
    """Whether the container's seccomp profile lets each netlink family open."""
    results = {}
    for name, protocol in (("route", 0), ("netfilter", 12)):
        try:
            socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, protocol).close()
            results[name] = "opened"
        except OSError as error:
            results[name] = errno.errorcode.get(error.errno or 0, str(error.errno))
    return results


def outside() -> dict[str, Any]:
    """How a call to a host outside the internal network ends, and how fast."""
    started = time.monotonic()
    try:
        socket.create_connection(("api.anthropic.com", 443), timeout=10).close()
        outcome = "connected"
    except OSError as error:
        outcome = type(error).__name__
    return {"outcome": outcome, "seconds": round(time.monotonic() - started, 2)}


def run_cgroup(name: str, memory: int, pids: int) -> Path:
    """A run's cgroup with KTD21's limits, made as the worker makes one."""
    (AGENTS / "cgroup.subtree_control").write_text("+cpu +memory +pids")
    path = AGENTS / name
    path.mkdir()
    for limit, value in (
        ("memory.max", str(memory)),
        ("memory.swap.max", "0"),
        ("memory.oom.group", "1"),
        ("cpu.max", "100000 100000"),
        ("pids.max", str(pids)),
    ):
        (path / limit).write_text(value)
    return path


def run_env(cgroup: Path, engine: str) -> dict[str, str]:
    """What the session piece puts in options.env for a run without a working
    directory."""
    return {
        "CORVO_SANDBOX_CGROUP": str(cgroup),
        "CORVO_SANDBOX_WORKDIR": "",
        "CORVO_SANDBOX_WRITES": "0",
        "CORVO_SANDBOX_ENGINE": engine,
        "CORVO_SANDBOX_TMPFS": str(64 * MIB),
        "ANTHROPIC_API_KEY": PLACEHOLDER,
    }


def probe() -> Any:
    cgroup = run_cgroup("run-gate-probe", 256 * MIB, 64)
    settings = json.dumps({"sandbox": SANDBOX})
    ran = subprocess.run(
        [WRAPPER, "--settings", settings],
        env={**os.environ, **run_env(cgroup, str(HERE / "probe.py"))},
        capture_output=True,
        text=True,
        timeout=60,
    )
    if ran.returncode != 0:
        return {"returncode": ran.returncode, "stderr": ran.stderr[-2000:]}
    return json.loads(ran.stdout)


async def listening(port: int) -> None:
    for _ in range(50):
        try:
            _, writer = await asyncio.open_connection("127.0.0.1", port)
        except OSError:
            await asyncio.sleep(0.1)
            continue
        writer.close()
        return
    raise RuntimeError("the scripted API never listened")


async def session(directory: Path) -> dict[str, Any]:
    """One real engine session whose only call is the Bash COMMAND."""
    script, log = directory / "script.json", directory / "log.jsonl"
    script.write_text(
        json.dumps(
            [
                {"tool_use": [{"name": "Bash", "input": {"command": COMMAND}}]},
                {"text": "{tool_results}"},
            ]
        )
    )
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    api = subprocess.Popen(
        [
            sys.executable,
            str(TESTS / "agents" / "scripted_api.py"),
            "127.0.0.1",
            str(port),
            str(script),
            str(log),
        ]
    )
    stderr: list[str] = []
    options = ClaudeAgentOptions(
        cli_path=WRAPPER,
        tools=["Bash"],
        allowed_tools=["Bash"],
        permission_mode="dontAsk",
        setting_sources=[],
        skills=[],
        strict_mcp_config=True,
        model="claude-haiku-5-5",
        max_turns=3,
        env={
            **run_env(run_cgroup("run-gate-session", 1024 * MIB, 256), ENGINE),
            "ANTHROPIC_BASE_URL": f"http://127.0.0.1:{port}",
        },
        sandbox=SANDBOX,
        stderr=stderr.append,
    )
    started = time.monotonic()
    report: dict[str, Any] = {}
    try:
        await listening(port)
        async with asyncio.timeout(60):
            async for message in query(prompt="run the gate", options=options):
                if isinstance(message, ResultMessage):
                    report |= {
                        "subtype": message.subtype,
                        "is_error": message.is_error,
                        "result": message.result,
                    }
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {str(error)[:500]}"
    finally:
        api.terminate()
        api.wait()
    report["seconds"] = round(time.monotonic() - started, 2)
    report["stderr"] = stderr[-20:]
    report["requests"] = [json.loads(line) for line in log.read_text().splitlines()]
    return report


async def without_cli_path() -> str:
    """What query() raises for options that leave out cli_path."""
    try:
        async for _ in query(prompt="x", options=ClaudeAgentOptions(max_turns=1)):
            pass
    except CLINotFoundError:
        return "CLINotFoundError"
    except Exception as error:
        return f"{type(error).__name__}: {str(error)[:300]}"
    return "no error"


def cgroup_events(path: Path) -> dict[str, int]:
    """A cgroup's memory.events or pids.events, as counts by name."""
    lines = path.read_text().splitlines()
    return {key: int(value) for key, value in (line.split() for line in lines)}


def hog() -> dict[str, Any]:
    cgroup = run_cgroup("run-gate-hog", 64 * MIB, 32)
    worker_cgroup = Path("/proc/self/cgroup").read_text()
    ran = subprocess.run(
        [sys.executable, "-c", HOG, str(cgroup)],
        capture_output=True,
        text=True,
        timeout=60,
    )

    return {
        "returncode": ran.returncode,
        "stdout": ran.stdout.split("\n")[:-1],
        "memory.events": cgroup_events(cgroup / "memory.events"),
        "pids.events": cgroup_events(cgroup / "pids.events"),
        "worker cgroup unchanged": Path("/proc/self/cgroup").read_text()
        == worker_cgroup,
        "worker memory.events": cgroup_events(AGENTS / "worker" / "memory.events"),
    }


def main() -> None:
    os.environ["CORVO_HATCHET_TOKEN"] = WORKER_SECRET
    report: dict[str, Any] = {
        "environment": environment(),
        "netlink": netlink(),
        "outside": outside(),
        "probe": probe(),
    }
    with tempfile.TemporaryDirectory() as directory:
        report["session"] = asyncio.run(session(Path(directory)))
    report["without cli_path"] = asyncio.run(without_cli_path())
    report["hog"] = hog()
    print(json.dumps(report))


if __name__ == "__main__":
    main()
