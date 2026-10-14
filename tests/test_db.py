from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from corvo.dependencies import SessionDep
from corvo.main import create_app


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
