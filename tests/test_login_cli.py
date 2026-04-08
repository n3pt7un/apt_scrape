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


import json
import os
import sqlite3
from unittest.mock import patch, MagicMock


def _create_fake_chrome_cookies(profile_dir, cookies):
    """Create a fake Chrome cookie SQLite database in a temp profile."""
    cookie_dir = os.path.join(profile_dir, "Default", "Network")
    os.makedirs(cookie_dir, exist_ok=True)
    db_path = os.path.join(cookie_dir, "Cookies")
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE cookies ("
        "name TEXT, value TEXT, host_key TEXT, path TEXT, "
        "expires_utc INTEGER, is_httponly INTEGER, is_secure INTEGER, "
        "samesite INTEGER)"
    )
    for c in cookies:
        conn.execute(
            "INSERT INTO cookies VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (c["name"], c["value"], c["domain"], c["path"],
             c["expires_utc"], c["httpOnly"], c["secure"], c["samesite"]),
        )
    conn.commit()
    conn.close()


def test_login_saves_cookies(tmp_path):
    """Login command reads cookies from Chrome's SQLite DB and saves them."""
    profile_dir = str(tmp_path / "chrome_profile")
    _create_fake_chrome_cookies(profile_dir, [
        {"name": "sid", "value": "abc", "domain": ".immobiliare.it",
         "path": "/", "expires_utc": 13370000000000000,
         "httpOnly": 1, "secure": 1, "samesite": 1},
    ])

    mock_proc = MagicMock()
    mock_proc.wait = MagicMock(return_value=0)

    data_dir = tmp_path / "data"

    with patch("apt_scrape.cli._find_chrome", return_value="/usr/bin/google-chrome"), \
         patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("tempfile.mkdtemp", return_value=profile_dir), \
         patch("apt_scrape.cli._DEFAULT_DATA_DIR", data_dir):
        runner = CliRunner()
        result = runner.invoke(cli, ["login", "--site", "immobiliare"], input="\n")

    assert result.exit_code == 0, f"CLI failed: {result.output}\n{result.exception}"
    # Verify cookies were saved
    from apt_scrape.cookies import cookie_path
    p = cookie_path("immobiliare", data_dir=data_dir)
    assert p.exists()
    saved = json.loads(p.read_text())
    assert len(saved) == 1
    assert saved[0]["name"] == "sid"
    assert saved[0]["value"] == "abc"
    assert saved[0]["domain"] == ".immobiliare.it"
    assert saved[0]["httpOnly"] is True
    assert saved[0]["sameSite"] == "Lax"
