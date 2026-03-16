"""apt_scrape.sites.casa — Adapter for Casa.it.

Config: ``apt_scrape/sites/configs/casa.yaml``

Casa.it uses a single search endpoint ``/srp/`` with all filters as query
parameters.  Location is encoded as a short hash in the ``q=`` parameter
(e.g. ``q=85ba3e0b`` for the Bicocca zone).

The old path-based URL pattern ``/affitto/residenziale/milano/{zone}/``
renders a page that **does not apply filters** — only the ``/srp/`` endpoint
with the correct ``q=`` hash actually returns filtered results.

Zone hashes are stored in the ``area_map`` config key.  A ``city_hash``
key provides the city-wide fallback (Milano = ``9f6485c2``).
"""

from pathlib import Path
from urllib.parse import urlencode

import yaml

from .base import SearchFilters, SiteAdapter, SiteConfig, load_config_from_yaml

_CONFIG_PATH = Path(__file__).parent / "configs" / "casa.yaml"


class CasaAdapter(SiteAdapter):
    """Adapter for Casa.it — Italy's oldest real estate portal (est. 1996).

    Overrides ``build_search_url`` to construct the ``/srp/`` endpoint URL
    with the correct zone hash (``q=``) and query parameter names, which
    differ entirely from the display-only path-based URLs.
    """

    def __init__(self, config: SiteConfig | None = None) -> None:
        if config is None:
            config = load_config_from_yaml(_CONFIG_PATH)
        super().__init__(config)
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            raw_config = yaml.safe_load(fh)
        # Maps our area slugs → Casa.it zone hashes (for the q= parameter).
        self.area_map: dict[str, str] = raw_config.get("area_map", {})
        # City-wide hash used when no area slug is provided.
        self.city_hash: str = raw_config.get("city_hash", "9f6485c2")

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build a Casa.it ``/srp/`` search URL with zone hash and filters.

        Translates the normalised operation/property-type slugs and area slug
        into the parameters expected by Casa.it's ``/srp/`` endpoint.

        Example output:
            https://www.casa.it/srp/?tr=affitti&propertyTypeGroup=case&q=85ba3e0b&priceMin=700&priceMax=1400&mqMin=40&numRoomsMin=2&page=1
        """
        op = self.config.operation_map.get(filters.operation, filters.operation)
        pt = self.config.property_type_map.get(filters.property_type, "case")

        # Resolve location hash — fall back to city-wide if slug not in map.
        area_hash = self.city_hash
        if filters.area:
            area_hash = self.area_map.get(filters.area, self.city_hash)

        query: dict = {
            "tr": op,
            "propertyTypeGroup": pt,
            "q": area_hash,
            "sortType": "relevance",
        }

        qmap = self.config.query_param_map
        if filters.min_price is not None and "min_price" in qmap:
            query[qmap["min_price"]] = filters.min_price
        if filters.max_price is not None and "max_price" in qmap:
            query[qmap["max_price"]] = filters.max_price
        if filters.min_sqm is not None and "min_sqm" in qmap:
            query[qmap["min_sqm"]] = filters.min_sqm
        if filters.max_sqm is not None and "max_sqm" in qmap:
            query[qmap["max_sqm"]] = filters.max_sqm
        if filters.min_rooms is not None and "min_rooms" in qmap:
            query[qmap["min_rooms"]] = filters.min_rooms
        if filters.max_rooms is not None and "max_rooms" in qmap:
            query[qmap["max_rooms"]] = filters.max_rooms

        query[self.config.page_param] = filters.page

        return self.config.base_url + "/srp/?" + urlencode(query)
