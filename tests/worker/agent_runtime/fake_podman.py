"""A stand-in for docker-py's client over Podman, for the container piece's
unit tests.

A container it creates does nothing until started; then its behaviour, a
function of the run directory mounted at /corvo/run, writes what the agent
would and says what the container printed to stderr and how it exited. A
container whose behaviour hangs runs until it is removed, as a session past
its deadline would.
"""

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests
from docker.errors import APIError, ImageNotFound, NotFound


@dataclass
class Exit:
    stderr: list[bytes] = field(default_factory=list)
    code: int = 0
    oom_killed: bool = False
    hangs: bool = False


type Behaviour = Callable[[Path], Exit]


def exits(run_dir: Path) -> Exit:
    return Exit()


class FakeContainer:
    def __init__(self, client: FakeClient, spec: dict[str, Any]) -> None:
        self.client = client
        self.spec = spec
        self.name: str = spec["name"]
        self.labels: dict[str, str] = spec["labels"]
        self.started = False
        self.removed = threading.Event()
        self.exit = Exit()
        # A removal that fails with this status code, once.
        self.remove_fails_with: int | None = None
        self.attrs: dict[str, Any] = {"State": {"OOMKilled": False}}

    @property
    def run_dir(self) -> Path:
        [run] = [m for m in self.spec["mounts"] if m["Target"] == "/corvo/run"]
        return Path(run["Source"])

    def start(self) -> None:
        self.started = True
        self.exit = self.client.behaviour(self.run_dir)
        self.attrs = {"State": {"OOMKilled": self.exit.oom_killed}}

    def logs(self, **options: Any) -> Iterator[bytes]:
        assert options == {
            "stream": True,
            "follow": True,
            "stdout": False,
            "stderr": True,
        }
        yield from self.exit.stderr
        if self.exit.hangs:
            self.removed.wait()

    def wait(self) -> dict[str, int]:
        if self.removed.is_set():
            raise NotFound("no such container")
        return {"StatusCode": self.exit.code}

    def reload(self) -> None:
        if self.removed.is_set():
            raise NotFound("no such container")

    def remove(self, force: bool = False) -> None:
        assert force
        self.client.removals.append(self.name)
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
        self.client.containers.made.remove(self)


class FakeContainers:
    def __init__(self, client: FakeClient) -> None:
        self.client = client
        self.made: list[FakeContainer] = []
        # Set to hold create until the test releases it.
        self.create_gate: threading.Event | None = None
        self.creating = threading.Event()

    def create(self, **spec: Any) -> FakeContainer:
        self.creating.set()
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
        self.containers = FakeContainers(self)
        self.images = FakeImages()
        self.removals: list[str] = []
        self.lookups: list[dict[str, str]] = []

    def stray(self, **labels: str) -> FakeContainer:
        """A container another worker, or an earlier attempt, left."""
        name = f"stray-{len(self.containers.made)}"
        container = FakeContainer(
            self,
            {"name": name, "labels": {"corvo.managed": "true", **labels}, "mounts": []},
        )
        self.containers.made.append(container)
        return container
