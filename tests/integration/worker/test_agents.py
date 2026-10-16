"""tone and dir-summary end to end: on the real Hatchet, in the agent
worker's compose service, in real bubblewrap and cgroups, with the fake
claude CLI as its sessions' engine (U9, R24).

The tests that stop the agent worker come last, and each starts it again.
"""

import asyncio
import json
import re
from pathlib import Path

import pytest
from hatchet_sdk import Hatchet, V1TaskStatus
from hatchet_sdk.clients.admin import TaskRunDetail
from hatchet_sdk.clients.rest.exceptions import NotFoundException

from corvo.agents.dir_summary.models import DirSummaryOutput
from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.worker.agent_calls import DirSummaryTaskInput
from corvo.worker.agent_runtime.sandbox import PLACEHOLDER

from .conftest import (
    NO_SECCOMP,
    TEST_CREDENTIAL,
    AgentWorker,
    dir_summary_stub,
    finished_tasks,
    tone_stub,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")

FRIENDLY = ToneOutput(tone="friendly", friendly=True)


async def tone_task(hatchet: Hatchet, run_id: str) -> TaskRunDetail:
    """The run's tone task, once it is done. The caller bounds the wait."""
    return (await finished_tasks(hatchet, run_id, count=1))["tone"]


async def running(hatchet: Hatchet, worker: AgentWorker, run_id: str) -> str:
    """Waits until the run's session is in its cgroup, and returns the task
    run's ID. The caller bounds the wait."""
    while True:
        details = await hatchet.runs.aio_get_details(run_id)
        for task in details.task_runs.values():
            if task.status == V1TaskStatus.RUNNING and (
                f"run-{task.external_id}" in await asyncio.to_thread(worker.run_cgroups)
            ):
                return task.external_id
        await asyncio.sleep(0.5)


async def run_log(hatchet: Hatchet, task_run_id: str, pattern: str) -> list[str]:
    """The task run's log, once a line matches pattern. Hatchet takes the
    lines after the run ends. The caller bounds the wait."""
    while True:
        listed = await hatchet.logs.aio_list(task_run_id)
        rows = sorted(listed.rows or [], key=lambda row: row.created_at)
        lines = [row.message for row in rows]
        if any(re.search(pattern, line) for line in lines):
            return lines
        await asyncio.sleep(1)


async def ended(worker: AgentWorker) -> None:
    """Waits until no session process and no run's cgroup remains in the
    agent worker. The caller bounds the wait."""
    while await asyncio.to_thread(worker.session_processes) or (
        await asyncio.to_thread(worker.run_cgroups)
    ):
        await asyncio.sleep(0.5)


async def test_tone_returns_the_engine_s_verdict(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    async with asyncio.timeout(60):
        output = await tone_stub(hatchet).aio_run(ToneInput(text="Thanks a lot!"))

    assert output == FRIENDLY
    assert agent_worker.run_cgroups() == []
    assert agent_worker.session_processes() == []


async def test_tone_reaches_the_api_through_the_proxy_with_its_credential(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    before = len(await asyncio.to_thread(agent_worker.api_requests))

    async with asyncio.timeout(60):
        output = await tone_stub(hatchet).aio_run(ToneInput(text="fake:api Hi!"))

    assert output == FRIENDLY
    requests = (await asyncio.to_thread(agent_worker.api_requests))[before:]
    assert [request["path"] for request in requests] == ["/v1/messages"]
    headers = {name.lower(): value for name, value in requests[0]["headers"].items()}
    assert headers["x-api-key"] == TEST_CREDENTIAL
    assert "authorization" not in headers
    assert PLACEHOLDER not in json.dumps(requests)


async def test_dir_summary_counts_its_words_in_the_worker(
    agent_worker: AgentWorker, hatchet: Hatchet, workdir: Path
) -> None:
    for name in ("notes.md", "plan.txt"):
        (workdir / name).write_text("A small file.\n")
        (workdir / name).chmod(0o644)

    async with asyncio.timeout(60):
        output = await dir_summary_stub(hatchet).aio_run(
            DirSummaryTaskInput(workdir=workdir.name)
        )

    # The fake's summary, made in the sandbox, which sees the directory
    # read-only, and its words as count_words counted them in the worker.
    assert output == DirSummaryOutput(
        summary="2 files, read-only: notes.md, plan.txt", word_count=5
    )
    assert agent_worker.run_cgroups() == []


async def test_tone_at_its_turn_limit_fails_without_a_retry(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    async with asyncio.timeout(60):
        run = await tone_stub(hatchet).aio_run(
            ToneInput(text="fake:max-turns"), wait_for_result=False
        )
        with pytest.raises(Exception, match="agent tone failed: error_max_turns"):
            await run.aio_result()
        task = await tone_task(hatchet, run.workflow_run_id)
        lines = await run_log(hatchet, task.external_id, r"^agent tone: ")
        summary = await hatchet.runs.aio_get_task_run(task.external_id)

    assert task.status == V1TaskStatus.FAILED
    assert summary.retry_count == 0
    assert lines[-1] == (
        "agent tone: error_max_turns, cost=0.0 turns=3 session=fake-session"
    )


async def test_a_cancelled_run_leaves_no_process(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    async with asyncio.timeout(60):
        run = await tone_stub(hatchet).aio_run(
            ToneInput(text="fake:hang"), wait_for_result=False
        )
        await running(hatchet, agent_worker, run.workflow_run_id)

        await hatchet.runs.aio_cancel(run.workflow_run_id)

    async with asyncio.timeout(5):
        await ended(agent_worker)


async def test_a_run_out_of_memory_fails_and_another_run_completes(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    tone = tone_stub(hatchet)

    async with asyncio.timeout(120):
        hog = await tone.aio_run(ToneInput(text="fake:hog"), wait_for_result=False)
        other = await tone.aio_run(ToneInput(text="Thanks!"), wait_for_result=False)
        with pytest.raises(Exception, match="agent tone failed: out of memory"):
            await hog.aio_result()
        assert ToneOutput.model_validate(await other.aio_result()) == FRIENDLY
        await ended(agent_worker)


async def test_a_sigterm_fails_the_running_session_for_good(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    async with asyncio.timeout(120):
        run = await tone_stub(hatchet).aio_run(
            ToneInput(text="fake:hang"), wait_for_result=False
        )
        task_run_id = await running(hatchet, agent_worker, run.workflow_run_id)

        await asyncio.to_thread(agent_worker.run, "stop", "agent-worker")
        task = await tone_task(hatchet, run.workflow_run_id)
        await asyncio.to_thread(agent_worker.up)
        # Past the engine's 30 seconds without a heartbeat, after which it
        # would re-queue a run still marked running.
        await asyncio.sleep(35)
        summary = await hatchet.runs.aio_get_task_run(task_run_id)

    assert task.status == V1TaskStatus.FAILED
    assert task.error is not None
    assert "agent tone failed: worker stopping" in task.error
    assert summary.status == V1TaskStatus.FAILED
    assert summary.retry_count == 0


async def test_a_worker_that_cannot_isolate_registers_nothing(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    async with asyncio.timeout(240):
        await asyncio.to_thread(agent_worker.run, "stop", "agent-worker")
        await asyncio.to_thread(
            agent_worker.run, "up", "--detach", "agent-worker", extra=[NO_SECCOMP]
        )
        run = await tone_stub(hatchet).aio_run(
            ToneInput(text="Thanks for waiting!"), wait_for_result=False
        )
        # Until it has refused twice: it exits, and compose starts it again.
        logs = ""
        while logs.count("agents refused: bubblewrap") < 2:
            await asyncio.sleep(2)
            logs = await asyncio.to_thread(agent_worker.logs)
        status = await hatchet.runs.aio_get_status(run.workflow_run_id)

        await asyncio.to_thread(agent_worker.up)
        output = await run.aio_result()

    assert "agents refused: bubblewrap: bwrap: No permissions" in logs
    assert "every isolation check passed" not in logs
    assert status == V1TaskStatus.QUEUED
    # It waited for an agent worker that can isolate it.
    assert ToneOutput.model_validate(output) == FRIENDLY


async def test_a_run_before_any_agent_worker_registered_is_dropped(
    agent_worker: AgentWorker, hatchet: Hatchet
) -> None:
    # The first deployment's case, for docs/agents.md: a run of a task no
    # worker has ever registered is lost. The engine either refuses the
    # trigger, or returns a run's ID and keeps no run, even once a worker
    # registers the task; both have been seen.
    first_run = agent_worker.first_run
    if isinstance(first_run, Exception):
        assert "workflow names not found: tone" in str(first_run), repr(first_run)
        return
    assert isinstance(first_run, str)
    with pytest.raises(NotFoundException):
        await hatchet.runs.aio_get_status(first_run)
