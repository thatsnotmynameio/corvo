"""corvo's PostgreSQL engine, configured from its settings the way Polar's is.

This module merges three files of polarsource/polar, at
10fc4889db1f97e52bf67b74df567dbdea299267: server/polar/postgres.py,
server/polar/kit/db/postgres.py and server/polar/kit/extensions/sqlalchemy/
sql.py. Copyright 2023 Polar Software Inc, under the Apache License 2.0 in
polar.LICENSE.

corvo changed them:

- the three files are one module, and the sql names are its own;
- the kit's engine factory is private, as _kit_create_async_engine;
- the read-replica and sync engines, their sessionmakers, the
  AsyncReadSession and AsyncSession types and the FastAPI dependencies are
  left out, and the sessions are SQLAlchemy's AsyncSession;
- the settings are read through get_settings();
- ProcessName is worker alone.
"""

import json
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio import (
    create_async_engine as _create_async_engine,
)
from sqlalchemy.sql import Delete, Select, Update, delete, func, select, update
from sqlalchemy.sql.base import ExecutableOption

from corvo.settings import get_settings

Insert = postgresql.Insert
insert = postgresql.insert

type ProcessName = Literal["worker"]


def _json_obj_serializer(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def json_serializer(obj: Any) -> str:
    return json.dumps(obj, default=_json_obj_serializer)


def _kit_create_async_engine(
    *,
    dsn: str,
    application_name: str | None = None,
    pool_logging_name: str | None = None,
    pool_size: int | None = None,
    pool_recycle: int | None = None,
    pool_pre_ping: bool = False,
    command_timeout: float | None = None,
    connect_timeout: float | None = None,
    debug: bool = False,
    ssl: str | None = None,
) -> AsyncEngine:
    connect_args: dict[str, Any] = {"prepared_statement_cache_size": 0}
    if application_name is not None:
        connect_args["server_settings"] = {"application_name": application_name}
    if command_timeout is not None:
        connect_args["command_timeout"] = command_timeout
    if connect_timeout is not None:
        connect_args["timeout"] = connect_timeout
    if ssl is not None:
        connect_args["ssl"] = ssl

    return _create_async_engine(
        dsn,
        echo=debug,
        connect_args=connect_args,
        pool_size=pool_size,
        pool_recycle=pool_recycle,
        pool_pre_ping=pool_pre_ping,
        pool_logging_name=pool_logging_name,
        json_serializer=json_serializer,
        query_cache_size=128,
    )


type AsyncSessionMaker = async_sessionmaker[AsyncSession]


def create_async_sessionmaker(engine: AsyncEngine) -> AsyncSessionMaker:
    return async_sessionmaker(engine, expire_on_commit=False)


def create_async_engine(
    process_name: ProcessName,
    *,
    pool_logging_name: str | None = None,
    pool_pre_ping: bool = False,
) -> AsyncEngine:
    settings = get_settings()
    return _kit_create_async_engine(
        dsn=str(settings.get_postgres_dsn("asyncpg")),
        application_name=f"{settings.env.value}.{process_name}",
        pool_logging_name=pool_logging_name or process_name,
        debug=settings.sqlalchemy_debug,
        pool_size=settings.database_pool_size,
        pool_recycle=settings.database_pool_recycle_seconds,
        pool_pre_ping=pool_pre_ping,
        command_timeout=settings.database_command_timeout_seconds,
        connect_timeout=settings.database_connect_timeout_seconds,
        ssl="require" if settings.postgres_ssl else None,
    )


__all__ = [
    "AsyncEngine",
    "AsyncSession",
    "AsyncSessionMaker",
    "Delete",
    "ExecutableOption",
    "Insert",
    "ProcessName",
    "Select",
    "Update",
    "create_async_engine",
    "create_async_sessionmaker",
    "delete",
    "func",
    "insert",
    "select",
    "update",
]
