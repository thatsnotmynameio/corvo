from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# Constraints get predictable names, so a migration can alter or drop them by
# name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """The base of every ORM model. Alembic compares the database with it."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # An object stays readable after a commit: reloading it would be an
    # implicit query, which async code cannot run.
    return async_sessionmaker(engine, expire_on_commit=False)
