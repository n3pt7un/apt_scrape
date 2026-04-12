"""apt_scrape.sites.gabetti — Adapter for Gabetti.it.

URL pattern:
    /affitto/{city}?prezzoMin=X&prezzoMax=Y&mqMin=A&mqMax=B&numLocaliMin=N&page=P
    Pagination via query param &page=N (page 1 = no param or page=1).

    Example page 1:
        /affitto/milano?prezzoMin=700&prezzoMax=1000&mqMin=40&mqMax=100&numLocaliMin=2
    Example page 2:
        /affitto/milano?prezzoMin=700&prezzoMax=1000&mqMin=40&mqMax=100&numLocaliMin=2&page=2

Detail URL: /affitto/milano/appartamento/{ID}

Notes:
- No sub-area filtering: Gabetti searches are city-wide only.
- The site is built with Next.js — all CSS classes are Tailwind utility classes.
  Stable selectors use data attributes (data-uw-original-href) and a small set of
  semantic utility classes that are consistent across builds (t-body-big, t-h2, etc.).
- Each search card is an <a> element with data-uw-original-href pointing to the listing URL.
- Features (sqm, rooms, bathrooms) are bare <span> children of div.t-body-medium.
- Address on search cards: p.line-clamp-2.
- Price on search cards: div.t-body-big.
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
_CONFIG_PATH = Path(__file__).parent / "configs" / "gabetti.yaml"


class GabettiAdapter(SiteAdapter):
    """Adapter for Gabetti.it — Italian real-estate franchise portal.

    Overrides ``build_search_url`` to handle:
    - Standard query-parameter filters (prezzoMin, prezzoMax, mqMin, etc.).
    - Query-parameter pagination (&page=N).
    - Fixed city path (no area granularity).

    Overrides ``_parse_one_card`` to handle:
    - Card = the <a> anchor itself (data-uw-original-href = detail URL).
    - Price from div.t-body-big.
    - Address from p.line-clamp-2.
    - Features from bare <span> children of div.t-body-medium.
    - Thumbnail from img[src*='api.gabettigroup.com'].
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
        """Build a Gabetti search URL.

        Uses standard query parameters for all filters and pagination.

        Args:
            filters: Normalized search parameters.

        Returns:
            Fully qualified Gabetti search URL.
        """
        op = self.config.operation_map.get(filters.operation, filters.operation)
        city = filters.city.lower()

        # Base path (no area support — city-wide only)
        base_path = self.config.search_path_template.format(
            operation=op,
            city=city,
        )

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

        # Pagination: page 1 omits the param; page 2+ adds &page=N
        if filters.page > 1 and "page" in qmap:
            query[qmap["page"]] = filters.page

        url = self.config.base_url + base_path
        if query:
            url += "?" + urlencode(query)

        logger.debug("Built Gabetti URL: %s", url)
        return url

    # ------------------------------------------------------------------
    # Search card parsing
    # ------------------------------------------------------------------

    def _parse_one_card(self, card: Tag, sels: SearchSelectors) -> ListingSummary:
        """Parse a single Gabetti search result card.

        Card structure (confirmed April 2026)::

            a[data-uw-original-href="/affitto/milano/appartamento/ID"]
              img[src*="api.gabettigroup.com"]   ← thumbnail
              div                                 ← content wrapper
                p.line-clamp-2                   ← "Appartamento in Via Foo, Milano (MI)"
                div.t-body-big                   ← "950 €"
                div.t-body-medium                ← feature container
                  span                           ← "51 m²"
                  span                           ← "2 locali"
                  span                           ← "1 bagno"
        """
        # URL — from data-uw-original-href (stable accessibility attribute)
        href = extract_attr(card, "data-uw-original-href")
        if not href:
            href = extract_attr(card, "href")
        if href and not href.startswith("http"):
            href = urljoin(self.config.base_url, href)

        # Address (serves as title on Gabetti cards)
        addr_el = card.select_one("p.line-clamp-2") or card.select_one("p[class*='line-clamp']")
        address = extract_text(addr_el)
        title = address  # Gabetti uses address as the card headline

        # Price
        price_el = card.select_one("div.t-body-big") or card.select_one("[class*='t-body-big']")
        price = extract_text(price_el)

        # Features: bare <span> children inside div.t-body-medium
        feature_container = card.select_one("div.t-body-medium") or card.select_one("[class*='t-body-medium']")
        raw_features: list[str] = []
        if feature_container:
            raw_features = [
                s.get_text(strip=True)
                for s in feature_container.find_all("span", recursive=False)
                if s.get_text(strip=True)
            ]

        # Classify features into sqm / rooms / bathrooms
        sqm = rooms = bathrooms = ""
        for ft in raw_features:
            classified = classify_feature(ft)
            if classified:
                name, val = classified
                if name == "sqm" and not sqm:
                    sqm = val
                elif name == "rooms" and not rooms:
                    rooms = val
                elif name == "bathrooms" and not bathrooms:
                    bathrooms = val

        # Thumbnail
        img_el = (
            card.select_one("img[src*='api.gabettigroup.com/images-web']")
            or card.select_one("img[data-src*='api.gabettigroup.com']")
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
