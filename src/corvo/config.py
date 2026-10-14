from functools import cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The application's settings, read from CORVO_* environment variables.

    The defaults are a developer's machine.
    """

    model_config = SettingsConfigDict(env_prefix="CORVO_")

    debug: bool = False
    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://corvo:corvo@localhost:5432/corvo"
    )


@cache
def get_settings() -> Settings:
    return Settings()
