import pytest

from corvo.agents.dir_summary.models import DirSummaryOutput
from corvo.agents.tone.models import ToneInput, ToneOutput
from corvo.worker import agent_calls
from corvo.worker.agent_calls import DirSummaryTaskInput
from corvo.worker.defaults import AGENT_WAITING_EXECUTION_TIMEOUT
from corvo.worker.workflows.dir_review import (
    DirReviewInput,
    DirReviewOutput,
    judge,
    summarize,
)

SUMMARY = DirSummaryOutput(summary="Two notes on a plan.", word_count=5)


class Replacement[In, Out]:
    """Stands in for a stub's aio_run, which would spawn a child run on
    Hatchet."""

    def __init__(self, output: Out) -> None:
        self.output = output
        self.received: list[In] = []

    async def __call__(self, input: In) -> Out:
        self.received.append(input)
        return self.output


async def test_summarize_spawns_dir_summary_on_the_workdir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = Replacement[DirSummaryTaskInput, DirSummaryOutput](SUMMARY)
    monkeypatch.setattr(agent_calls.dir_summary, "aio_run", replacement)

    output = await summarize.aio_mock_run(DirReviewInput(workdir="review-1"))

    assert output == SUMMARY
    assert replacement.received == [DirSummaryTaskInput(workdir="review-1")]


async def test_judge_spawns_tone_on_the_summary_and_reviews_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = Replacement[ToneInput, ToneOutput](
        ToneOutput(tone="neutral", friendly=False)
    )
    monkeypatch.setattr(agent_calls.tone, "aio_run", replacement)

    output = await judge.aio_mock_run(
        DirReviewInput(workdir="review-1"),
        parent_outputs={"summarize": SUMMARY.model_dump()},
    )

    assert output == DirReviewOutput(review="A neutral summary, 5 words long.")
    assert replacement.received == [ToneInput(text="Two notes on a plan.")]


def test_steps_that_wait_on_an_agent_do_not_retry() -> None:
    for step in (summarize, judge):
        assert step.retries == 0
        assert step.execution_timeout == AGENT_WAITING_EXECUTION_TIMEOUT
