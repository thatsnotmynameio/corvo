from corvo.settings import get_settings
from corvo.vendors.hatchet.client import hatchet


def test_the_client_takes_the_token_from_corvo_settings() -> None:
    assert hatchet.config.token == get_settings().hatchet_token


def test_the_client_takes_the_tls_strategy_from_corvo_settings() -> None:
    # corvo's default, none, is not Hatchet's, tls.
    assert hatchet.config.tls_config.strategy == get_settings().hatchet_tls_strategy
