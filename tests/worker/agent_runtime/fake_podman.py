"""A stand-in for docker-py's client over Podman, for the container piece's
unit tests.

A container it creates does nothing until attached to and started. Its
attach is one end of a socket pair, which the container serves as Podman's
attach stream does: once started, it reads the framed request, hands it to
its behaviour, and sends what the behaviour says the container printed, in
the stream's 8-byte frames, then says how it exited. A container whose
behaviour hangs runs until it is removed, as a session past its deadline
would, and removing a container ends its stream.
"""

import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import requests
from docker.errors import APIError, ImageNotFound, NotFound

from corvo.agents.frame import FrameError, read_frame

# What the container piece attaches with.
ATTACH = {"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1, "detachKeys": ""}

STDOUT, STDERR = 1, 2
FRAME_HEADER = struct.Struct(">BxxxL")


@dataclass
class Exit:
    # What the container prints, each chunk sent as one frame, stderr's and
    # stdout's in turn.
    stdout: list[bytes] = field(default_factory=list)
    stderr: list[bytes] = field(default_factory=list)
    code: int = 0
    oom_killed: bool = False
    hangs: bool = False
    # Each byte sent on its own, so frame headers split across reads.
    trickles: bool = False
    # The stream stays open after the container exits.
    outlives: bool = False


type Behaviour = Callable[[bytes], Exit]

# What a container does with its stdin: read the request, never read it,
# or exit before reading it.
type Reading = Literal["reads", "never", "exits"]


def exits(request: bytes) -> Exit:
    return Exit()


def framed(stream: int, payload: bytes) -> bytes:
    return FRAME_HEADER.pack(stream, len(payload)) + payload


class FakeStream:
    """What docker-py's attach_socket returns: a stream over the socket,
    which keeps the HTTP response it read the attach's answer through."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._response = FakeResponse()


class FakeResponse:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeContainer:
    def __init__(self, client: FakeClient, spec: dict[str, Any]) -> None:
        self.client = client
        self.spec = spec
        self.name: str = spec["name"]
        self.labels: dict[str, str] = spec["labels"]
        self.started = False
        self.removed = threading.Event()
        self.exited = threading.Event()
        # Set once the container exits, or is removed first.
        self.finished = threading.Event()
        self.exit = Exit()
        # The container's end of its attach.
        self.peer: socket.socket | None = None
        # A removal that fails with this status code, once.
        self.remove_fails_with: int | None = None
        # Seconds a removal takes, as a slow Podman's would.
        self.remove_takes = 0.0
        self.attrs: dict[str, Any] = {"State": {"OOMKilled": False}}

    def attach(self) -> socket.socket:
        assert self.spec["stdin_open"] and not self.spec["tty"]
        mine, self.peer = socket.socketpair()
        return mine

    def start(self) -> None:
        self.client.events.append("start")
        self.started = True
        threading.Thread(target=self.serve, daemon=True).start()

    def serve(self) -> None:
        peer = self.peer
        assert peer is not None, "started before an attach"
        try:
            self.run(peer)
        except OSError:
            # The worker closed its end.
            pass
        if self.exit.hangs or self.client.reading == "never":
            self.removed.wait()
        else:
            self.exited.set()
            self.finished.set()
        if not self.exit.outlives:
            close(peer)

    def run(self, peer: socket.socket) -> None:
        if self.client.reading == "exits":
            self.exit = Exit(code=1)
            return
        if self.client.reading == "never":
            return
        request = b""
        # corvo-agent probe reads no request.
        if self.spec["command"] == ["run"]:
            try:
                request = read_frame(peer.fileno(), 10)
            except FrameError:
                pass
            self.client.requests.append(request)
        self.exit = self.client.behaviour(request)
        self.attrs = {"State": {"OOMKilled": self.exit.oom_killed}}
        streams = ((STDERR, self.exit.stderr), (STDOUT, self.exit.stdout))
        for index in range(max(len(self.exit.stderr), len(self.exit.stdout))):
            for stream, chunks in streams:
                if index < len(chunks):
                    self.send(peer, framed(stream, chunks[index]))

    def send(self, peer: socket.socket, data: bytes) -> None:
        if not self.exit.trickles:
            peer.sendall(data)
            return
        for byte in data:
            peer.sendall(bytes([byte]))
            time.sleep(0.001)

    def wait(self) -> dict[str, int]:
        self.finished.wait()
        if not self.exited.is_set():
            raise NotFound("no such container")
        return {"StatusCode": self.exit.code}

    def reload(self) -> None:
        if self.removed.is_set():
            raise NotFound("no such container")

    def remove(self, force: bool = False) -> None:
        assert force
        self.client.removals.append(self.name)
        time.sleep(self.remove_takes)
        if self.remove_fails_with is not None:
            status, self.remove_fails_with = self.remove_fails_with, None
            response = requests.Response()
            response.status_code = status
            # docker-py raises NotFound for every 404.
            error = NotFound if status == 404 else APIError
            raise error("removal failed", response=response)
        if self.removed.is_set():
            raise NotFound("no such container")
        self.removed.set()
        self.finished.set()
        # Removing the container ends its stream.
        if self.peer is not None:
            close(self.peer)
        self.client.containers.made.remove(self)


def close(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    sock.close()


class FakeAPI:
    def __init__(self, client: FakeClient) -> None:
        self.client = client

    def attach_socket(self, container: str, params: dict[str, Any]) -> FakeStream:
        assert params == ATTACH
        self.client.events.append("attach")
        if self.client.attach_gate is not None:
            assert self.client.attach_gate.wait(10)
        if self.client.attach_fails_with is not None:
            response = requests.Response()
            response.status_code = self.client.attach_fails_with
            raise APIError("attach failed", response=response)
        [made] = [c for c in self.client.containers.made if c.name == container]
        stream = FakeStream(made.attach())
        self.client.streams.append(stream)
        return stream


class FakeContainers:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.made: list[FakeContainer] = []
        # Set to hold create until the test releases it.
        self.create_gate: threading.Event | None = None
        self.creating = threading.Event()

    def create(self, **spec: Any) -> FakeContainer:
        self.creating.set()
        self.client.events.append("create")
        if self.create_gate is not None:
            assert self.create_gate.wait(10)
        container = FakeContainer(self.client, spec)
        self.made.append(container)
        return container

    def list(
        self, all: bool = False, filters: dict[str, list[str]] | None = None
    ) -> list[FakeContainer]:
        assert all
        wanted = dict(label.split("=", 1) for label in (filters or {}).get("label", []))
        self.client.lookups.append(wanted)
        return [
            container
            for container in self.made
            if wanted.items() <= container.labels.items()
        ]


class FakeImages:
    def __init__(self) -> None:
        self.present: set[str] = set()

    def get(self, image: str) -> object:
        if image not in self.present:
            raise ImageNotFound(f"{image} not found")
        return object()


class FakeClient:
    def __init__(self, behaviour: Behaviour = exits) -> None:
        self.behaviour = behaviour
        self.reading: Reading = "reads"
        self.api = FakeAPI(self)
        self.containers = FakeContainers(self)
        self.images = FakeImages()
        # The calls in the order they came, and what each attach returned.
        self.events: list[str] = []
        self.streams: list[FakeStream] = []
        # The requests the containers read.
        self.requests: list[bytes] = []
        # An attach that fails with this status code, or waits to be let go.
        self.attach_fails_with: int | None = None
        self.attach_gate: threading.Event | None = None
        self.removals: list[str] = []
        self.lookups: list[dict[str, str]] = []
        self.closed = False
        # What DockerClient was given, when a test connects through it.
        self.options: dict[str, object] = {}

    def close(self) -> None:
        self.closed = True

    def open_sockets(self) -> list[socket.socket]:
        """The attach sockets the container piece has not closed."""
        return [
            stream._sock
            for stream in self.streams
            if stream._sock.fileno() != -1 or not stream._response.closed
        ]

    def stray(self, **labels: str) -> FakeContainer:
        """A container another worker, or an earlier attempt, left."""
        name = f"stray-{len(self.containers.made)}"
        container = FakeContainer(
            self,
            {"name": name, "labels": {"corvo.managed": "true", **labels}, "mounts": []},
        )
        self.containers.made.append(container)
        return container
