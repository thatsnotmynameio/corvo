import json
import os
from collections.abc import AsyncIterator, Iterator
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql import column, table

from corvo import postgres
from corvo.settings import get_settings

# The prefixes of the variables create_async_engine reads, besides CORVO_ENV.
ENGINE_SETTINGS = ("CORVO_POSTGRES_", "CORVO_DATABASE_", "CORVO_SQLALCHEMY_")


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The engine's settings at their defaults, whatever the shell exports."""
    for name in list(os.environ):
        if name == "CORVO_ENV" or name.startswith(ENGINE_SETTINGS):
            monkeypatch.delenv(name)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def engine_arguments(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """What create_async_engine passes SQLAlchemy, which builds no engine."""
    recorded: dict[str, Any] = {}

    def record(url: str, **kwargs: Any) -> None:
        recorded.update(kwargs, url=url)

    monkeypatch.setattr(postgres, "_create_async_engine", record)
    return recorded


def test_the_engine_is_configured_from_the_settings(
    engine_arguments: dict[str, Any],
) -> None:
    postgres.create_async_engine("worker")

    assert engine_arguments["url"] == get_settings().get_postgres_dsn("asyncpg")
    assert engine_arguments["connect_args"] == {
        "prepared_statement_cache_size": 0,
        "server_settings": {"application_name": "development.worker"},
        "command_timeout": 30.0,
        "timeout": 10.0,
    }
    assert engine_arguments["pool_size"] == 5
    assert engine_arguments["pool_recycle"] == 600
    assert engine_arguments["pool_pre_ping"] is False
    assert engine_arguments["pool_logging_name"] == "worker"
    assert engine_arguments["echo"] is False
    assert engine_arguments["query_cache_size"] == 128


def test_the_application_name_carries_the_environment(
    monkeypatch: pytest.MonkeyPatch, engine_arguments: dict[str, Any]
) -> None:
    monkeypatch.setenv("CORVO_ENV", "production")

    postgres.create_async_engine("worker")

    server_settings = engine_arguments["connect_args"]["server_settings"]
    assert server_settings == {"application_name": "production.worker"}


def test_ssl_is_required_when_the_settings_ask_for_it(
    monkeypatch: pytest.MonkeyPatch, engine_arguments: dict[str, Any]
) -> None:
    monkeypatch.setenv("CORVO_POSTGRES_SSL", "true")

    postgres.create_async_engine("worker")

    assert engine_arguments["connect_args"]["ssl"] == "require"


def test_ssl_is_left_to_the_driver_by_default(
    engine_arguments: dict[str, Any],
) -> None:
    postgres.create_async_engine("worker")

    assert "ssl" not in engine_arguments["connect_args"]


def test_the_sqlalchemy_debug_setting_echoes_the_statements(
    monkeypatch: pytest.MonkeyPatch, engine_arguments: dict[str, Any]
) -> None:
    monkeypatch.setenv("CORVO_SQLALCHEMY_DEBUG", "true")

    postgres.create_async_engine("worker")

    assert engine_arguments["echo"] is True


def test_the_caller_sets_the_pool_logging_name_and_pre_ping(
    engine_arguments: dict[str, Any],
) -> None:
    postgres.create_async_engine(
        "worker", pool_logging_name="worker_events", pool_pre_ping=True
    )

    assert engine_arguments["pool_logging_name"] == "worker_events"
    assert engine_arguments["pool_pre_ping"] is True


def test_the_json_serializer_writes_a_decimal_as_a_number(
    engine_arguments: dict[str, Any],
) -> None:
    postgres.create_async_engine("worker")
    serialize = engine_arguments["json_serializer"]

    assert json.loads(serialize({"amount": Decimal("1.5")})) == {"amount": 1.5}

    with pytest.raises(TypeError, match="not JSON serializable"):
        serialize({"value": object()})


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    """A real engine, which opens no connection until a query runs."""
    engine = postgres.create_async_engine("worker")
    yield engine
    await engine.dispose()


def test_a_real_engine_takes_the_settings_pool_size_and_echo(
    engine: AsyncEngine,
) -> None:
    assert engine.pool.size() == 5  # type: ignore[attr-defined]
    assert engine.echo is False


async def test_the_sessions_keep_their_objects_after_a_commit(
    engine: AsyncEngine,
) -> None:
    sessionmaker = postgres.create_async_sessionmaker(engine)

    async with sessionmaker() as session:
        assert session.sync_session.expire_on_commit is False


def test_insert_builds_postgresql_s_insert() -> None:
    statement = postgres.insert(table("t", column("id"))).values(id=1)

    sql = statement.on_conflict_do_nothing().compile(dialect=postgresql.dialect())

    assert str(sql).endswith("ON CONFLICT DO NOTHING")
