from dataclasses import replace
from pathlib import Path

import pytest

from agents.isolation import assert_isolated
from agents.scripted import SESSION_ID, ScriptedQuery, init, result, session
from corvo.agents.dir_summary import agent
from corvo.agents.dir_summary.models import DirSummaryInput, DirSummaryOutput
from corvo.agents.report import RunReport

WORKDIR = Path("/var/lib/corvo/agents/workdirs/issue-7")
SUMMARY = {"summary": "Two notes on the release.", "word_count": 5}


def script(monkeypatch: pytest.MonkeyPatch) -> ScriptedQuery:
    scripted = ScriptedQuery(init(), result(structured_output=SUMMARY))
    monkeypatch.setattr(agent, "query", scripted)
    return scripted


async def test_the_session_s_summary_is_the_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script(monkeypatch)

    output, report = await agent.run(DirSummaryInput(), replace(session(), cwd=WORKDIR))

    assert output == DirSummaryOutput(**SUMMARY)
    assert report == RunReport(
        subtype="success", num_turns=2, total_cost_usd=0.0042, session_id=SESSION_ID
    )


async def test_the_options_read_only_the_working_directory_and_count_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted = script(monkeypatch)
    given = replace(session(), cwd=WORKDIR)

    await agent.run(DirSummaryInput(), given)

    [options] = scripted.options
    assert_isolated(options, given)
    assert options.cwd == WORKDIR
    assert options.tools == ["Read", "Glob", "Grep"]
    assert options.allowed_tools == [
        f"Read(/{WORKDIR}/**)",
        "mcp__dir_summary__count_words",
    ]
    assert isinstance(options.mcp_servers, dict)
    assert list(options.mcp_servers) == ["dir_summary"]
    assert options.model == "claude-haiku-5-5"
    assert (options.max_turns, options.max_budget_usd) == (15, 0.25)
    assert options.output_format == {
        "type": "json_schema",
        "schema": DirSummaryOutput.model_json_schema(),
    }
    assert isinstance(options.system_prompt, str)
    assert "count_words" in options.system_prompt
    assert scripted.prompts == [agent.REQUEST]
