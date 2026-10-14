from functools import cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """The application's settings, read from CORVO_* environment variables.

    The defaults are a developer's machine.
    """

    model_config = SettingsConfigDict(env_prefix="CORVO_")

    debug: bool = False
    postgres_user: str = "corvo"
    postgres_password: str = "corvo"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_database: str = "corvo"
    # The worker's Hatchet API token, which also holds the engine's address.
    hatchet_token: str = ""
    # none: the engine's gRPC has no TLS, as compose runs it.
    hatchet_tls_strategy: Literal["tls", "mtls", "none"] = "none"

    def get_postgres_dsn(self) -> str:
        # Built as Polar builds it: URL.create escapes the password.
        return URL.create(
            "postgresql+asyncpg",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
        ).render_as_string(hide_password=False)


@cache
def get_settings() -> Settings:
    return Settings()
