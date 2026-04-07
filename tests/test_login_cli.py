"""Tests for login CLI command and login_url site config support."""
from apt_scrape.sites import get_adapter


def test_immobiliare_has_login_url():
    """Immobiliare adapter config has a login_url field."""
    adapter = get_adapter("immobiliare")
    assert hasattr(adapter.config, "login_url")
    assert "immobiliare.it" in adapter.config.login_url


def test_casa_has_login_url():
    """Casa adapter config has a login_url field."""
    adapter = get_adapter("casa")
    assert hasattr(adapter.config, "login_url")
    assert "casa.it" in adapter.config.login_url


def test_idealista_has_login_url():
    """Idealista adapter config has a login_url field."""
    adapter = get_adapter("idealista")
    assert hasattr(adapter.config, "login_url")
    assert "idealista.it" in adapter.config.login_url
