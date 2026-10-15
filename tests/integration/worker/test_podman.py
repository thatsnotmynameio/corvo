"""The proof that rootless Podman runs the agents' container as KTD6 specifies.

Every agent run leans on it: a container built by the container piece's own
spec, with every capability dropped, a read-only root, size-limited tmpfs
mounts and memory, CPU and process limits, starts, and the limits apply
inside it.

It is also the gate of the request's transport (the agent-request-stdin
plan's U1): through the container piece's own attach, a request written to
the container's stdin arrives whole, and the same socket brings back what
the container writes to its stdout and stderr, each apart and whole.
"""

import hashlib
import json
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import docker
import pytest
from docker import DockerClient
from docker.models.containers import Container

from corvo.agents.frame import MAX_UNTRUSTED_BYTES, encode
from corvo.worker.agent_runtime import containers
from corvo.worker.agent_runtime.containers import (
    DRAIN_TIMEOUT,
    PODMAN_TIMEOUT,
    STDERR,
    STDOUT,
    Attachment,
)
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

# Reads one request from its stdin, framed as its decimal length and a
# newline, after <delay> seconds and under a total <deadline>, then writes
# what <output> names. It exits with how the read ended: 0 whole, 3 at the
# end of input, 4 at the deadline.
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
sys.exit({"whole": 0, "eof": 3, "deadline": 4}[outcome])
"""
EOF, DEADLINE = 3, 4

# What the reader's chatter writes to each stream.
CHATTER_STDOUT = b"o" * 4096 * 256
CHATTER_STDERR = b"e" * 4096 * 256

# The largest request: the 1 MiB the runner accepts, bytes 0 to 255 over.
LARGEST = bytes(range(256)) * (MAX_UNTRUSTED_BYTES // 256)


@pytest.fixture(scope="module")
def image(podman: Podman) -> str:
    podman.client.images.pull(IMAGE)
    return IMAGE


def agent_container(image: str, command: list[str], **labels: str) -> dict[str, Any]:
    """The container piece's spec for a container of the tests' own."""
    return container_spec(
        image=image,
        name=f"corvo-test-{uuid.uuid4().hex[:8]}",
        labels={"corvo.managed": "true", **labels},
        command=command,
    )


def reader(
    image: str, output: str, *, delay: float = 0, deadline: float = 30
) -> dict[str, Any]:
    command = ["python", "-c", READER, str(delay), str(deadline), output]
    return agent_container(image, command)


def report_of(payload: bytes) -> dict[str, Any]:
    """The reader's report of a request it read whole."""
    return {
        "outcome": "whole",
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


@contextmanager
def attached(
    client: DockerClient, spec: dict[str, Any]
) -> Iterator[tuple[Container, Attachment]]:
    """A container created, attached to and started, in that order, as the
    container piece does, and removed on the way out."""
    container = client.containers.create(**spec)
    attachment = Attachment()
    try:
        attachment.open(client, spec["name"])
        container.start()
        yield container, attachment
    finally:
        attachment.close()
        container.remove(force=True)


def streams(
    client: DockerClient, spec: dict[str, Any], request: bytes | None = None
) -> dict[int, bytes]:
    """Every frame's payload, joined by stream, of a container written
    <request> while its output is read. The stream must end on its own
    within DRAIN_TIMEOUT of the container's exit, with exit code 0."""
    with attached(client, spec) as (container, attachment):
        joined = {STDOUT: b"", STDERR: b""}

        def read() -> None:
            for stream, payload in attachment.frames():
                joined[stream] += payload

        reading = threading.Thread(target=read)
        reading.start()
        if request is not None:
            attachment.write(request)
        assert container.wait(timeout=60)["StatusCode"] == 0
        reading.join(DRAIN_TIMEOUT)
        assert not reading.is_alive(), "the stream outlived the container"
    return joined


def reported(client: DockerClient, spec: dict[str, Any], request: bytes) -> Any:
    return json.loads(streams(client, spec, request)[STDOUT])


def test_the_hardened_container_applies_its_limits(podman: Podman, image: str) -> None:
    out = streams(podman.client, agent_container(image, ["python", "-c", PROBE]))

    assert json.loads(out[STDOUT]) == {
        "memory.max": str(AGENT_MEMORY),
        "cpu.max": "100000 100000",
        "pids.max": "256",
        "CapEff": "0000000000000000",
        "root writable": False,
        "tmp writable": True,
    }


def test_positive_label_filters_find_the_deployment(podman: Podman, image: str) -> None:
    container = podman.client.containers.create(
        **agent_container(image, ["true"], **{"corvo.deployment": "x"})
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


def test_kill_and_force_remove_leave_no_container(podman: Podman, image: str) -> None:
    settings = agent_container(image, ["sleep", "300"])
    container = podman.client.containers.run(detach=True, **settings)
    container.kill()
    container.remove(force=True)

    left = podman.client.containers.list(all=True, filters={"name": settings["name"]})
    assert left == []


# The request's direction.


def test_a_request_of_the_largest_size_arrives_whole(
    podman: Podman, image: str
) -> None:
    spec = reader(image, "report")

    assert reported(podman.client, spec, encode(LARGEST)) == report_of(LARGEST)


def test_a_request_past_the_pipe_buffers_waits_for_a_late_reader(
    podman: Podman, image: str
) -> None:
    payload = b"x" * (256 * 1024)
    spec = reader(image, "report", delay=2)

    assert reported(podman.client, spec, encode(payload)) == report_of(payload)


def test_a_late_reader_outlasts_the_clients_own_timeout(
    podman: Podman, image: str
) -> None:
    # The worker's client, whose timeout the attach's socket inherits.
    client = docker.DockerClient(
        base_url=f"unix://{podman.socket}", timeout=PODMAN_TIMEOUT
    )
    payload = b"x" * (512 * 1024)
    spec = reader(image, "report", delay=PODMAN_TIMEOUT + 2)
    try:
        assert reported(client, spec, encode(payload)) == report_of(payload)
    finally:
        client.close()


def test_output_after_the_clients_own_timeout_arrives_without_a_request(
    podman: Podman, image: str
) -> None:
    # As the probe: nothing is written, so no write lifts the timeout.
    client = docker.DockerClient(
        base_url=f"unix://{podman.socket}", timeout=PODMAN_TIMEOUT
    )
    script = f"import time; time.sleep({PODMAN_TIMEOUT + 2}); print('late')"
    try:
        out = streams(client, agent_container(image, ["python", "-c", script]))
    finally:
        client.close()

    assert out == {STDOUT: b"late\n", STDERR: b""}


def test_bytes_written_before_the_read_are_kept(podman: Podman, image: str) -> None:
    payload = b'{"agent": "tone"}'
    spec = reader(image, "report", delay=3)

    assert reported(podman.client, spec, encode(payload)) == report_of(payload)


def test_a_request_holding_ctrl_p_ctrl_q_arrives_whole(
    podman: Podman, image: str
) -> None:
    payload = b"a" * 100 + b"\x10\x11" + b"b" * 100
    spec = reader(image, "report", deadline=5)

    assert reported(podman.client, spec, encode(payload)) == report_of(payload)


def test_a_container_that_never_reads_times_the_write_out(
    podman: Podman, image: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers, "REQUEST_WRITE_TIMEOUT", 3)
    spec = agent_container(image, ["sleep", "300"])
    with attached(podman.client, spec) as (_, attachment):
        started = time.monotonic()
        with pytest.raises(TimeoutError):
            attachment.write(encode(LARGEST))
        assert time.monotonic() - started < 10
    left = podman.client.containers.list(all=True, filters={"name": spec["name"]})
    assert left == []


def test_a_dropped_connection_ends_the_read_within_its_deadline(
    podman: Podman, image: str
) -> None:
    spec = reader(image, "report", deadline=10)
    with attached(podman.client, spec) as (container, attachment):
        attachment.write(b"%d\n" % MAX_UNTRUSTED_BYTES + b"x" * (100 * 1024))
        attachment.close()
        started = time.monotonic()
        exit_code = container.wait(timeout=60)["StatusCode"]
        assert time.monotonic() - started < 15
    assert exit_code in (EOF, DEADLINE)


# The result's direction.


def test_a_result_written_just_before_exit_arrives_whole(
    podman: Podman, image: str
) -> None:
    out = streams(podman.client, reader(image, "blob"), encode(b"{}"))

    assert out == {STDOUT: encode(bytes(range(256)) * 4096), STDERR: b""}


def test_a_line_past_conmons_buffer_arrives_unsplit(podman: Podman, image: str) -> None:
    out = streams(podman.client, reader(image, "line"), encode(b"{}"))

    assert out == {STDOUT: b"a" * 20000 + b"\n", STDERR: b""}


def test_stdout_and_stderr_arrive_apart(podman: Podman, image: str) -> None:
    out = streams(podman.client, reader(image, "interleaved"), encode(b"{}"))

    assert out == {STDOUT: CHATTER_STDOUT, STDERR: CHATTER_STDERR}


def test_a_request_and_a_result_cross_on_one_connection(
    podman: Podman, image: str
) -> None:
    out = streams(podman.client, reader(image, "chatter"), encode(LARGEST))

    report = encode(json.dumps(report_of(LARGEST)).encode())
    assert out == {STDOUT: CHATTER_STDOUT + report, STDERR: CHATTER_STDERR}
