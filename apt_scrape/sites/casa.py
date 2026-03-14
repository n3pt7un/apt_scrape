"""apt_scrape.sites.casa — Adapter for Casa.it.

Config: ``apt_scrape/sites/configs/casa.yaml``

Casa.it's current UI uses a single `/srp/` endpoint with an opaque `q` code
for locations (neighborhoods or combined zones). This adapter overrides
``build_search_url`` to translate our normalized ``city``/``area`` filters
into the appropriate `q` value where known, falling back gracefully when a
mapping is missing.
"""

from pathlib import Path
from urllib.parse import urlencode

from .base import SearchFilters, SiteAdapter, SiteConfig, load_config_from_yaml

_CONFIG_PATH = Path(__file__).parent / "configs" / "casa.yaml"


class CasaAdapter(SiteAdapter):
    """Adapter for Casa.it — Italy's oldest real estate portal (est. 1996).

    Uses fully config-driven parsing. The URL structure places all property
    types under the fixed path segment ``residenziale``, so the
    ``property_type_map`` in the YAML config collapses every property type
    to that value.
    """

    def __init__(self, config: SiteConfig | None = None) -> None:
        if config is None:
            config = load_config_from_yaml(_CONFIG_PATH)
        super().__init__(config)

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build Casa.it search URL using the `/srp/` pattern and `q` codes.

        Example target:

        ``https://www.casa.it/srp/?tr=affitti&numRoomsMin=2&mqMin=50&priceMin=50&priceMax=1000&photo=true&sortType=relevance&propertyTypeGroup=case&q=<code>``

        The `q` code is a location identifier. We maintain a minimal mapping
        from normalized area slugs to these codes and re-use them across
        searches so the multi-area scripts can hit the same result sets that
        you see in the browser.
        """
        # Operation (rent / sale)
        if filters.operation == "vendita":
            tr = "vendite"
        else:
            # Default to rentals
            tr = "affitti"

        # Property type group – keep it simple: all residential "case"
        # (this matches appartamenti/attici/case group on Casa.it).
        pt_group = "case"

        # Sorting
        if filters.sort == "piu-recenti":
            sort_type = "date_desc"
        else:
            # Default relevance sort
            sort_type = "relevance"

        # Known Casa.it location codes (`q`) for Milan areas.
        # The keys are normalized area slugs (same as `filters.area`).
        #
        # NOTE: Some codes correspond to grouped areas on Casa.it (e.g.
        # turro+greco+precotto share a single `q` value), so we map each slug
        # individually to the same code.
        milano_q_map: dict[str, str] = {
            # bicocca
            "bicocca": "a86a0cc6",
            # niguarda
            "niguarda": "8a4e090d",
            # citta studi
            "citta-studi": "d6b85baf",
            # lambrate
            "lambrate": "2fa24ae1",
            # grouped: turro + greco + precotto
            "precotto": "82c10d65",
            "turro": "82c10d65",
            "greco-segnano": "82c10d65",
            # crescenzago
            "crescenzago": "d6b85baf",
            # centrale
            "centrale": "2fa24ae1",
        }

        q: str | None = None
        city = filters.city.lower()
        area = (filters.area or "").lower()

        if city == "milano" and area:
            q = milano_q_map.get(area)

        # If we don't have a specific `q` mapping, fall back to a coarse search
        # using just the city name; this at least returns something rather than
        # failing outright.
        if q is None:
            q = city

        params: dict[str, str | int] = {
            "tr": tr,
            "propertyTypeGroup": pt_group,
            "sortType": sort_type,
            "q": q,
            # Always prefer listings with at least one photo
            "photo": "true",
        }

        # Prices
        if filters.min_price is not None:
            params["priceMin"] = filters.min_price
        if filters.max_price is not None:
            params["priceMax"] = filters.max_price

        # Surface (mq)
        if filters.min_sqm is not None:
            params["mqMin"] = filters.min_sqm
        if filters.max_sqm is not None:
            params["mqMax"] = filters.max_sqm

        # Rooms
        if filters.min_rooms is not None:
            params["numRoomsMin"] = filters.min_rooms

        # Pagination
        if filters.page >= 1:
            params["page"] = filters.page

        return f"{self.config.base_url}/srp/?{urlencode(params)}"
