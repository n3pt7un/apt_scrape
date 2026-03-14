"""apt_scrape.sites.idealista — Adapter for Idealista.it.

URL pattern: ``/{operation}-{property_type}/{city}/{area}/con-{filters}/``
Detail URL:  ``/immobile/{id}/``
Config:      ``apt_scrape/sites/configs/idealista.yaml``

Idealista uses path-based filters instead of query parameters. All filters
are encoded as comma-separated path segments after ``/con-``:

    .../milano/citta-studi/con-prezzo_1200,prezzo-min_100,dimensione_40,bilocali-2/

The adapter overrides ``build_search_url`` to construct these filter paths.
"""

import logging
import re
from pathlib import Path
from urllib.parse import urljoin

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
_CONFIG_PATH = Path(__file__).parent / "configs" / "idealista.yaml"


class IdealistaAdapter(SiteAdapter):
    """Adapter for Idealista.it — international real estate portal.

    Overrides ``build_search_url`` to handle Idealista's path-based filter
    encoding (e.g. ``/con-prezzo_1200,dimensione_40/``).
    """

    def __init__(self, config: SiteConfig | None = None) -> None:
        if config is None:
            config = load_config_from_yaml(_CONFIG_PATH)
        super().__init__(config)
        # Load extra config fields not in SiteConfig
        with open(_CONFIG_PATH, encoding="utf-8") as fh:
            raw_config = yaml.safe_load(fh)
        self.path_filter_map = raw_config.get("path_filter_map", {})
        self.room_filter_map = raw_config.get("room_filter_map", {})
        self.sort_map = raw_config.get("sort_map", {})
        self.page_path_template = raw_config.get("page_path_template", "pagina-{page}.htm")
        self.area_map = raw_config.get("area_map", {})

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build an Idealista search URL with path-based filters.

        Idealista encodes all filters in a single path segment after ``/con-``
        with comma-separated filter expressions:

            /affitto-appartamenti/milano/con-prezzo_1200,dimensione_40/

        Args:
            filters: Normalized search parameters.

        Returns:
            Fully qualified Idealista search URL.
        """
        # Map operation and property type
        op = self.config.operation_map.get(filters.operation, filters.operation)
        pt = self.config.property_type_map.get(filters.property_type, filters.property_type)

        # Build location path, mapping simple area slugs to Idealista's zone/neighborhood format
        location = filters.city
        if filters.area:
            area_clean = filters.area.strip("/")
            # Look up the Idealista-specific path (e.g. "bicocca" → "bicocca-niguarda-precotto/bicocca")
            area_path = self.area_map.get(area_clean, area_clean)
            location = f"{location}/{area_path}"

        # Build base path
        path = self.config.search_path_template.format(
            operation=op,
            property_type=pt,
            city=location,
        )

        # Build filter path segments
        filter_parts: list[str] = []
        
        # Price filters
        if filters.max_price is not None and "max_price" in self.path_filter_map:
            filter_parts.append(self.path_filter_map["max_price"].format(value=filters.max_price))
        if filters.min_price is not None and "min_price" in self.path_filter_map:
            filter_parts.append(self.path_filter_map["min_price"].format(value=filters.min_price))

        # Size filters
        if filters.min_sqm is not None and "min_sqm" in self.path_filter_map:
            filter_parts.append(self.path_filter_map["min_sqm"].format(value=filters.min_sqm))
        if filters.max_sqm is not None and "max_sqm" in self.path_filter_map:
            filter_parts.append(self.path_filter_map["max_sqm"].format(value=filters.max_sqm))

        # Room filters - idealista uses named segments like "bilocali-2", "trilocali-3"
        if filters.min_rooms is not None:
            # For min_rooms, we need to include all room types >= min_rooms
            min_rooms = filters.min_rooms
            max_rooms = filters.max_rooms or 5  # Default max to 5+
            
            # Build list of room filters to include
            for room_num in range(min_rooms, max_rooms + 1):
                room_key = str(room_num)
                if room_key in self.room_filter_map:
                    filter_parts.append(self.room_filter_map[room_key])
                elif room_num >= 5:
                    # 5+ rooms
                    filter_parts.append("5-locali-o-piu")
                    break

        # Published within filter (sort by recency)
        sort_value = (filters.sort or "").strip().lower()
        
        if sort_value in self.sort_map:
            # Map sort to published_within filter
            filter_parts.append(f"pubblicato_{self.sort_map[sort_value]}")
        elif filters.published_within and "published_within" in self.path_filter_map:
            # Direct published_within filter
            days = filters.published_within
            if days == "1":
                filter_parts.append("pubblicato_ultime-24-ore")
            elif days == "7":
                filter_parts.append("pubblicato_ultima-settimana")
            elif days == "14":
                filter_parts.append("pubblicato_ultimi-15-giorni")
            elif days == "30":
                filter_parts.append("pubblicato_ultimo-mese")

        # Combine filters into path
        if filter_parts:
            filters_str = ",".join(filter_parts)
            path = f"{path.rstrip('/')}/con-{filters_str}/"
        else:
            # No filters - just ensure trailing slash
            path = f"{path.rstrip('/')}/"

        # Add pagination if needed
        if filters.page > 1:
            page_suffix = self.page_path_template.format(page=filters.page)
            path = f"{path.rstrip('/')}/{page_suffix}"

        url = self.config.base_url + path
        logger.debug(f"Built Idealista URL: {url}")
        return url

    def _parse_one_card(self, card: Tag, sels: SearchSelectors) -> ListingSummary:
        """Parse a single Idealista search result card.

        Idealista renders all feature spans inside a single container div;
        individual ``span.item-detail`` elements give clean values, but a
        sibling span concatenates them all into one string.  This override
        deduplicates by keeping only single-feature strings (no embedded
        spaces from concatenation) and splits on the known m2 pattern.
        """
        title_el = sels.title.find(card)
        title = extract_text(title_el)

        href = extract_attr(title_el, "href")
        if not href:
            any_link = card.select_one("a[href]")
            href = extract_attr(any_link, "href")
        if href and not href.startswith("http"):
            href = urljoin(self.config.base_url, href)

        price = extract_text(sels.price.find(card))

        # Collect individual feature spans, skip the concatenated summary span
        raw_spans = sels.features.find_all(card)
        feature_texts: list[str] = []
        longest = ""
        for span in raw_spans:
            t = extract_text(span)
            if t:
                feature_texts.append(t)
                if len(t) > len(longest):
                    longest = t
        # Remove the concatenated string (it's a superset of all others)
        feature_texts = [t for t in feature_texts if t != longest or feature_texts.count(t) > 1]
        # Also split any remaining "Nlocali67 m2Floor" style strings by known keywords
        split: list[str] = []
        for t in feature_texts:
            # Split on boundaries between known feature types
            parts = re.split(r'(?<=\w)(?=\d+(?:º|°)?\s*(?:piano|locale|locali)|\bpiano\b|\bbagn)', t, flags=re.IGNORECASE)
            split.extend(p.strip() for p in parts if p.strip())
        feature_texts = split

        sqm = rooms = bathrooms = ""
        for ft in feature_texts:
            classified = classify_feature(ft)
            if classified:
                name, val = classified
                if name == "sqm" and not sqm:
                    sqm = val
                elif name == "rooms" and not rooms:
                    rooms = val
                elif name == "bathrooms" and not bathrooms:
                    bathrooms = val

        address = extract_text(sels.address.find(card))
        img_el = sels.thumbnail.find(card)
        thumbnail = (
            extract_attr(img_el, "data-ondemand-img")
            or extract_attr(img_el, "data-src")
            or extract_attr(img_el, "src")
        )
        if thumbnail and not thumbnail.startswith("http"):
            thumbnail = urljoin(self.config.base_url, thumbnail)
        description = extract_text(sels.description.find(card))
        post_date = self.extract_post_date_from_search_card(card, feature_texts)

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
            raw_features=feature_texts,
        )
