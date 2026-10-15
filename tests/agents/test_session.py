import pytest
from claude_agent_sdk import ProcessError, ResultError
from pydantic import BaseModel

from agents.scripted import SESSION_ID, ScriptedQuery, init, result
from corvo.agents.report import AgentRunFailed, RunReport
from corvo.agents.session import consume


class Verdict(BaseModel):
    tone: str


def report(subtype: str) -> RunReport:
    return RunReport(
        subtype=subtype, num_turns=2, total_cost_usd=0.0042, session_id=SESSION_ID
    )


def max_turns_error() -> ResultError:
    return ResultError(
        "Claude Code returned an error result: error_max_turns",
        data={"subtype": "error_max_turns", "is_error": True},
        exit_code=1,
    )


async def test_a_valid_structured_output_is_returned_with_the_report() -> None:
    session = ScriptedQuery(init(), result(structured_output={"tone": "friendly"}))

    verdict, run_report = await consume(session.stream(), Verdict)

    assert verdict == Verdict(tone="friendly")
    assert run_report == report("success")


async def test_the_session_id_goes_to_stderr_when_the_session_starts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    session = ScriptedQuery(init(), result(structured_output={"tone": "friendly"}))

    await consume(session.stream(), Verdict)

    assert capsys.readouterr().err == f"session {SESSION_ID}\n"


async def test_the_turn_limit_fails_with_its_subtype_and_report() -> None:
    session = ScriptedQuery(
        init(),
        result(subtype="error_max_turns", is_error=True),
        error=max_turns_error(),
    )

    with pytest.raises(AgentRunFailed) as failure:
        await consume(session.stream(), Verdict)

    assert failure.value.reason == "error_max_turns"
    assert failure.value.report == report("error_max_turns")


async def test_an_api_error_reported_as_success_fails() -> None:
    session = ScriptedQuery(
        init(),
        result(is_error=True),
        error=ResultError("API Error", data={"subtype": "success"}, exit_code=1),
    )

    with pytest.raises(AgentRunFailed) as failure:
        await consume(session.stream(), Verdict)

    assert failure.value.reason == "api_error"
    assert failure.value.report == report("success")


async def test_a_success_without_structured_output_fails() -> None:
    session = ScriptedQuery(init(), result())

    with pytest.raises(AgentRunFailed) as failure:
        await consume(session.stream(), Verdict)

    assert failure.value.reason == "no_structured_output"
    assert failure.value.report == report("success")


async def test_a_structured_output_that_does_not_validate_fails() -> None:
    session = ScriptedQuery(init(), result(structured_output={"mood": "friendly"}))

    with pytest.raises(AgentRunFailed) as failure:
        await consume(session.stream(), Verdict)

    assert failure.value.reason == "invalid_structured_output"


async def test_a_process_that_fails_without_a_result_keeps_the_session_id() -> None:
    session = ScriptedQuery(init(), error=ProcessError("crashed", exit_code=137))

    with pytest.raises(AgentRunFailed) as failure:
        await consume(session.stream(), Verdict)

    assert failure.value.reason == "process_failed"
    assert failure.value.report == RunReport(session_id=SESSION_ID)


async def test_a_process_that_fails_after_a_success_keeps_its_report() -> None:
    session = ScriptedQuery(
        init(),
        result(structured_output={"tone": "friendly"}),
        error=ProcessError("crashed", exit_code=137),
    )

    with pytest.raises(AgentRunFailed) as failure:
        await consume(session.stream(), Verdict)

    assert failure.value.reason == "process_failed"
    assert failure.value.report == report("success")


async def test_a_session_that_ends_without_a_result_fails() -> None:
    session = ScriptedQuery(init())

    with pytest.raises(AgentRunFailed) as failure:
        await consume(session.stream(), Verdict)

    assert failure.value.reason == "no_result"
