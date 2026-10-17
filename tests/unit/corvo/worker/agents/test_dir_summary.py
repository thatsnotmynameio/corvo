from pathlib import Path

import pytest

from corvo.agents.dir_summary import agent
from corvo.agents.dir_summary.models import DirSummaryOutput
from corvo.worker.agent_calls import DirSummaryTaskInput
from corvo.worker.agent_runtime.sessions import AgentFailed
from corvo.worker.agents.dir_summary import dir_summary
from corvo.worker.defaults import (
    AGENT_CONCURRENCY,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_SCHEDULE_TIMEOUT,
)
from support.scripted import ScriptedQuery, init, result

from ..agent_runtime.fake_cgroups import Tree

SUMMARY = {"summary": "Two notes on the release.", "word_count": 5}


def test_dir_summary_declares_the_agent_defaults() -> None:
    [task] = dir_summary.tasks

    assert task.name == "dir-summary"
    assert task.retries == 0
    assert task.execution_timeout == AGENT_EXECUTION_TIMEOUT
    assert task.schedule_timeout == AGENT_SCHEDULE_TIMEOUT
    assert task.concurrency == [AGENT_CONCURRENCY]


async def test_dir_summary_runs_in_its_working_directory_read_only(
    tree: Tree, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = tmp_path / "root" / "workdirs" / "issue-7"
    workdir.mkdir()
    scripted = ScriptedQuery(init(), result(structured_output=SUMMARY))
    monkeypatch.setattr(agent, "query", scripted)

    output = await dir_summary.aio_mock_run(DirSummaryTaskInput(workdir="issue-7"))

    assert output == DirSummaryOutput(**SUMMARY)
    [options] = scripted.options
    assert options.cwd == workdir
    assert options.env["CORVO_SANDBOX_WORKDIR"] == str(workdir)
    assert options.env["CORVO_SANDBOX_WRITES"] == "0"
    assert tree.events == ["create", "kill", "remove"]


async def test_a_working_directory_outside_workdirs_fails_before_any_cgroup(
    tree: Tree, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "root" / "elsewhere").mkdir()
    scripted = ScriptedQuery(init(), result(structured_output=SUMMARY))
    monkeypatch.setattr(agent, "query", scripted)

    with pytest.raises(AgentFailed, match="is not a directory below"):
        await dir_summary.aio_mock_run(DirSummaryTaskInput(workdir="../elsewhere"))

    assert tree.events == []
    assert scripted.options == []
