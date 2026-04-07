"""Tests for apt_scrape.cookies — cookie persistence utilities."""
import json
from pathlib import Path

from apt_scrape.cookies import cookie_path


def test_cookie_path_default_identifier(tmp_path):
    """cookie_path returns data/cookies/{site_id}_{hash}.json with deterministic hash."""
    p = cookie_path("immobiliare", data_dir=tmp_path)
    assert p.parent == tmp_path / "cookies"
    assert p.name.startswith("immobiliare_")
    assert p.name.endswith(".json")
    # Default identifier "default" → same hash every time
    p2 = cookie_path("immobiliare", data_dir=tmp_path)
    assert p == p2


def test_cookie_path_custom_identifier(tmp_path):
    """Different identifiers produce different file paths."""
    p1 = cookie_path("immobiliare", identifier="alice@example.com", data_dir=tmp_path)
    p2 = cookie_path("immobiliare", identifier="bob@example.com", data_dir=tmp_path)
    assert p1 != p2
    assert p1.parent == p2.parent


from apt_scrape.cookies import save_cookies, load_cookies


SAMPLE_COOKIES = [
    {
        "name": "session_id",
        "value": "abc123",
        "domain": ".immobiliare.it",
        "path": "/",
        "expires": 9999999999,
        "httpOnly": True,
        "secure": True,
        "sameSite": "Lax",
    }
]


def test_save_and_load_cookies(tmp_path):
    """save_cookies writes JSON; load_cookies reads it back identically."""
    p = tmp_path / "cookies" / "test.json"
    save_cookies(SAMPLE_COOKIES, p)
    assert p.exists()
    loaded = load_cookies(p)
    assert loaded == SAMPLE_COOKIES


def test_load_cookies_missing_file(tmp_path):
    """load_cookies returns None when file does not exist."""
    p = tmp_path / "cookies" / "nonexistent.json"
    assert load_cookies(p) is None


def test_load_cookies_corrupted_file(tmp_path):
    """load_cookies returns None when file contains invalid JSON."""
    p = tmp_path / "cookies" / "bad.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json!", encoding="utf-8")
    assert load_cookies(p) is None
