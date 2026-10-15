"""corvo-agent, the entrypoint of every agent container.

`corvo-agent run` reads the AgentRequest the worker framed on its stdin,
under REQUEST_READ_TIMEOUT, then points stdin at /dev/null. It imports
corvo.agents.<agent>.agent, validates the input with the model run's input
parameter declares, and awaits run under the session budget. It then
writes the envelope, framed, to its stdout. Every failure it can name
becomes a failed envelope; a crash leaves none, which the worker reports
with the container's exit code.

`corvo-agent probe` frames what it reads inside its container on its
stdout, for the worker's startup check (KTD10).

Only the frame reaches the real stdout: main first moves it to a private
descriptor, which no child inherits, and points fd 1 at stderr, so nothing
the CLI, a tool or a library prints can corrupt or forge the frame.

The entrypoint sits outside the agent: the agent calls its SDK itself.
"""

import argparse
import asyncio
import os
import socket
import struct
import sys
from importlib import import_module
from pathlib import Path
from typing import BinaryIO, get_type_hints

from pydantic import BaseModel, ValidationError

from corvo.agents.envelope import (
    AgentRequest,
    AgentRunFailed,
    Failed,
    ProbeReport,
    RunReport,
    Succeeded,
)
from corvo.agents.fingerprint import fingerprint
from corvo.agents.frame import FrameError, encode, read_frame

# How long the request may take to arrive: below the worker's own bound on
# its write, so a run that reports an invalid request is not cut off.
REQUEST_READ_TIMEOUT = 30

# The cloud metadata address, which the production nftables rule blocks.
METADATA_ADDRESS = "169.254.169.254"
PROBE_PORT = 80


def send(out: BinaryIO, model: BaseModel) -> None:
    out.write(encode(model.model_dump_json().encode()))
    out.flush()


def read_request(fd: int = 0) -> bytes | None:
    """The request framed on <fd>, or None when it does not arrive whole.
    Then <fd> points at /dev/null, so neither the CLI nor a tool can read
    late bytes or hold the channel."""
    try:
        return read_frame(fd, REQUEST_READ_TIMEOUT)
    except FrameError as error:
        # The reason names sizes at most, never the request.
        print(f"corvo-agent: invalid request: {error}", file=sys.stderr)
        return None
    finally:
        null = os.open(os.devnull, os.O_RDONLY)
        os.dup2(null, fd)
        os.close(null)


async def outcome(raw: bytes | None) -> Succeeded | Failed:
    if raw is None:
        return Failed(reason="invalid_request", report=RunReport())
    try:
        request = AgentRequest.model_validate_json(raw)
    except ValidationError:
        return Failed(reason="invalid_request", report=RunReport())

    package = f"corvo.agents.{request.agent}"
    try:
        agent = import_module(f"{package}.agent")
    except ModuleNotFoundError as error:
        # Only the agent's own absence: a missing import inside it is a bug.
        if error.name not in (package, f"{package}.agent"):
            raise
        return Failed(reason="unknown_agent", report=RunReport())

    input_model: type[BaseModel] = get_type_hints(agent.run)["input"]
    try:
        agent_input = input_model.model_validate(request.input)
    except ValidationError:
        return Failed(reason="invalid_input", report=RunReport())

    try:
        async with asyncio.timeout(request.budget_seconds) as budget:
            output, report = await agent.run(agent_input, None)
    except TimeoutError:
        # Only the budget's own timeout: another is the agent's failure.
        if not budget.expired():
            raise
        return Failed(reason="deadline", report=RunReport())
    except AgentRunFailed as failure:
        return Failed(reason=failure.reason, report=failure.report)
    return Succeeded(output=output.model_dump(mode="json"), report=report)


async def execute(raw: bytes | None, out: BinaryIO) -> bool:
    """Run the requested agent and frame its envelope on out: True when it
    is ok."""
    envelope = await outcome(raw)
    send(out, envelope)
    return isinstance(envelope, Succeeded)


def mount_options(mounts: Path) -> dict[str, list[str]]:
    """Each mount point's options; a later mount over a point wins."""
    options = {}
    for line in mounts.read_text().splitlines():
        _, point, _, flags, *_ = line.split()
        options[point] = flags.split(",")
    return options


def default_gateway(route: Path) -> str | None:
    for line in route.read_text().splitlines()[1:]:
        fields = line.split()
        if fields[1] == "00000000":
            # The kernel writes the address in host byte order.
            return socket.inet_ntoa(struct.pack("<L", int(fields[2], 16)))
    return None


def reaches(address: str) -> bool:
    try:
        with socket.create_connection((address, PROBE_PORT), timeout=1):
            return True
    except ConnectionRefusedError:
        # A refusal came back from the address, so it was reached.
        return True
    except OSError:
        return False


def probe(root: Path = Path("/")) -> ProbeReport:
    cgroup = root / "sys" / "fs" / "cgroup"
    status = dict(
        line.split(":\t", 1)
        for line in (root / "proc" / "self" / "status").read_text().splitlines()
    )
    mounts = mount_options(root / "proc" / "self" / "mounts")
    gateway = default_gateway(root / "proc" / "net" / "route")
    return ProbeReport(
        fingerprint=fingerprint(),
        memory_max=(cgroup / "memory.max").read_text().strip(),
        cpu_max=(cgroup / "cpu.max").read_text().strip(),
        pids_max=(cgroup / "pids.max").read_text().strip(),
        cap_eff=status["CapEff"].strip(),
        env_names=sorted(os.environ),
        root_read_only="ro" in mounts["/"],
        mounts={point: mounts.get(point, []) for point in ("/tmp", "/home/agent")},
        gateway=gateway,
        gateway_reachable=None if gateway is None else reaches(gateway),
        metadata_reachable=reaches(METADATA_ADDRESS),
    )


def main() -> int:
    # The real stdout, for the frame alone; fd 1 now writes to stderr.
    out = os.fdopen(os.dup(1), "wb")
    os.dup2(2, 1)
    parser = argparse.ArgumentParser(prog="corvo-agent")
    parser.add_argument("command", choices=["run", "probe"])
    command = parser.parse_args().command
    if command == "probe":
        send(out, probe())
        return 0
    return 0 if asyncio.run(execute(read_request(), out)) else 1
