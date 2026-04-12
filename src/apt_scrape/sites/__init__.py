"""apt_scrape.sites — Site adapter registry.

All registered adapters are available via the following helpers:

    get_adapter(site_id)        → look up by slug (e.g. "immobiliare")
    adapter_for_url(url)        → auto-detect site from a listing URL
    list_adapters()             → all registered site IDs
    list_adapter_details()      → metadata dicts for all adapters
    ADAPTERS                    → the full list of adapter instances

To add a new site:
    1. Copy ``templates/new_site_adapter.py`` to ``apt_scrape/sites/your_site.py``.
    2. Implement a ``SiteAdapter`` subclass.
    3. Import and append the adapter class to ``ADAPTERS`` below.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .base import (
    ClassifyResult,
    DetailSelectors,
    ListingDetail,
    ListingSummary,
    SearchFilters,
    SearchSelectors,
    SelectorGroup,
    SiteAdapter,
    SiteConfig,
    classify_feature,
    config_from_dict,
    config_to_dict,
    deep_merge,
    extract_attr,
    extract_text,
)
from .casa import CasaAdapter
from .idealista import IdealistaAdapter
from .immobiliare import ImmobiliareAdapter
from .tecnocasa import TecnocasaAdapter

__all__ = [
    "ADAPTERS",
    "ClassifyResult",
    "DetailSelectors",
    "ListingDetail",
    "ListingSummary",
    "SearchFilters",
    "SearchSelectors",
    "SelectorGroup",
    "SiteAdapter",
    "SiteConfig",
    "adapter_for_url",
    "classify_feature",
    "config_to_dict",
    "deep_merge",
    "extract_attr",
    "extract_text",
    "get_adapter",
    "get_adapter_with_overrides",
    "get_config_path",
    "list_adapter_details",
    "list_adapters",
]

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

# Order matters for URL matching — first match wins.
ADAPTERS: list[SiteAdapter] = [
    ImmobiliareAdapter(),
    CasaAdapter(),
    IdealistaAdapter(),
    TecnocasaAdapter(),
]

_BY_ID: dict[str, SiteAdapter] = {a.site_id: a for a in ADAPTERS}

# For get_adapter_with_overrides: site_id -> (adapter_class, config_path)
_PACKAGE_DIR = Path(__file__).resolve().parent
_CONFIG_PATHS: dict[str, tuple[type[SiteAdapter], str]] = {
    "immobiliare": (ImmobiliareAdapter, str(_PACKAGE_DIR / "configs" / "immobiliare.yaml")),
    "casa": (CasaAdapter, str(_PACKAGE_DIR / "configs" / "casa.yaml")),
    "idealista": (IdealistaAdapter, str(_PACKAGE_DIR / "configs" / "idealista.yaml")),
    "tecnocasa": (TecnocasaAdapter, str(_PACKAGE_DIR / "configs" / "tecnocasa.yaml")),
}


def get_adapter(site_id: str) -> SiteAdapter:
    """Return the adapter registered under *site_id*.

    Args:
        site_id: The short slug identifying the site (e.g. ``"immobiliare"``).

    Returns:
        The matching ``SiteAdapter`` instance.

    Raises:
        KeyError: If no adapter is registered under *site_id*.
    """
    if site_id not in _BY_ID:
        available = ", ".join(sorted(_BY_ID.keys()))
        raise KeyError(f"Unknown site '{site_id}'. Available: {available}")
    return _BY_ID[site_id]


def adapter_for_url(url: str) -> SiteAdapter | None:
    """Auto-detect the right adapter for a given listing URL.

    Args:
        url: Full URL of a listing or search page.

    Returns:
        The first adapter whose ``domain_pattern`` matches *url*, or ``None``
        if no adapter matches.
    """
    for adapter in ADAPTERS:
        if adapter.matches_url(url):
            return adapter
    return None


def list_adapters() -> list[str]:
    """Return all registered site IDs.

    Returns:
        List of site ID strings (e.g. ``["immobiliare", "casa"]``).
    """
    return [a.site_id for a in ADAPTERS]


def get_config_path(site_id: str) -> str:
    """Return the path to the YAML config file for the given site."""
    if site_id not in _CONFIG_PATHS:
        raise KeyError(f"Unknown site '{site_id}'")
    return _CONFIG_PATHS[site_id][1]


def get_adapter_with_overrides(site_id: str, overrides: dict | None = None) -> SiteAdapter:
    """Return an adapter with optional config overrides merged on top of the base YAML config.

    If overrides is None or empty, returns the same as get_adapter(site_id).
    Otherwise loads the base config dict from the site's YAML, deep_merges overrides,
    builds a SiteConfig, and returns a new adapter instance with that config.
    """
    if not overrides:
        return get_adapter(site_id)
    if site_id not in _BY_ID:
        available = ", ".join(sorted(_BY_ID.keys()))
        raise KeyError(f"Unknown site '{site_id}'. Available: {available}")
    adapter_class, config_path = _CONFIG_PATHS[site_id]
    with open(config_path, encoding="utf-8") as fh:
        base_dict = yaml.safe_load(fh)
    merged = deep_merge(base_dict, overrides)
    config = config_from_dict(merged)
    return adapter_class(config)


def list_adapter_details() -> list[dict[str, str]]:
    """Return metadata dicts for all registered adapters.

    Returns:
        List of dicts, each containing ``site_id``, ``display_name``, and
        ``base_url`` for one adapter.
    """
    return [
        {
            "site_id": a.site_id,
            "display_name": a.config.display_name,
            "base_url": a.config.base_url,
        }
        for a in ADAPTERS
    ]
