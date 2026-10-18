from functools import cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    """The application's settings, read from CORVO_* environment variables.

    The defaults are a developer's machine.
    """

    model_config = SettingsConfigDict(env_prefix="CORVO_")

    # corvo-worker's root logger level. Hatchet forwards a task's log lines
    # at or above it to the run's log.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    postgres_user: str = "corvo"
    postgres_password: str = "corvo"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_database: str = "corvo"
    # The worker's Hatchet API token, which also holds the engine's address.
    hatchet_token: str = ""
    # none: the engine's gRPC has no TLS, as compose runs it.
    hatchet_tls_strategy: Literal["tls", "mtls", "none"] = "none"
    # The permission profile corvo-worker serves: main, or agents for the
    # agent worker. corvo.worker.profiles names each one.
    worker_profile: str = "main"
    # The name the worker registers under in Hatchet, in place of its
    # profile's, which tells apart two services on one profile.
    worker_name: str = ""
    # The directory the agents' working directories live under, in workdirs.
    agent_root: str = ""
    # Which Claude credential the proxy holds; corvo never holds it.
    # oauth_token: a `claude setup-token` token, which lasts a year. Anthropic's
    # terms allow it only for the subscriber's own ordinary use; a product or
    # service built on the Agent SDK must use an API key.
    agent_credential_kind: Literal["api_key", "oauth_token"] = "api_key"
    # The credential proxy, every session's ANTHROPIC_BASE_URL.
    agent_proxy_url: str = ""
    # The cgroup delegated to the agent worker, which holds each run's cgroup.
    agent_cgroup_root: str = "/sys/fs/cgroup/agents"
    # The engine every session runs; the agent-worker image sets it.
    agent_engine: str = ""

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
