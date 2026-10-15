"""The isolation gate's driver: runs inside the agent worker's image, as the
worker would, and prints what it found as one JSON report (U1).

It makes run cgroups under the subtree the entrypoint delegated, runs a probe
in the engine's place through corvo-agent-sandbox, runs one real engine
session against the scripted API, and runs a fork and memory hog in a run's
cgroup. test_isolation_gate.py asserts on the report.
"""

import asyncio
import ctypes
import errno
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    ClaudeAgentOptions,
    CLINotFoundError,
    ResultMessage,
    query,
)

from corvo.agents.session import sandbox_settings
from corvo.worker.agent_runtime.cgroups import read_keyed
from corvo.worker.agent_runtime.sandbox import PLACEHOLDER

HERE = Path(__file__).parent
TESTS = HERE.parents[2]
AGENTS = Path("/sys/fs/cgroup/agents")
WRAPPER = str(Path(sys.executable).parent / "corvo-agent-sandbox")
ENGINE = os.environ["CORVO_AGENT_ENGINE"]
MIB = 1024**2

# A secret the worker holds, which nothing in the sandbox may see.
WORKER_SECRET = "gate-hatchet-token"

# Every session's own sandbox settings, so the gate proves what agents run.
SANDBOX = sandbox_settings()

# The session's one Bash call: a marker, then the network interfaces the
# command sees, which only the SDK's own sandbox narrows to loopback.
COMMAND = "echo corvo-gate $(tail -n +3 /proc/net/dev | cut -d: -f1 | tr -d ' ')"

SYS_SOCKET_X86_64 = 41
SOCK_RAW = 3
NETLINK_NETFILTER = 12

# socketcall(SYS_SOCKET, [AF_NETLINK, SOCK_RAW, NETLINK_NETFILTER]) through
# int 0x80, the 32-bit x86 entry, from code and arguments mapped below 4 GiB.
# It prints the fd or the errno; the filter may also kill it.
SOCKETCALL = """
import ctypes, errno, mmap, struct
page = mmap.mmap(-1, 4096, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS | 0x40,
                 prot=mmap.PROT_READ | mmap.PROT_WRITE | mmap.PROT_EXEC)
base = ctypes.addressof(ctypes.c_char.from_buffer(page))
assert base < 2**32
arguments = base + 64
code = (b"\\x53" + b"\\xb8" + struct.pack("<I", 102) + b"\\xbb" + struct.pack("<I", 1)
        + b"\\xb9" + struct.pack("<I", arguments) + b"\\xcd\\x80" + b"\\x5b\\xc3")
page[0:len(code)] = code
page[64:76] = struct.pack("<3I", 16, 3, 12)
result = ctypes.CFUNCTYPE(ctypes.c_int)(base)()
print("opened" if result >= 0 else errno.errorcode.get(-result, str(-result)))
"""

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
    status = dict(
        line.split(":\t", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
    )
    setuid = subprocess.run(
        ["find", "/", "-xdev", "-type", "f", "-perm", "/6000"],
        capture_output=True,
        text=True,
    )
    return {
        "uid": os.getuid(),
        "privileges": {
            name: status[name].strip()
            for name in ("NoNewPrivs", "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb")
        },
        "setuid files": setuid.stdout.split(),
        "kernel": os.uname().release,
        "bubblewrap": version.stdout.strip(),
        "cgroup": Path("/proc/self/cgroup").read_text().strip(),
        "cgroup2 options": mount[2].split(",") if mount[0] == "cgroup2" else mount,
    }


def raw_socket(family: int, protocol: int) -> str:
    """socket() as a raw syscall, so its 64-bit arguments reach the filter as
    given: a command can set bits the kernel's 32-bit ints then drop."""
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    args = (ctypes.c_long(family), ctypes.c_long(SOCK_RAW), ctypes.c_long(protocol))
    fd = libc.syscall(SYS_SOCKET_X86_64, *args)
    if fd >= 0:
        os.close(fd)
        return "opened"
    return errno.errorcode.get(ctypes.get_errno(), str(ctypes.get_errno()))


def socketcall() -> str:
    """A netfilter socket through 32-bit x86's socketcall, in a process of its
    own, since the filter may kill it."""
    ran = subprocess.run(
        [sys.executable, "-c", SOCKETCALL], capture_output=True, text=True, timeout=30
    )
    if ran.returncode < 0:
        return f"killed by signal {-ran.returncode}"
    return ran.stdout.strip() or f"exit {ran.returncode}: {ran.stderr[-300:]}"


def netlink() -> dict[str, str]:
    """Whether the container's seccomp profile lets each netlink socket open."""
    results = {}
    for name, protocol in (("route", 0), ("netfilter", NETLINK_NETFILTER)):
        try:
            socket.socket(socket.AF_NETLINK, socket.SOCK_RAW, protocol).close()
            results[name] = "opened"
        except OSError as error:
            results[name] = errno.errorcode.get(error.errno or 0, str(error.errno))
    high = 1 << 32
    results["netfilter, protocol's high bits"] = raw_socket(
        socket.AF_NETLINK, high | NETLINK_NETFILTER
    )
    results["netfilter, family's high bits"] = raw_socket(
        high | socket.AF_NETLINK, NETLINK_NETFILTER
    )
    results["netfilter, 32-bit socketcall"] = socketcall()
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


def pids_peak(cgroup: Path) -> int:
    """How many processes the cgroup ever held: none unless the wrapper
    joined it."""
    return int((cgroup / "pids.peak").read_text())


def probe() -> Any:
    """The probe in the engine's place, in a read-only working directory of
    its own, as a run with one gets."""
    cgroup = run_cgroup("run-gate-probe", 256 * MIB, 64)
    workdir = tempfile.mkdtemp(prefix="corvo-gate-", dir="/var/tmp")
    settings = json.dumps({"sandbox": SANDBOX})
    ran = subprocess.run(
        [WRAPPER, "--setting-sources=", "--settings", settings],
        env={
            **os.environ,
            **run_env(cgroup, str(HERE / "probe.py")),
            "CORVO_SANDBOX_WORKDIR": workdir,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    if ran.returncode != 0:
        return {"returncode": ran.returncode, "stderr": ran.stderr[-2000:]}
    return json.loads(ran.stdout) | {"workdir": workdir, "pids.peak": pids_peak(cgroup)}


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
    cgroup = run_cgroup("run-gate-session", 1024 * MIB, 256)
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
            **run_env(cgroup, ENGINE),
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
    report["pids.peak"] = pids_peak(cgroup)
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
        "memory.events": read_keyed(cgroup / "memory.events"),
        "pids.events": read_keyed(cgroup / "pids.events"),
        "worker cgroup unchanged": Path("/proc/self/cgroup").read_text()
        == worker_cgroup,
        "worker memory.events": read_keyed(AGENTS / "worker" / "memory.events"),
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
