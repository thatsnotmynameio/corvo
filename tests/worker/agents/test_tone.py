from pathlib import Path
from typing import cast

import pytest
from docker import DockerClient

from corvo.agents.envelope import AgentRequest, RunReport, Succeeded
from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.worker.agent_runtime import containers
from corvo.worker.agent_runtime.containers import Runtime
from corvo.worker.agent_runtime.spec import Credential
from corvo.worker.agents.tone import tone
from corvo.worker.defaults import (
    AGENT_CONCURRENCY,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_SCHEDULE_TIMEOUT,
)

from ..agent_runtime.fake_podman import Exit, FakeClient


def test_tone_declares_the_agent_defaults() -> None:
    [task] = tone.tasks

    assert task.name == "tone"
    assert task.retries == 0
    assert task.execution_timeout == AGENT_EXECUTION_TIMEOUT
    assert task.schedule_timeout == AGENT_SCHEDULE_TIMEOUT
    assert task.concurrency == [AGENT_CONCURRENCY]


async def test_tone_runs_the_tone_agent_in_its_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[AgentRequest] = []

    def agent(run_dir: Path) -> Exit:
        requests.append(
            AgentRequest.model_validate_json((run_dir / "request.json").read_text())
        )
        envelope = Succeeded(
            output={"tone": "neutral", "friendly": False}, report=RunReport()
        )
        (run_dir / "result.json").write_text(envelope.model_dump_json())
        return Exit()

    (tmp_path / "runs").mkdir()
    runtime = Runtime(
        client=cast(DockerClient, FakeClient(agent)),
        root=tmp_path,
        image="corvo-agent",
        credential=Credential(kind="api_key", value="secret"),
        deployment="tenant@http://hatchet",
    )
    monkeypatch.setattr(containers, "state", runtime)

    output = await tone.aio_mock_run(ToneInput(text="Noted."))

    assert output == ToneOutput(tone="neutral", friendly=False)
    assert [request.agent for request in requests] == ["tone"]
