import pytest
from claude_agent_sdk import ResultError

from agents.isolation import assert_isolated
from agents.scripted import SESSION_ID, ScriptedQuery, init, result, session
from corvo.agents.report import AgentRunFailed, RunReport
from corvo.agents.tone import agent
from corvo.agents.tone.models import ToneInput, ToneOutput, ToneVerdict


def script(monkeypatch: pytest.MonkeyPatch, scripted: ScriptedQuery) -> None:
    monkeypatch.setattr(agent, "query", scripted)


async def test_a_friendly_verdict_becomes_a_friendly_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = ScriptedQuery(init(), result(structured_output={"tone": "friendly"}))
    script(monkeypatch, scripted)

    output, report = await agent.run(ToneInput(text="Thanks a lot!"), session())

    assert output == ToneOutput(tone="friendly", friendly=True)
    assert report == RunReport(
        subtype="success", num_turns=2, total_cost_usd=0.0042, session_id=SESSION_ID
    )
    assert scripted.prompts == ["Thanks a lot!"]


async def test_the_options_are_isolated_and_ask_for_the_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = ScriptedQuery(init(), result(structured_output={"tone": "neutral"}))
    script(monkeypatch, scripted)

    given = session()

    await agent.run(ToneInput(text="The meeting is at noon."), given)

    [options] = scripted.options
    assert_isolated(options, given)
    assert options.cwd is None
    assert options.tools == []
    assert options.allowed_tools == []
    assert options.model == "claude-haiku-5-5"
    assert options.output_format == {
        "type": "json_schema",
        "schema": ToneVerdict.model_json_schema(),
    }
    assert isinstance(options.system_prompt, str)
    assert "friendly" in options.system_prompt


async def test_the_turn_limit_fails_the_run_with_its_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = ScriptedQuery(
        init(),
        result(subtype="error_max_turns", is_error=True),
        error=ResultError(
            "error_max_turns", data={"subtype": "error_max_turns"}, exit_code=1
        ),
    )
    script(monkeypatch, scripted)

    with pytest.raises(AgentRunFailed) as failure:
        await agent.run(ToneInput(text="Whatever."), session())

    assert failure.value.reason == "error_max_turns"
    assert failure.value.report == RunReport(
        subtype="error_max_turns",
        num_turns=2,
        total_cost_usd=0.0042,
        session_id=SESSION_ID,
    )
