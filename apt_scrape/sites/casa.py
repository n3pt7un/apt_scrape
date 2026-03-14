"""apt_scrape.sites.casa — Adapter for Casa.it.

Config: ``apt_scrape/sites/configs/casa.yaml``

Casa.it uses a path-based URL format for location filtering:

    /affitto/residenziale/milano/{zone-slug}/?prezzoMax=X&prezzoMin=Y&...

Neighbourhoods are grouped into macro-zones on Casa.it (e.g. Bicocca,
Niguarda and Ca' Granda all fall under ``bicocca-ca-granda-parco-nord``).
The ``area_map`` in the YAML config translates our normalised area slugs
(``bicocca``, ``niguarda``, etc.) into the correct zone path segment.
"""

import dataclasses
from pathlib import Path

import yaml

from .base import SearchFilters, SiteAdapter, SiteConfig, load_config_from_yaml

_CONFIG_PATH = Path(__file__).parent / "configs" / "casa.yaml"


class CasaAdapter(SiteAdapter):
    """Adapter for Casa.it — Italy's oldest real estate portal (est. 1996).

    Overrides ``build_search_url`` only to translate the normalised area slug
    (e.g. ``"bicocca"``) into Casa.it's zone path segment
    (e.g. ``"bicocca-ca-granda-parco-nord"``), then delegates to the
    standard base-class implementation which builds the path + query string.
    """

    def __init__(self, config: SiteConfig | None = None) -> None:
        if config is None:
            config = load_config_from_yaml(_CONFIG_PATH)
        super().__init__(config)
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            raw_config = yaml.safe_load(fh)
        # Maps our area slugs → Casa.it zone path segments.
        self.area_map: dict[str, str] = raw_config.get("area_map", {})

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build a Casa.it search URL, translating the area slug first.

        Casa.it uses grouped zone slugs (e.g. precotto, turro and greco all
        map to ``gorla-greco-precotto``).  We look up the normalised slug in
        ``area_map`` and pass the translated value to the base implementation.

        Example output:
            https://www.casa.it/affitto/residenziale/milano/bicocca-ca-granda-parco-nord/?prezzoMax=1400&prezzoMin=700&superficieMin=50&numLocaliMin=2&page=1
        """
        if filters.area:
            zone = self.area_map.get(filters.area, filters.area)
            filters = dataclasses.replace(filters, area=zone)
        return super().build_search_url(filters)
