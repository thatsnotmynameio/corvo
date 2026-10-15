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
    # The socket of the rootless Podman that runs the agents' containers.
    # Empty, like an empty agent_root, leaves agents not configured.
    agent_podman_socket: str = ""
    # The directory each agent run's working and run directories live under.
    agent_root: str = ""
    # The agent image, built into that Podman's store with --target agent.
    agent_image: str = "localhost/corvo-agent:latest"
    # oauth_token: a `claude setup-token` token, which lasts a year. Anthropic's
    # terms allow it only for the subscriber's own ordinary use; a product or
    # service built on the Agent SDK must use an API key.
    agent_credential_kind: Literal["api_key", "oauth_token"] = "api_key"
    # The API key or the OAuth token itself. Empty disables agents.
    agent_credential: str = ""
    # Disable agents when their containers reach the gateway or the metadata
    # address, which the production nftables rule blocks.
    agent_require_egress_block: bool = False

    def agents_configured(self) -> bool:
        return bool(self.agent_podman_socket and self.agent_root)

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
