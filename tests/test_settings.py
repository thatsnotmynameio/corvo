import pytest
from pydantic import ValidationError
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


def test_the_credential_kind_reads_oauth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORVO_AGENT_CREDENTIAL_KIND", "oauth_token")

    assert Settings().agent_credential_kind == "oauth_token"


def test_the_credential_kind_rejects_an_unknown_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORVO_AGENT_CREDENTIAL_KIND", "token")

    with pytest.raises(ValidationError, match="agent_credential_kind"):
        Settings()


def test_agents_are_not_configured_without_their_variables() -> None:
    assert not Settings().agents_configured()


@pytest.mark.parametrize(
    ("socket", "root", "configured"),
    [
        ("/run/corvo/podman.sock", "", False),
        ("", "/srv/corvo/agents", False),
        ("/run/corvo/podman.sock", "/srv/corvo/agents", True),
    ],
)
def test_agents_are_configured_by_the_socket_and_the_root(
    socket: str, root: str, configured: bool
) -> None:
    settings = Settings(agent_podman_socket=socket, agent_root=root)

    assert settings.agents_configured() is configured
