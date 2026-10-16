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


def test_the_cgroup_root_defaults_to_the_delegated_agents_cgroup() -> None:
    assert Settings().agent_cgroup_root == "/sys/fs/cgroup/agents"


def test_the_settings_hold_no_credential() -> None:
    with pytest.raises(ValidationError, match="agent_credential"):
        Settings(agent_credential="sk-ant-real")  # type: ignore[call-arg]


def test_the_worker_profile_defaults_to_main() -> None:
    assert Settings().worker_profile == "main"


def test_the_worker_profile_reads_its_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORVO_WORKER_PROFILE", "agents")

    assert Settings().worker_profile == "agents"


def test_the_log_level_defaults_to_info() -> None:
    assert Settings().log_level == "INFO"


def test_the_log_level_reads_its_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORVO_LOG_LEVEL", "DEBUG")

    assert Settings().log_level == "DEBUG"


def test_the_log_level_rejects_an_unknown_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CORVO_LOG_LEVEL", "TRACE")

    with pytest.raises(ValidationError, match="log_level"):
        Settings()
