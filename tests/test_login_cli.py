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


from click.testing import CliRunner
from apt_scrape.cli import cli


def test_login_command_exists():
    """The 'login' command is registered on the CLI group."""
    runner = CliRunner()
    result = runner.invoke(cli, ["login", "--help"])
    assert result.exit_code == 0
    assert "--site" in result.output
    assert "--identifier" in result.output


def test_login_rejects_unknown_site():
    """Login command fails with a clear error for an unknown site."""
    runner = CliRunner()
    result = runner.invoke(cli, ["login", "--site", "fakeSite99"])
    assert result.exit_code != 0
    assert "fakeSite99" in result.output or "fakeSite99" in (result.exception and str(result.exception) or "")


from unittest.mock import AsyncMock, patch, MagicMock


def test_login_saves_cookies(tmp_path):
    """Login command extracts cookies from browser context and saves them."""
    fake_cookies = [
        {"name": "sid", "value": "abc", "domain": ".immobiliare.it",
         "path": "/", "expires": 9999999999, "httpOnly": True,
         "secure": True, "sameSite": "Lax"}
    ]

    mock_context = AsyncMock()
    mock_context.cookies = AsyncMock(return_value=fake_cookies)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    mock_camoufox_instance = AsyncMock()
    mock_camoufox_instance.__aenter__ = AsyncMock(return_value=mock_browser)
    mock_camoufox_instance.__aexit__ = AsyncMock(return_value=False)

    with patch("apt_scrape.cli.AsyncCamoufox", return_value=mock_camoufox_instance), \
         patch("apt_scrape.cli._DEFAULT_DATA_DIR", tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["login", "--site", "immobiliare"], input="\n")

    assert result.exit_code == 0, f"CLI failed: {result.output}"
    # Verify cookies were saved
    from apt_scrape.cookies import cookie_path
    p = cookie_path("immobiliare", data_dir=tmp_path)
    assert p.exists()
    import json
    saved = json.loads(p.read_text())
    assert saved == fake_cookies
