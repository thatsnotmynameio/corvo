import pytest
from claude_agent_sdk import ResultError
from hatchet_sdk import Context

from corvo.agents.session import sandbox_settings
from corvo.agents.tone import agent
from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.worker.agent_runtime.sessions import WRAPPER, AgentFailed
from corvo.worker.agents.tone import tone
from corvo.worker.defaults import (
    AGENT_CONCURRENCY,
    AGENT_EXECUTION_TIMEOUT,
    AGENT_SCHEDULE_TIMEOUT,
)
from support.scripted import SESSION_ID, ScriptedQuery, init, result

from ..agent_runtime.fake_cgroups import Tree
from ..test_registration import (
    AREAS,
    area_modules,
    definitions,
    problems,
    profile_lists,
)


@pytest.fixture
def lines(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The run log's lines, which a mock run's context would send to no one."""
    logged: list[str] = []
    monkeypatch.setattr(Context, "log", lambda self, line: logged.append(line))
    return logged


def test_tone_declares_the_agent_defaults() -> None:
    [task] = tone.tasks

    assert task.name == "tone"
    assert task.retries == 0
    assert task.execution_timeout == AGENT_EXECUTION_TIMEOUT
    assert task.schedule_timeout == AGENT_SCHEDULE_TIMEOUT
    assert task.concurrency == [AGENT_CONCURRENCY]


async def test_tone_runs_the_tone_agent_in_the_run_s_session(
    tree: Tree, lines: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    scripted = ScriptedQuery(init(), result(structured_output={"tone": "friendly"}))
    monkeypatch.setattr(agent, "query", scripted)

    output = await tone.aio_mock_run(ToneInput(text="Thanks a lot!"))

    assert output == ToneOutput(tone="friendly", friendly=True)
    [options] = scripted.options
    assert options.cli_path == WRAPPER
    assert options.env["CORVO_SANDBOX_CGROUP"] == str(tree.path)
    assert options.sandbox == sandbox_settings()
    assert tree.events == ["create", "kill", "remove"]
    assert lines[-1] == (
        f"agent tone: succeeded, cost=0.0042 turns=2 session={SESSION_ID}"
    )


async def test_the_turn_limit_fails_tone_with_its_report(
    tree: Tree, lines: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Covers AE3: no retry, since tone declares none, and the report logged.
    scripted = ScriptedQuery(
        init(),
        result(subtype="error_max_turns", is_error=True),
        error=ResultError(
            "error_max_turns", data={"subtype": "error_max_turns"}, exit_code=1
        ),
    )
    monkeypatch.setattr(agent, "query", scripted)

    with pytest.raises(AgentFailed, match="error_max_turns"):
        await tone.aio_mock_run(ToneInput(text="Whatever."))

    assert lines[-1] == (
        f"agent tone: error_max_turns, cost=0.0042 turns=2 session={SESSION_ID}"
    )


def test_tone_missing_from_the_agents_profile_is_named() -> None:
    # Covers AE1.
    defined = {
        profile: definitions(area_modules(areas)) for profile, areas in AREAS.items()
    }

    registered = profile_lists()
    registered["agents"] = [each for each in registered["agents"] if each is not tone]

    found = problems(defined, registered)

    assert found == [
        "corvo.worker.agents.tone.tone (tone) is on no worker: add it to the "
        "agents profile"
    ]
