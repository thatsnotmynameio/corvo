from hatchet_sdk import ClientConfig, ClientTLSConfig, Hatchet

from corvo.settings import get_settings

# The client the tasks are declared on and the worker runs, as in Hatchet's
# Python quickstart. Its settings come from corvo's, as the database's do; the
# engine's address comes from the token.
hatchet = Hatchet(
    config=ClientConfig(
        token=get_settings().hatchet_token,
        tls_config=ClientTLSConfig(strategy=get_settings().hatchet_tls_strategy),
    )
)
