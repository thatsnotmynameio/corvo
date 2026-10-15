#!/usr/local/bin/python3
"""Run by corvo-agent-sandbox in the engine's place: what a session's engine
sees inside its bubblewrap, printed as JSON. It reads every process's
environment, so it reports variable names only."""

import json
import os
from pathlib import Path


def environ_names(pid: Path) -> list[str] | str:
    try:
        raw = (pid / "environ").read_bytes()
    except OSError as error:
        return f"unreadable: {error.strerror}"
    return sorted(
        entry.split(b"=", 1)[0].decode() for entry in raw.split(b"\0") if entry
    )


def main() -> None:
    pids = sorted(
        (path for path in Path("/proc").iterdir() if path.name.isdigit()),
        key=lambda path: int(path.name),
    )
    print(
        json.dumps(
            {
                "uid": os.getuid(),
                "cwd": os.getcwd(),
                "cwd writable": os.access(".", os.W_OK),
                "processes": {
                    path.name: (path / "cmdline").read_bytes().split(b"\0")[0].decode()
                    for path in pids
                },
                "environ": {path.name: environ_names(path) for path in pids},
                "sys": os.path.exists("/sys"),
                "interfaces": sorted(
                    line.split(":")[0].strip()
                    for line in Path("/proc/net/dev").read_text().splitlines()[2:]
                ),
                "cgroup": Path("/proc/self/cgroup").read_text().strip(),
            }
        )
    )


if __name__ == "__main__":
    main()
