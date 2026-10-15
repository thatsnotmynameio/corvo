import asyncio
import logging
import os
import signal
from collections.abc import Iterator
from pathlib import Path
from types import FrameType
from typing import Any, cast

import pytest
from docker import DockerClient
from hatchet_sdk import V1TaskStatus
from hatchet_sdk.clients.rest.exceptions import NotFoundException

from corvo.agents.envelope import ProbeReport
from corvo.settings import Settings
from corvo.worker.agent_runtime import containers, startup
from corvo.worker.agent_runtime.containers import Runtime
from corvo.worker.agent_runtime.spec import ISOLATION_ENV, Credential

from .fake_podman import Behaviour, Exit, FakeClient, FakeContainer
from .probe_report import matching_report

DEPLOYMENT = "tenant@http://hatchet"
IMAGE = "localhost/corvo-agent:latest"


def probing(probed: ProbeReport, code: int = 0) -> Behaviour:
    def behaviour(run_dir: Path) -> Exit:
        (run_dir / "probe.json").write_text(probed.model_dump_json())
        return Exit(code=code)

    return behaviour


@pytest.fixture
def podman(monkeypatch: pytest.MonkeyPatch) -> FakeClient:
    client = FakeClient(probing(matching_report()))
    client.images.present.add(IMAGE)

    def connect(**options: object) -> FakeClient:
        client.options = options
        return client

    monkeypatch.setattr(startup, "DockerClient", connect)
    # Each test leaves the state as it found it.
    monkeypatch.setattr(containers, "state", containers.NOT_CONFIGURED)
    return client


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        agent_podman_socket="/run/podman.sock",
        agent_root=str(tmp_path),
        agent_credential="secret",
    )


async def nothing_ran(run_id: str) -> V1TaskStatus:
    raise AssertionError("no run to look up")


async def test_a_probe_that_matches_enables_agents(
    podman: FakeClient, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    runtime = containers.state
    assert isinstance(runtime, Runtime)
    assert runtime.image == IMAGE
    assert runtime.credential == Credential(kind="api_key", value="secret")
    assert runtime.deployment == DEPLOYMENT
    assert "agents are enabled" in caplog.messages
    assert not podman.closed


async def test_each_podman_call_returns_within_the_cleanup_bound(
    podman: FakeClient, settings: Settings
) -> None:
    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    # A create the cleanup waits for returns while the cleanup can still
    # remove its container.
    timeout = podman.options["timeout"]
    assert isinstance(timeout, int)
    assert 0 < timeout < containers.CLEANUP_TIMEOUT


async def test_the_probe_runs_the_spec_without_a_credential(
    podman: FakeClient, settings: Settings
) -> None:
    specs: list[dict[str, Any]] = []

    def record(run_dir: Path) -> Exit:
        [container] = podman.containers.made
        specs.append(container.spec)
        return probing(matching_report())(run_dir)

    podman.behaviour = record

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    [spec] = specs
    assert spec["command"] == ["probe"]
    assert spec["labels"]["corvo.deployment"] == DEPLOYMENT
    assert "corvo.run_id" not in spec["labels"]
    assert spec["environment"] == ISOLATION_ENV


@pytest.mark.parametrize(
    "probed", [matching_report(), matching_report(memory_max="max")]
)
async def test_the_probe_leaves_no_container_or_directory(
    podman: FakeClient, settings: Settings, probed: ProbeReport
) -> None:
    podman.behaviour = probing(probed)

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert podman.containers.made == []
    assert list((Path(settings.agent_root) / "runs").iterdir()) == []


@pytest.mark.parametrize(
    ("probed", "reason"),
    [
        (matching_report(memory_max="max"), "memory.max is 'max'"),
        (matching_report(fingerprint="stale"), "fingerprint differs"),
        (matching_report(cap_eff="00000000a80425fb"), "effective capabilities"),
    ],
)
async def test_a_probe_that_differs_disables_agents(
    podman: FakeClient,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
    probed: ProbeReport,
    reason: str,
) -> None:
    podman.behaviour = probing(probed)

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert isinstance(containers.state, str)
    assert reason in containers.state
    assert any(reason in message for message in caplog.messages)


async def test_a_probe_that_fails_disables_agents(
    podman: FakeClient, settings: Settings
) -> None:
    podman.behaviour = lambda run_dir: Exit(code=1)

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert containers.state == "agents are disabled: the probe exited with 1"
    assert podman.containers.made == []


async def test_an_invalid_probe_report_disables_agents_without_its_content(
    podman: FakeClient, settings: Settings
) -> None:
    def behaviour(run_dir: Path) -> Exit:
        (run_dir / "probe.json").write_text('{"fingerprint": "leaked-content"}')
        return Exit()

    podman.behaviour = behaviour

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert containers.state == "agents are disabled: the probe's report is invalid"


async def test_a_missing_image_disables_agents(
    podman: FakeClient, settings: Settings
) -> None:
    podman.images.present.clear()

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert isinstance(containers.state, str)
    assert f"{IMAGE} is not in the agents' Podman" in containers.state
    assert podman.containers.made == []
    assert podman.closed


async def test_an_empty_credential_disables_agents(
    podman: FakeClient, settings: Settings
) -> None:
    settings.agent_credential = ""

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert containers.state == ("agents are disabled: CORVO_AGENT_CREDENTIAL is empty")


async def test_without_configuration_preparation_does_nothing(
    podman: FakeClient, settings: Settings
) -> None:
    settings.agent_podman_socket = ""

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert containers.state == containers.NOT_CONFIGURED
    assert podman.lookups == []


async def test_open_egress_disables_agents_when_its_block_is_required(
    podman: FakeClient, settings: Settings
) -> None:
    podman.behaviour = probing(matching_report(metadata_reachable=True))
    settings.agent_require_egress_block = True

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert isinstance(containers.state, str)
    assert "reached the gateway or the metadata address" in containers.state


async def test_open_egress_only_warns_when_its_block_is_not_required(
    podman: FakeClient, settings: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    podman.behaviour = probing(matching_report(metadata_reachable=True))

    await startup.prepare(settings, DEPLOYMENT, nothing_ran)

    assert isinstance(containers.state, Runtime)
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "reached the gateway or the metadata address" in warning.getMessage()


def stray(client: FakeClient, run_id: str) -> FakeContainer:
    return client.stray(**{"corvo.deployment": DEPLOYMENT, "corvo.run_id": run_id})


async def test_the_sweep_removes_only_containers_whose_run_ended(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeClient()
    statuses = {
        "completed": V1TaskStatus.COMPLETED,
        "failed": V1TaskStatus.FAILED,
        "cancelled": V1TaskStatus.CANCELLED,
        "queued": V1TaskStatus.QUEUED,
        "running": V1TaskStatus.RUNNING,
    }
    for run_id in [*statuses, "missing"]:
        stray(client, run_id)
    elsewhere = client.stray(**{"corvo.deployment": "other", "corvo.run_id": "x"})

    async def status_of(run_id: str) -> V1TaskStatus:
        if run_id not in statuses:
            raise NotFoundException(status=404)
        return statuses[run_id]

    await startup.sweep(cast(DockerClient, client), DEPLOYMENT, status_of)

    left = [container.labels["corvo.run_id"] for container in client.containers.made]
    assert left == ["queued", "running", "missing", "x"]
    assert not elsewhere.removed.is_set()
    assert any("missing" in message for message in caplog.messages)


async def test_the_sweep_leaves_the_probe_containers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeClient()
    client.stray(**{"corvo.deployment": DEPLOYMENT, "corvo.probe": "p"})

    await startup.sweep(cast(DockerClient, client), DEPLOYMENT, nothing_ran)

    assert len(client.containers.made) == 1


async def test_the_sweep_keeps_runs_whose_lookup_hangs_within_its_bound(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(startup, "LOOKUP_TIMEOUT", 0.2)
    client = FakeClient()
    for run_id in ["a", "b", "c", "d"]:
        stray(client, run_id)

    async def hangs(run_id: str) -> V1TaskStatus:
        await asyncio.sleep(60)
        raise AssertionError("the lookup was not bounded")

    async with asyncio.timeout(2):
        await startup.sweep(cast(DockerClient, client), DEPLOYMENT, hangs)

    assert len(client.containers.made) == 4
    timed_out = [m for m in caplog.messages if "timed out" in m]
    assert len(timed_out) == 4


@pytest.fixture
def sigterm() -> Iterator[list[int]]:
    """A stand-in for Hatchet's own SIGTERM handler, which records the
    signals it got; the test's handler is restored afterwards."""
    received: list[int] = []

    def hatchets(signum: int, frame: FrameType | None) -> None:
        received.append(signum)

    previous = signal.signal(signal.SIGTERM, hatchets)
    try:
        yield received
    finally:
        signal.signal(signal.SIGTERM, previous)


async def test_sigterm_removes_the_in_flight_containers_then_hands_over(
    sigterm: list[int], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeClient()
    mine = client.stray(**{"corvo.task_run_id": "mine"})
    other = client.stray(**{"corvo.task_run_id": "other"})
    runtime = Runtime(
        client=cast(DockerClient, client),
        root=tmp_path,
        image=IMAGE,
        credential=Credential(kind="api_key", value="secret"),
        deployment=DEPLOYMENT,
        in_flight={"mine"},
    )
    monkeypatch.setattr(containers, "state", runtime)
    removed_first: list[bool] = []

    def after_removal(signum: int, frame: FrameType | None) -> None:
        removed_first.append(mine.removed.is_set())
        sigterm.append(signum)

    signal.signal(signal.SIGTERM, after_removal)
    startup.install_sigterm_hook()

    signal.raise_signal(signal.SIGTERM)
    async with asyncio.timeout(5):
        while not sigterm:
            await asyncio.sleep(0.01)

    assert removed_first == [True]
    assert not other.removed.is_set()
    assert sigterm == [signal.SIGTERM]


async def test_sigterm_without_agents_hands_over_at_once(
    sigterm: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(containers, "state", containers.NOT_CONFIGURED)
    startup.install_sigterm_hook()

    signal.raise_signal(signal.SIGTERM)

    assert sigterm == [signal.SIGTERM]


async def test_sigterm_hands_over_even_when_the_removal_fails(
    sigterm: list[int],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeClient()
    client.stray(**{"corvo.task_run_id": "mine"}).remove_fails_with = 500
    runtime = Runtime(
        client=cast(DockerClient, client),
        root=tmp_path,
        image=IMAGE,
        credential=Credential(kind="api_key", value="secret"),
        deployment=DEPLOYMENT,
        in_flight={"mine"},
    )
    monkeypatch.setattr(containers, "state", runtime)
    startup.install_sigterm_hook()

    signal.raise_signal(signal.SIGTERM)
    async with asyncio.timeout(5):
        while not sigterm:
            await asyncio.sleep(0.01)

    assert sigterm == [signal.SIGTERM]
    assert "removing the in-flight agent containers failed" in caplog.messages


async def test_sigterm_during_preparation_removes_the_probe(
    podman: FakeClient, settings: Settings
) -> None:
    podman.behaviour = lambda run_dir: Exit(hangs=True)
    preparing = asyncio.create_task(
        startup.prepare_until_stopped(settings, DEPLOYMENT, nothing_ran)
    )
    async with asyncio.timeout(5):
        while not (podman.containers.made and podman.containers.made[0].started):
            await asyncio.sleep(0.01)

    os.kill(os.getpid(), signal.SIGTERM)

    async with asyncio.timeout(5):
        assert await preparing
    assert podman.containers.made == []
    assert list((Path(settings.agent_root) / "runs").iterdir()) == []


async def test_preparation_that_ends_reports_no_stop(
    podman: FakeClient, settings: Settings
) -> None:
    assert not await startup.prepare_until_stopped(settings, DEPLOYMENT, nothing_ran)
    assert isinstance(containers.state, Runtime)
