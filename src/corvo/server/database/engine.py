from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(url)


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # An object stays readable after a commit: reloading it would be an
    # implicit query, which async code cannot run.
    return async_sessionmaker(engine, expire_on_commit=False)
