"""apt_scrape.cookies — Session cookie persistence for authenticated site access.

Cookies are stored as Playwright-format JSON arrays in:
    data/cookies/{site_id}_{hash}.json

The hash is derived from site_id + identifier to support multiple accounts per site
without storing PII in filenames.
"""
import hashlib
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))


def _make_hash(site_id: str, identifier: str) -> str:
    """Return first 8 hex chars of SHA-256(site_id + identifier)."""
    return hashlib.sha256(f"{site_id}:{identifier}".encode()).hexdigest()[:8]


def cookie_path(
    site_id: str,
    identifier: str = "default",
    data_dir: Path | None = None,
) -> Path:
    """Return the cookie file path for a site/identifier combo.

    Args:
        site_id: Site slug (e.g. "immobiliare").
        identifier: User-provided label (e.g. email) to disambiguate accounts.
        data_dir: Base data directory. Defaults to DATA_DIR env var or "data".

    Returns:
        Path like ``data/cookies/immobiliare_a1b2c3d4.json``.
    """
    base = data_dir if data_dir is not None else _DEFAULT_DATA_DIR
    return base / "cookies" / f"{site_id}_{_make_hash(site_id, identifier)}.json"


def save_cookies(cookies: list[dict], path: Path) -> None:
    """Write Playwright-format cookies to a JSON file.

    Creates parent directories if they don't exist.

    Args:
        cookies: List of cookie dicts (from ``context.cookies()``).
        path: Destination file path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
    logger.info("Saved %d cookies to %s", len(cookies), path)


def load_cookies(path: Path) -> list[dict] | None:
    """Read cookies from a JSON file.

    Args:
        path: Cookie file path.

    Returns:
        List of cookie dicts, or ``None`` if the file is missing or unreadable.
    """
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            logger.warning("Cookie file %s does not contain a list", path)
            return None
        return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load cookies from %s: %s", path, exc)
        return None
