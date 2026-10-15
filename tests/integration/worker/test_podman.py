"""The proof that rootless Podman runs the agents' container as KTD6 specifies.

Every agent run leans on it: a container built by the container piece's own
spec, with every capability dropped, a read-only root, size-limited tmpfs
mounts and memory, CPU and process limits, starts, and the limits apply
inside it.

It is also the gate of the request's transport (the agent-request-stdin
plan's U1): a request written to the container's standard input, through
docker-py's attach socket, arrives whole, and the same socket brings back
what the container writes to its stdout and stderr.
"""

import hashlib
import json
import socket
import struct
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from docker.models.containers import Container
from docker.types import LogConfig

from corvo.worker.agent_runtime.spec import MANAGED, container_spec
from corvo.worker.defaults import AGENT_MEMORY

from .conftest import Podman

# The Python the app's image is built on, named in full: Podman resolves no
# short name without a registries.conf that allows it.
IMAGE = "docker.io/library/python:3.14.7-slim"

# What the agents' container reports from inside it: its cgroup's limits, its
# effective capabilities, and whether the root and /tmp take a write.
PROBE = """
import json

def read(path):
    with open(path) as f:
        return f.read().strip()

def writable(path):
    try:
        with open(path, "w"):
            pass
    except OSError:
        return False
    return True

status = dict(line.split(":", 1) for line in read("/proc/self/status").splitlines())
print(json.dumps({
    "memory.max": read("/sys/fs/cgroup/memory.max"),
    "cpu.max": read("/sys/fs/cgroup/cpu.max"),
    "pids.max": read("/sys/fs/cgroup/pids.max"),
    "CapEff": status["CapEff"].strip(),
    "root writable": writable("/probe"),
    "tmp writable": writable("/tmp/probe"),
}))
"""


@pytest.fixture(scope="module")
def image(podman: Podman) -> str:
    podman.client.images.pull(IMAGE)
    return IMAGE


@pytest.fixture
def run_dir(podman: Podman) -> Iterator[Path]:
    path = podman.root / f"test-{uuid.uuid4().hex[:8]}"
    path.mkdir()
    yield path
    path.rmdir()


def agent_container(
    image: str, command: list[str], run_dir: Path, **labels: str
) -> dict[str, Any]:
    """The container piece's spec for a container of the tests' own."""
    return container_spec(
        image=image,
        name=f"corvo-test-{uuid.uuid4().hex[:8]}",
        labels={"corvo.managed": "true", **labels},
        command=command,
        run_dir=run_dir,
    )


def test_the_hardened_container_applies_its_limits(
    podman: Podman, image: str, run_dir: Path
) -> None:
    container = podman.client.containers.run(
        detach=True, **agent_container(image, ["python", "-c", PROBE], run_dir)
    )
    try:
        assert container.wait(timeout=60)["StatusCode"] == 0
        report = json.loads(container.logs(stderr=False))
    finally:
        container.remove(force=True)

    assert report == {
        "memory.max": str(AGENT_MEMORY),
        "cpu.max": "100000 100000",
        "pids.max": "256",
        "CapEff": "0000000000000000",
        "root writable": False,
        "tmp writable": True,
    }


def test_positive_label_filters_find_the_deployment(
    podman: Podman, image: str, run_dir: Path
) -> None:
    container = podman.client.containers.create(
        **agent_container(image, ["true"], run_dir, **{"corvo.deployment": "x"})
    )

    def listed(deployment: str) -> list[str | None]:
        filters: dict[str, str | list[str] | bool] = {
            "label": [MANAGED, f"corvo.deployment={deployment}"]
        }
        return [c.id for c in podman.client.containers.list(all=True, filters=filters)]

    try:
        assert container.id in listed("x")
        assert container.id not in listed("y")
    finally:
        container.remove(force=True)


def test_kill_and_force_remove_leave_no_container(
    podman: Podman, image: str, run_dir: Path
) -> None:
    settings = agent_container(image, ["sleep", "300"], run_dir)
    container = podman.client.containers.run(detach=True, **settings)
    container.kill()
    container.remove(force=True)

    left = podman.client.containers.list(all=True, filters={"name": settings["name"]})
    assert left == []


# The largest request the runner accepts, which is the envelope's cap.
MAX_REQUEST = 1024 * 1024

# Reads one request from its stdin, framed as its decimal length and a
# newline, after <delay> seconds and under a total <deadline>, then writes
# what <output> names. Its report says how the read ended: whole, at the
# end of input, or at the deadline.
READER = r"""
import hashlib, json, os, select, sys, threading, time

delay, deadline, output = float(sys.argv[1]), float(sys.argv[2]), sys.argv[3]

def write(fd, data):
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]

def chatter():
    for _ in range(256):
        write(1, b"o" * 4096)
        write(2, b"e" * 4096)

def read_request():
    end = time.monotonic() + deadline
    data, expected = b"", None
    while True:
        if expected is None and b"\n" in data:
            header, _, data = data.partition(b"\n")
            expected = int(header)
        if expected is not None and len(data) >= expected:
            return "whole", data[:expected]
        left = end - time.monotonic()
        if left <= 0 or not select.select([0], [], [], left)[0]:
            return "deadline", data
        chunk = os.read(0, 65536)
        if not chunk:
            return "eof", data
        data += chunk

chatting = threading.Thread(target=chatter)
if output == "chatter":
    chatting.start()
time.sleep(delay)
outcome, body = read_request()
report = json.dumps({
    "outcome": outcome,
    "length": len(body),
    "sha256": hashlib.sha256(body).hexdigest(),
}).encode()
if output == "report":
    write(1, report + b"\n")
elif output == "blob":
    blob = bytes(range(256)) * 4096
    write(1, b"%d\n" % len(blob) + blob)
elif output == "line":
    write(1, b"a" * 20000 + b"\n")
elif output == "interleaved":
    chatting.start()
    chatting.join()
elif output == "chatter":
    chatting.join()
    write(1, b"%d\n" % len(report) + report)
"""

# What the reader's chatter writes to each stream.
CHATTER_STDOUT = b"o" * 4096 * 256
CHATTER_STDERR = b"e" * 4096 * 256

# The bounds the transport is held to: the worker's write, and the time the
# attach stream may take to end once the container has exited.
WRITE_TIMEOUT = 45
DRAIN_TIMEOUT = 5

# The attach stream's frame header: the stream, three zero bytes and the
# payload's length (docker-py's utils/socket.py).
FRAME_HEADER = struct.Struct(">BxxxL")
STDOUT, STDERR = 1, 2


def framed(payload: bytes) -> bytes:
    return b"%d\n" % len(payload) + payload


def report_of(payload: bytes) -> dict[str, Any]:
    """The reader's report of a request it read whole."""
    return {
        "outcome": "whole",
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def reader_container(
    image: str,
    run_dir: Path,
    output: str,
    *,
    delay: float = 0,
    deadline: float = 30,
    **settings: Any,
) -> dict[str, Any]:
    """The reader in an agent container whose stdin is open, with no tty."""
    command = ["python", "-c", READER, str(delay), str(deadline), output]
    spec = agent_container(image, command, run_dir)
    return {**spec, "stdin_open": True, "tty": False, **settings}


@dataclass
class Attached:
    container: Container
    # The connection's socket, and the HTTP response docker-py read the
    # attach's answer through, which holds the socket open until it is
    # closed too.
    sock: socket.socket
    response: Any

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.response.close()
        self.sock.close()


@contextmanager
def attached(
    podman: Podman,
    spec: dict[str, Any],
    *,
    output: bool,
) -> Iterator[Attached]:
    """A container created, attached to and started, in that order, and
    removed on the way out. The attach takes stdin, and stdout and stderr
    when <output> holds. Its detach keys are none, where docker-py would
    otherwise send those of ~/.docker/config.json."""
    container = podman.client.containers.create(**spec)
    try:
        params: dict[str, Any] = {"stdin": 1, "stream": 1, "detachKeys": ""}
        if output:
            params |= {"stdout": 1, "stderr": 1}
        stream = podman.client.api.attach_socket(spec["name"], params=params)
        connection = Attached(container, stream._sock, stream._response)
        try:
            container.start()
            yield connection
        finally:
            connection.close()
    finally:
        container.remove(force=True)


def send(connection: Attached, data: bytes, timeout: float = WRITE_TIMEOUT) -> None:
    connection.sock.settimeout(timeout)
    connection.sock.sendall(data)


def received(sock: socket.socket, size: int) -> bytes | None:
    """Exactly <size> bytes, or None when the stream ends first."""
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def streams(sock: socket.socket) -> dict[int, bytes]:
    """Every frame's payload until the stream ends, joined by stream."""
    joined = {STDOUT: b"", STDERR: b""}
    while (header := received(sock, FRAME_HEADER.size)) is not None:
        kind, size = FRAME_HEADER.unpack(header)
        payload = received(sock, size)
        if payload is None:
            break
        joined[kind] += payload
    return joined


def logged_report(container: Container) -> dict[str, Any]:
    assert container.wait(timeout=60)["StatusCode"] == 0
    report: dict[str, Any] = json.loads(container.logs(stdout=True, stderr=False))
    return report


def run_attached(
    podman: Podman, spec: dict[str, Any], request: bytes
) -> dict[int, bytes]:
    """The streams of a container attached to with stdin, stdout and stderr,
    written <request> while they are read. The stream must end within
    DRAIN_TIMEOUT of the container's exit."""
    with attached(podman, spec, output=True) as connection:
        connection.sock.settimeout(WRITE_TIMEOUT)
        result: dict[int, bytes] = {}
        reader = threading.Thread(
            target=lambda: result.update(streams(connection.sock))
        )
        reader.start()
        connection.sock.sendall(request)
        assert connection.container.wait(timeout=60)["StatusCode"] == 0
        reader.join(DRAIN_TIMEOUT)
        assert not reader.is_alive(), "the stream outlived the container"
    return result


# The request's direction.


def test_a_request_of_the_largest_size_arrives_whole(
    podman: Podman, image: str, run_dir: Path
) -> None:
    payload = bytes(range(256)) * (MAX_REQUEST // 256)
    spec = reader_container(image, run_dir, "report")
    with attached(podman, spec, output=False) as connection:
        send(connection, framed(payload))
        assert logged_report(connection.container) == report_of(payload)


def test_a_request_past_the_pipe_buffers_waits_for_a_late_reader(
    podman: Podman, image: str, run_dir: Path
) -> None:
    payload = b"x" * (256 * 1024)
    spec = reader_container(image, run_dir, "report", delay=2)
    with attached(podman, spec, output=False) as connection:
        send(connection, framed(payload))
        assert logged_report(connection.container) == report_of(payload)


def test_bytes_written_before_the_read_are_kept(
    podman: Podman, image: str, run_dir: Path
) -> None:
    payload = b'{"agent": "tone"}'
    spec = reader_container(image, run_dir, "report", delay=3)
    with attached(podman, spec, output=False) as connection:
        send(connection, framed(payload))
        assert logged_report(connection.container) == report_of(payload)


def test_a_request_holding_ctrl_p_ctrl_q_arrives_whole(
    podman: Podman, image: str, run_dir: Path
) -> None:
    payload = b"a" * 100 + b"\x10\x11" + b"b" * 100
    spec = reader_container(image, run_dir, "report", deadline=5)
    with attached(podman, spec, output=False) as connection:
        send(connection, framed(payload))
        assert logged_report(connection.container) == report_of(payload)


def test_a_container_that_never_reads_times_the_write_out(
    podman: Podman, image: str, run_dir: Path
) -> None:
    spec = {**agent_container(image, ["sleep", "300"], run_dir), "stdin_open": True}
    with attached(podman, spec, output=False) as connection:
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            send(connection, framed(b"x" * MAX_REQUEST), timeout=3)
        assert time.monotonic() - started < 10
    left = podman.client.containers.list(all=True, filters={"name": spec["name"]})
    assert left == []


def test_a_dropped_connection_ends_the_read_within_its_deadline(
    podman: Podman, image: str, run_dir: Path
) -> None:
    spec = reader_container(image, run_dir, "report", deadline=10)
    with attached(podman, spec, output=False) as connection:
        send(connection, b"%d\n" % MAX_REQUEST + b"x" * (100 * 1024))
        connection.close()
        started = time.monotonic()
        report = logged_report(connection.container)
        assert time.monotonic() - started < 15
    assert report["outcome"] in {"eof", "deadline"}
    assert report["length"] < MAX_REQUEST


# The result's direction.


def test_a_result_written_just_before_exit_arrives_whole(
    podman: Podman, image: str, run_dir: Path
) -> None:
    spec = reader_container(image, run_dir, "blob")
    out = run_attached(podman, spec, framed(b"{}"))
    assert out == {STDOUT: framed(bytes(range(256)) * 4096), STDERR: b""}


def test_a_line_past_conmons_buffer_arrives_unsplit(
    podman: Podman, image: str, run_dir: Path
) -> None:
    spec = reader_container(image, run_dir, "line")
    out = run_attached(podman, spec, framed(b"{}"))
    assert out == {STDOUT: b"a" * 20000 + b"\n", STDERR: b""}


@pytest.mark.parametrize("log_driver", [None, "none"])
def test_stdout_and_stderr_arrive_apart(
    podman: Podman, image: str, run_dir: Path, log_driver: str | None
) -> None:
    settings: dict[str, Any] = (
        {} if log_driver is None else {"log_config": LogConfig(type=log_driver)}
    )
    spec = reader_container(image, run_dir, "interleaved", **settings)
    out = run_attached(podman, spec, framed(b"{}"))
    assert out == {STDOUT: CHATTER_STDOUT, STDERR: CHATTER_STDERR}


def test_a_request_and_a_result_cross_on_one_connection(
    podman: Podman, image: str, run_dir: Path
) -> None:
    payload = bytes(range(256)) * (MAX_REQUEST // 256)
    spec = reader_container(
        image, run_dir, "chatter", log_config=LogConfig(type="none")
    )
    out = run_attached(podman, spec, framed(payload))
    report = json.dumps(report_of(payload)).encode()
    assert out == {STDOUT: CHATTER_STDOUT + framed(report), STDERR: CHATTER_STDERR}
