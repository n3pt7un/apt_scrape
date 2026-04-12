"""apt_scrape.sites.tecnocasa — Adapter for Tecnocasa.it.

URL pattern:
    /affitto/immobili/lombardia/{city}/{city}.html?min_price=X&max_price=Y&...
    Pagination via path segment: /pag-{page} inserted before .html extension.

    Example page 1:
        /affitto/immobili/lombardia/milano/milano.html?min_price=700&max_price=1000&...
    Example page 2:
        /affitto/immobili/lombardia/milano/milano.html/pag-2?min_price=700&...

Detail URL: /affitto/appartamenti/{city}/{city}/{id}.html

Notes:
- No sub-area filtering: Tecnocasa searches are city-wide only.
- property_type filter is a numeric query param (1 = residential).
- Features (rooms, sqm, bathrooms) are in div.estate-card-data-element children.
- Address is the h4.estate-card-subtitle text ("City, Street - Neighbourhood").
"""

import logging
import re
from pathlib import Path
from urllib.parse import urlencode, urljoin

import yaml

from .base import (
    ListingSummary,
    SearchFilters,
    SearchSelectors,
    SiteAdapter,
    SiteConfig,
    Tag,
    classify_feature,
    extract_attr,
    extract_text,
    load_config_from_yaml,
)

logger = logging.getLogger(__name__)
_CONFIG_PATH = Path(__file__).parent / "configs" / "tecnocasa.yaml"


class TecnocasaAdapter(SiteAdapter):
    """Adapter for Tecnocasa.it — Italian real-estate franchise portal.

    Overrides ``build_search_url`` to handle:
    - Path-based pagination (/pag-{n} segment before query string).
    - Fixed city path (no area granularity).
    - Query-parameter filters (min_price, max_price, min_surface, etc.).

    Overrides ``_parse_one_card`` to extract:
    - Address from ``h4.estate-card-subtitle`` (not a generic span).
    - Features from ``div.estate-card-data-element`` spans.
    """

    def __init__(self, config: SiteConfig | None = None) -> None:
        if config is None:
            config = load_config_from_yaml(_CONFIG_PATH)
        super().__init__(config)
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
        self._query_param_map: dict[str, str] = raw.get("query_param_map", {})

    # ------------------------------------------------------------------
    # URL building
    # ------------------------------------------------------------------

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build a Tecnocasa search URL.

        Pagination uses a path segment ``/pag-{page}`` inserted between the
        base path and the query string (page 1 has no segment).

        Args:
            filters: Normalized search parameters.

        Returns:
            Fully qualified Tecnocasa search URL.
        """
        op = self.config.operation_map.get(filters.operation, filters.operation)
        city = filters.city.lower()

        # Base path (no area support)
        base_path = self.config.search_path_template.format(
            operation=op,
            city=city,
        )

        # Pagination segment
        if filters.page > 1:
            # Tecnocasa inserts /pag-N after the .html filename
            base_path = base_path + f"/pag-{filters.page}"

        # Build query params
        qmap = self._query_param_map
        query: dict[str, object] = {}

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

        # property_type: map through config; default to "1" (residential)
        pt_raw = filters.property_type or "appartamenti"
        pt_val = self.config.property_type_map.get(pt_raw, "1")
        if "property_type" in qmap:
            query[qmap["property_type"]] = pt_val

        url = self.config.base_url + base_path
        if query:
            url += "?" + urlencode(query)

        logger.debug("Built Tecnocasa URL: %s", url)
        return url

    # ------------------------------------------------------------------
    # Search card parsing
    # ------------------------------------------------------------------

    def _parse_one_card(self, card: Tag, sels: SearchSelectors) -> ListingSummary:
        """Parse a single Tecnocasa search result card.

        Card structure (confirmed April 2026)::

            div.estate-card
              a                              ← wraps everything; href = detail URL
                div.estate-carousel-image    ← thumbnail img
                div.estate-card-box-data
                  div.estate-card-price
                    div.estate-card-current-price  ← "€ 1.000 / mese"
                  div.estate-card-titles-container
                    h3.estate-card-title           ← "Bilocale in affitto"
                    h4.estate-card-subtitle        ← "Milano, Via Foo - Neighbourhood"
                  div.estate-card-data
                    div.estate-card-data-element.estate-card-rooms
                      span → "2 locali"
                    div.estate-card-data-element.estate-card-surface
                      span → "52 Mq"
                    div.estate-card-data-element.estate-card-bathrooms
                      span → "1 bagno"
        """
        # Link / URL
        link_el = card.select_one("a[href]")
        href = extract_attr(link_el, "href")
        if href and not href.startswith("http"):
            href = urljoin(self.config.base_url, href)

        # Title
        title_el = card.select_one("h3.estate-card-title")
        title = extract_text(title_el)

        # Price
        price_el = card.select_one("div.estate-card-current-price")
        price = extract_text(price_el)

        # Address: subtitle "Milano, Via Foo - Neighbourhood"
        subtitle_el = card.select_one("h4.estate-card-subtitle")
        address = extract_text(subtitle_el)

        # Features: dedicated data-element divs with known CSS class suffixes
        rooms_el = card.select_one("div.estate-card-rooms span")
        sqm_el = card.select_one("div.estate-card-surface span")
        bath_el = card.select_one("div.estate-card-bathrooms span")

        rooms = extract_text(rooms_el)
        sqm = extract_text(sqm_el)
        bathrooms = extract_text(bath_el)

        # Raw feature list for compatibility with base pipeline
        raw_features = [t for t in [rooms, sqm, bathrooms] if t]

        # Thumbnail
        img_el = (
            card.select_one("img[src*='cdn-media.medialabtc']")
            or card.select_one("img[src*='medialabtc.it']")
            or card.select_one("div.estate-carousel-image img")
            or card.select_one("img")
        )
        thumbnail = extract_attr(img_el, "src") or extract_attr(img_el, "data-src")
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = urljoin(self.config.base_url, thumbnail)

        # No description snippet on search cards
        description = ""

        post_date = self.extract_post_date_from_search_card(card, raw_features)

        return ListingSummary(
            source=self.config.display_name,
            title=title,
            url=href or "",
            price=price,
            sqm=sqm,
            rooms=rooms,
            bathrooms=bathrooms,
            address=address,
            thumbnail=thumbnail,
            description_snippet=description,
            post_date=post_date,
            raw_features=raw_features,
        )
