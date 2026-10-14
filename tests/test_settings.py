import pytest
from sqlalchemy import make_url

from corvo.settings import Settings


def test_postgres_dsn_joins_the_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORVO_POSTGRES_USER", "app")
    monkeypatch.setenv("CORVO_POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("CORVO_POSTGRES_HOST", "db")
    monkeypatch.setenv("CORVO_POSTGRES_PORT", "6543")
    monkeypatch.setenv("CORVO_POSTGRES_DATABASE", "prod")

    dsn = Settings().get_postgres_dsn()

    assert dsn == "postgresql+asyncpg://app:secret@db:6543/prod"


def test_postgres_dsn_escapes_the_password() -> None:
    password = "p@ss/w:rd#?"

    url = make_url(Settings(postgres_password=password).get_postgres_dsn())

    assert url.password == password
    assert url.host == "localhost"
