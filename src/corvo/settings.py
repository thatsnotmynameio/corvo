"""corvo's settings, read from CORVO_* environment variables.

Environment, the database settings from sqlalchemy_debug to
database_connect_timeout_seconds, get_postgres_dsn(driver) and the is_*
checks come from Polar's server/polar/config.py, at polarsource/polar
10fc4889db1f97e52bf67b74df567dbdea299267: Copyright 2023 Polar Software Inc,
under the Apache License 2.0 in polar.LICENSE. corvo changed them: the names
are lower case, CORVO_ENV sets the environment, Environment keeps only
development, testing and production, and get_postgres_dsn has no fallback
host.
"""

from enum import StrEnum
from functools import cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Environment(StrEnum):
    development = "development"
    testing = "testing"  # Used for running tests
    production = "production"


class Settings(BaseSettings):
    """The application's settings, read from CORVO_* environment variables.

    The defaults are a developer's machine.
    """

    model_config = SettingsConfigDict(env_prefix="CORVO_")

    # The environment a process runs in. corvo.postgres puts it in each
    # database connection's application_name.
    env: Environment = Environment.development
    # corvo-worker's root logger level. Hatchet forwards a task's log lines
    # at or above it to the run's log.
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    postgres_user: str = "corvo"
    postgres_password: str = "corvo"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_database: str = "corvo"
    # SQLAlchemy logs every statement it runs.
    sqlalchemy_debug: bool = False
    # The connections require TLS.
    postgres_ssl: bool = False
    # The engine's pool: the connections it keeps open, and the age, in
    # seconds, past which it replaces one.
    database_pool_size: int = 5
    database_pool_recycle_seconds: int = 600  # 10 minutes
    # How long a statement may run, and a connection may take to open.
    database_command_timeout_seconds: float = 30.0
    database_connect_timeout_seconds: float = 10.0
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

    def get_postgres_dsn(self, driver: Literal["asyncpg", "psycopg2"]) -> str:
        # URL.create escapes the password.
        return URL.create(
            f"postgresql+{driver}",
            username=self.postgres_user,
            password=self.postgres_password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_database,
        ).render_as_string(hide_password=False)

    def is_environment(self, environments: set[Environment]) -> bool:
        return self.env in environments

    def is_development(self) -> bool:
        return self.is_environment({Environment.development})

    def is_testing(self) -> bool:
        return self.is_environment({Environment.testing})

    def is_production(self) -> bool:
        return self.is_environment({Environment.production})


@cache
def get_settings() -> Settings:
    return Settings()
