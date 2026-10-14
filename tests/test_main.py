import pytest
from fastapi.testclient import TestClient

from corvo.exceptions import ConflictError, CorvoError, NotFoundError
from corvo.main import create_app


def test_health() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (NotFoundError("no such thing"), 404),
        (ConflictError("no such thing"), 409),
        (CorvoError("no such thing"), 400),
    ],
)
def test_business_errors_map_to_http_status(
    error: CorvoError, status_code: int
) -> None:
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise error

    response = TestClient(app).get("/boom")

    assert response.status_code == status_code
    assert response.json() == {
        "error": type(error).__name__,
        "detail": "no such thing",
    }
