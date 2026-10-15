import pytest
from pydantic import ValidationError

from corvo.agents.envelope import ENVELOPE, Failed, RunReport, Succeeded

REPORT = RunReport(
    subtype="success", num_turns=2, total_cost_usd=0.0042, session_id="s-1"
)


def test_an_ok_envelope_reads_back_with_its_output_and_report() -> None:
    sent = Succeeded(output={"tone": "friendly", "friendly": True}, report=REPORT)

    received = ENVELOPE.validate_json(sent.model_dump_json())

    assert received == sent


def test_a_failed_envelope_reads_back_with_its_reason_and_report() -> None:
    sent = Failed(reason="error_max_turns", report=REPORT)

    received = ENVELOPE.validate_json(sent.model_dump_json())

    assert received == sent


def test_an_envelope_of_another_protocol_is_rejected() -> None:
    other = '{"protocol": 2, "status": "failed", "reason": "deadline", "report": {}}'

    with pytest.raises(ValidationError, match="protocol"):
        ENVELOPE.validate_json(other)
