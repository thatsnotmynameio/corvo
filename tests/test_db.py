from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, SessionTransaction

from corvo.dependencies import SessionDep
from corvo.exceptions import ConflictError
from corvo.main import create_app


@pytest.fixture
def transactions() -> Iterator[list[str]]:
    """How each session's transaction ended: "commit" or "rollback"."""
    ended: list[str] = []

    def on_commit(session: Session) -> None:
        ended.append("commit")

    def on_rollback(session: Session, previous_transaction: SessionTransaction) -> None:
        if previous_transaction.parent is None:
            ended.append("rollback")

    event.listen(Session, "after_commit", on_commit)
    event.listen(Session, "after_soft_rollback", on_rollback)
    yield ended
    event.remove(Session, "after_commit", on_commit)
    event.remove(Session, "after_soft_rollback", on_rollback)


def test_each_request_gets_its_own_session() -> None:
    app = create_app()
    sessions: list[AsyncSession] = []

    @app.get("/session")
    async def session(session: SessionDep) -> None:
        sessions.append(session)

    with TestClient(app) as client:
        client.get("/session")
        client.get("/session")

    assert len(sessions) == 2
    assert all(isinstance(s, AsyncSession) for s in sessions)
    assert sessions[0] is not sessions[1]


def test_the_transaction_commits_when_the_route_returns(
    transactions: list[str],
) -> None:
    app = create_app()

    @app.post("/ok")
    async def ok(session: SessionDep) -> None:
        pass

    with TestClient(app) as client:
        response = client.post("/ok")

    assert response.status_code == 200
    assert transactions == ["commit"]


def test_the_transaction_rolls_back_when_the_route_raises(
    transactions: list[str],
) -> None:
    app = create_app()

    @app.post("/conflict")
    async def conflict(session: SessionDep) -> None:
        raise ConflictError("taken")

    with TestClient(app) as client:
        response = client.post("/conflict")

    assert response.status_code == 409
    assert transactions == ["rollback"]
