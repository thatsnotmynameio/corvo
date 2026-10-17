# Lifted on this line alone, so the module's other imports keep every ban: it
# must not import the worker, which imports it.
from hatchet_sdk import ClientConfig, ClientTLSConfig, Hatchet  # noqa: TID251

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
