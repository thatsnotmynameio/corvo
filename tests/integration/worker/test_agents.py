"""The agent tasks on the real Hatchet and a real rootless Podman.

The worker runs tone in the agent image the session built, with the fake
claude CLI in place of the real one, so no test reaches Claude. The fake
answers a friendly verdict, and its prompt picks the other paths:
fake:max-turns ends on the turn limit and fake:hang never answers.
"""

import asyncio
import os
import signal
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from docker.models.containers import Container
from hatchet_sdk import ClientConfig, ClientTLSConfig, Hatchet, V1TaskStatus
from hatchet_sdk.runnables.workflow import Standalone

from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.worker.agent_runtime.spec import ENDED, MANAGED, deployment_label
from corvo.worker.tasks.hello import HelloInput, HelloOutput

from .conftest import Podman, WorkerProcess, running_worker

pytestmark = [
    pytest.mark.usefixtures("worker"),
    pytest.mark.asyncio(loop_scope="session"),
]


def tone_stub(hatchet: Hatchet) -> Standalone[ToneInput, ToneOutput]:
    return hatchet.stubs.task(
        name="tone", input_validator=ToneInput, output_validator=ToneOutput
    )


def labelled(podman: Podman, **labels: str) -> list[Container]:
    filters: dict[str, str | list[str] | bool] = {
        "label": [MANAGED, *(f"{key}={value}" for key, value in labels.items())]
    }
    return podman.client.containers.list(all=True, filters=filters)


async def until[T](check: Callable[[], T], timeout: float = 60) -> T:
    """Polls check until it returns something truthy, within timeout."""
    async with asyncio.timeout(timeout):
        while not (found := await asyncio.to_thread(check)):
            await asyncio.sleep(0.5)
    return found


def running(podman: Podman, run_id: str) -> Callable[[], list[Container]]:
    """Whether the run's container is up, as the worker starts it."""

    def check() -> list[Container]:
        return [
            container
            for container in labelled(podman, **{"corvo.run_id": run_id})
            if container.status == "running"
        ]

    return check


async def ended(hatchet: Hatchet, run_id: str) -> Any:
    """The run's details once its one task is done."""

    async def details() -> Any:
        found = await hatchet.runs.aio_get(run_id)
        if found.tasks and all(task.status in ENDED for task in found.tasks):
            return found
        return None

    async with asyncio.timeout(60):
        while (found := await details()) is None:
            await asyncio.sleep(1)
    return found


async def test_tone_runs_in_a_container_it_then_removes(
    hatchet: Hatchet, podman: Podman
) -> None:
    # Covers AE1: the request reaches the container over its stdin, so the
    # agent root holds nothing but the Podman socket at any point of the run.
    seen: set[Path] = set()

    async def watch() -> None:
        while True:
            seen.update(p for p in podman.root.rglob("*") if not p.is_socket())
            await asyncio.sleep(0.05)

    watching = asyncio.create_task(watch())
    try:
        async with asyncio.timeout(120):
            output = await tone_stub(hatchet).aio_run(ToneInput(text="Thanks a lot!"))
    finally:
        watching.cancel()

    assert output == ToneOutput(tone="friendly", friendly=True)
    assert labelled(podman) == []
    assert seen == set()


async def test_the_worker_found_its_containers_as_the_spec_asks(
    worker: WorkerProcess,
) -> None:
    # The probe's report matched the spec on this Podman (R15).
    assert "agents are enabled" in worker.log.read_text()


async def test_a_run_past_its_turn_limit_fails_once_with_its_report(
    hatchet: Hatchet, podman: Podman
) -> None:
    run = await tone_stub(hatchet).aio_run(
        ToneInput(text="fake:max-turns"), wait_for_result=False
    )
    with pytest.raises(Exception, match="agent tone failed: error_max_turns"):
        async with asyncio.timeout(120):
            await run.aio_result()

    [task] = (await ended(hatchet, run.workflow_run_id)).tasks
    assert task.status == V1TaskStatus.FAILED
    assert task.retry_count in (0, None)

    async def report() -> list[str]:
        lines = await hatchet.logs.aio_list(task.task_external_id)
        return [
            line.message
            for line in lines.rows or []
            if line.message.startswith("agent tone: failed")
        ]

    async with asyncio.timeout(30):
        while not (found := await report()):
            await asyncio.sleep(1)
    [line] = found
    assert "cost=" in line and "turns=" in line and "session=fake-session" in line
    assert labelled(podman) == []


async def test_a_cancelled_run_leaves_no_container(
    hatchet: Hatchet, podman: Podman
) -> None:
    run = await tone_stub(hatchet).aio_run(
        ToneInput(text="fake:hang"), wait_for_result=False
    )
    await until(running(podman, run.workflow_run_id))

    # The engine sends a timed-out task the same action a cancel does.
    await hatchet.runs.aio_cancel(run.workflow_run_id)

    await until(lambda: labelled(podman, **{"corvo.run_id": run.workflow_run_id}) == [])
    [task] = (await ended(hatchet, run.workflow_run_id)).tasks
    assert task.status == V1TaskStatus.CANCELLED


def namespaced(worker_env: dict[str, str], namespace: str) -> dict[str, str]:
    """A worker environment whose tasks Hatchet names apart, so only that
    worker serves them."""
    return {**worker_env, "HATCHET_CLIENT_NAMESPACE": namespace}


def namespaced_client(hatchet: Hatchet, namespace: str) -> Hatchet:
    """A client that triggers the tasks of a namespaced worker."""
    return Hatchet(
        config=ClientConfig(
            token=hatchet.config.token,
            tls_config=ClientTLSConfig(strategy="none"),
            namespace=namespace,
        )
    )


async def test_a_starting_worker_removes_only_containers_of_ended_runs(
    hatchet: Hatchet,
    podman: Podman,
    worker_env: dict[str, str],
    agent_image: str,
    tmp_path: Path,
) -> None:
    # A container this deployment's lost worker left, of a run that ended.
    hello = hatchet.stubs.task(
        name="hello", input_validator=HelloInput, output_validator=HelloOutput
    )
    ended_run = await hello.aio_run(HelloInput(name="corvo"), wait_for_result=False)
    # Ended in Hatchet's read model too, which the sweep reads.
    await ended(hatchet, ended_run.workflow_run_id)
    deployment = deployment_label(hatchet.config.tenant_id, hatchet.config.server_url)
    podman.client.containers.create(
        agent_image,
        ["probe"],
        labels={
            "corvo.managed": "true",
            "corvo.deployment": deployment,
            "corvo.run_id": ended_run.workflow_run_id,
            "corvo.task_run_id": "stray",
        },
    )
    # A run still going on the session's worker.
    live = await tone_stub(hatchet).aio_run(
        ToneInput(text="fake:hang"), wait_for_result=False
    )
    [live_container] = await until(running(podman, live.workflow_run_id))
    env = namespaced(worker_env, "sweep")

    try:
        with running_worker(env, tmp_path / "second.log"):
            pass

        assert labelled(podman, **{"corvo.task_run_id": "stray"}) == []
        assert [c.id for c in running(podman, live.workflow_run_id)()] == [
            live_container.id
        ]
    finally:
        await hatchet.runs.aio_cancel(live.workflow_run_id)
        await until(
            lambda: labelled(podman, **{"corvo.run_id": live.workflow_run_id}) == []
        )


async def test_sigterm_removes_the_running_containers_and_fails_their_runs(
    hatchet: Hatchet,
    podman: Podman,
    worker_env: dict[str, str],
    tmp_path: Path,
) -> None:
    env = namespaced(worker_env, "sigterm")
    with running_worker(env, tmp_path / "sigterm.log") as worker:
        run = await tone_stub(namespaced_client(hatchet, "sigterm")).aio_run(
            ToneInput(text="fake:hang"), wait_for_result=False
        )
        await until(running(podman, run.workflow_run_id))

        # To the worker alone, as docker stop signals its container's first
        # process.
        os.kill(worker.process.pid, signal.SIGTERM)
        await asyncio.to_thread(worker.process.wait, 60)

    assert labelled(podman, **{"corvo.run_id": run.workflow_run_id}) == []
    [task] = (await ended(hatchet, run.workflow_run_id)).tasks
    assert task.status == V1TaskStatus.FAILED
    # Failed while the worker answered, so not re-queued as a lost one.
    await asyncio.sleep(5)
    [task] = (await hatchet.runs.aio_get(run.workflow_run_id)).tasks
    assert (task.status, task.retry_count or 0) == (V1TaskStatus.FAILED, 0)
