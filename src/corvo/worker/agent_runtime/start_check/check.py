#!/usr/local/bin/python3
"""Run by corvo-agent-sandbox in the engine's place when the agent worker
starts (KTD10): what a session's sandbox shows, printed as one JSON line.

It reports the processes /proc lists and the names of the variables each
holds, never their values; whether /sys and each path given after --absent
exist; whether a nested bubblewrap with its own user and network namespaces
starts, as the SDK's sandbox starts one for each command; and where socat
is, which the SDK's sandbox needs too. corvo.worker.agent_runtime.startup
judges the report.

The sandbox holds no corvo package, so it imports only the standard library.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# A command in user and network namespaces of its own, as the SDK's sandbox
# runs each one, with only the system files it needs.
NESTED = [
    "bwrap",
    "--unshare-user",
    "--unshare-net",
    "--die-with-parent",
    "--ro-bind",
    "/usr",
    "/usr",
    "--symlink",
    "usr/bin",
    "/bin",
    "--symlink",
    "usr/lib",
    "/lib",
    "--symlink",
    "usr/lib64",
    "/lib64",
    "/usr/bin/true",
]
NESTED_TIMEOUT = 10


def environ_names(pid: Path) -> list[str] | str:
    try:
        raw = (pid / "environ").read_bytes()
    except OSError as error:
        return f"unreadable: {error.strerror}"
    return sorted(
        entry.split(b"=", 1)[0].decode() for entry in raw.split(b"\0") if entry
    )


def command(pid: Path) -> str:
    try:
        return (pid / "cmdline").read_bytes().split(b"\0")[0].decode()
    except OSError as error:
        return f"unreadable: {error.strerror}"


def nested() -> dict[str, Any]:
    try:
        ran = subprocess.run(
            NESTED, capture_output=True, text=True, timeout=NESTED_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"returncode": None, "stderr": f"{type(error).__name__}: {error}"}
    return {"returncode": ran.returncode, "stderr": ran.stderr[-500:]}


def report(argv: list[str]) -> dict[str, Any]:
    absent = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--absent"]
    pids = sorted(
        (path for path in Path("/proc").iterdir() if path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    # The processes first, before the nested bubblewrap adds its own.
    processes = {path.name: command(path) for path in pids}
    environ = {path.name: environ_names(path) for path in pids}
    return {
        "self": str(os.getpid()),
        "processes": processes,
        "environ": environ,
        "sys": os.path.lexists("/sys"),
        "present": [path for path in absent if os.path.lexists(path)],
        "nested": nested(),
        "socat": shutil.which("socat"),
    }


def main() -> None:
    print(json.dumps(report(sys.argv[1:])))


if __name__ == "__main__":
    main()
