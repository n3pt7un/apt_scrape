"""
sites.base — Abstract base class and shared types for site adapters.

To add a new site:
1. Create sites/your_site.py
2. Define a YAML config dict (or load from sites/your_site.yaml)
3. Subclass SiteAdapter and implement build_search_url, parse_search, parse_detail
4. Register it in sites/__init__.py

The config-driven approach means selectors and URL templates live in data,
not buried in code. You can patch selectors without touching Python.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

from bs4 import BeautifulSoup, Tag


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------


@dataclass
class SearchFilters:
    """Normalized search filters passed from the MCP tool to any site adapter."""

    city: str
    area: Optional[str] = None
    operation: str = "affitto"  # affitto | vendita
    property_type: str = "case"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_sqm: Optional[int] = None
    max_sqm: Optional[int] = None
    min_rooms: Optional[int] = None
    max_rooms: Optional[int] = None
    published_within: Optional[str] = None  # days as string: "1","3","7","14","30"
    sort: str = "rilevanza"  # rilevanza | piu-recenti | etc.
    page: int = 1


@dataclass
class ListingSummary:
    """One listing card from a search results page."""

    source: str
    title: str = ""
    url: str = ""
    price: str = ""
    sqm: str = ""
    rooms: str = ""
    bathrooms: str = ""
    address: str = ""
    thumbnail: str = ""
    description_snippet: str = ""
    post_date: str = ""
    features_raw: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ListingDetail:
    """Full detail extracted from a single listing page."""

    source: str
    url: str
    title: str = ""
    price: str = ""
    description: str = ""
    address: str = ""
    size: str = ""
    floor: str = ""
    metadata: dict[str, str] = field(default_factory=dict)
    photos: list[str] = field(default_factory=list)
    energy_class: str = ""
    agency: str = ""
    post_date: str = ""
    costs: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# Selector config schema
# ---------------------------------------------------------------------------


@dataclass
class SelectorGroup:
    """A group of CSS selectors tried in order (first match wins).

    This is the core mechanism for resilient parsing — sites change class names
    constantly, so we store fallback chains rather than single selectors.
    """

    selectors: list[str]

    def find(self, soup: BeautifulSoup | Tag) -> Optional[Tag]:
        """Return the first element matched by any selector, or None."""
        for sel in self.selectors:
            el = soup.select_one(sel)
            if el is not None:
                return el
        return None

    def find_all(self, soup: BeautifulSoup | Tag) -> list[Tag]:
        """Return all elements matched by selectors (merged, deduplicated by id)."""
        seen: set[int] = set()
        results: list[Tag] = []
        for sel in self.selectors:
            for el in soup.select(sel):
                eid = id(el)
                if eid not in seen:
                    seen.add(eid)
                    results.append(el)
        return results


@dataclass
class SearchSelectors:
    """All CSS selector groups needed to parse a search results page."""

    listing_card: SelectorGroup
    title: SelectorGroup
    price: SelectorGroup
    features: SelectorGroup
    address: SelectorGroup
    thumbnail: SelectorGroup
    description: SelectorGroup


@dataclass
class DetailSelectors:
    """All CSS selector groups needed to parse a listing detail page."""

    title: SelectorGroup
    price: SelectorGroup
    description: SelectorGroup
    features_keys: SelectorGroup
    features_values: SelectorGroup
    address: SelectorGroup
    photos: SelectorGroup
    energy_class: SelectorGroup
    agency: SelectorGroup
    costs_keys: SelectorGroup
    costs_values: SelectorGroup


@dataclass
class SiteConfig:
    """Full configuration for a site adapter, loadable from YAML/dict."""

    site_id: str  # e.g. "immobiliare"
    display_name: str  # e.g. "Immobiliare.it"
    base_url: str  # e.g. "https://www.immobiliare.it"
    domain_pattern: str  # regex to match URLs belonging to this site

    # URL template for search — Python .format() with named placeholders
    # Available keys: {operation}, {property_type}, {city}
    search_path_template: str

    # Mapping from normalized filter names to this site's query param names
    query_param_map: dict[str, str]

    # Name of the pagination query param, e.g. "pag" or "page"
    page_param: str

    # Selector to wait for after page load (for Camoufox)
    search_wait_selector: str
    detail_wait_selector: str

    # CSS selector configs
    search_selectors: SearchSelectors
    detail_selectors: DetailSelectors

    # Property type mapping: normalized name → site-specific slug
    # e.g. {"case": "case", "appartamenti": "appartamenti"}
    property_type_map: dict[str, str] = field(default_factory=dict)

    # Operation mapping: normalized → site-specific
    # e.g. {"affitto": "affitto", "vendita": "vendita"}
    operation_map: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def extract_text(element: Optional[Tag], default: str = "") -> str:
    """Safely extract stripped text from a BS4 element."""
    if element is None:
        return default
    return element.get_text(strip=True)


def extract_attr(element: Optional[Tag], attr: str, default: str = "") -> str:
    """Safely extract an attribute from a BS4 element."""
    if element is None:
        return default
    val = element.get(attr, default)
    return val if isinstance(val, str) else (val[0] if val else default)


def classify_feature(text: str) -> Optional[tuple[str, str]]:
    """Try to classify a feature string as sqm/rooms/bathrooms.

    Returns (field_name, raw_text) or None if unrecognized.
    """
    t = text.lower()
    if "m²" in t or "mq" in t:
        return ("sqm", text)
    if "local" in t or "vani" in t:
        return ("rooms", text)
    if "bagn" in t:
        return ("bathrooms", text)
    return None


def extract_post_date_text(text: str) -> str:
    """Extract a listing publication/update date text from arbitrary content."""
    if not text:
        return ""

    # Prefer explicit labels when available.
    patterns = [
        re.compile(
            r"((?:annuncio\s+)?(?:pubblicato|inserito|aggiornato)\s+(?:il\s+)?"
            r"\d{1,2}/\d{1,2}/\d{2,4})",
            flags=re.IGNORECASE,
        ),
        re.compile(
            r"((?:annuncio\s+)?(?:pubblicato|inserito|aggiornato)\s+(?:oggi|ieri))",
            flags=re.IGNORECASE,
        ),
        re.compile(r"\b(?:oggi|ieri)\b", flags=re.IGNORECASE),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(1) if match.groups() else match.group(0)).strip()

    return ""


# ---------------------------------------------------------------------------
# YAML config loader
# ---------------------------------------------------------------------------


def _sg(selectors: list[str]) -> SelectorGroup:
    return SelectorGroup(selectors)


def load_config_from_yaml(path: str) -> SiteConfig:
    """Load a SiteConfig from a YAML file."""
    import yaml
    from pathlib import Path

    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f)

    def sg(key: dict) -> SelectorGroup:
        return SelectorGroup(key if isinstance(key, list) else [key])

    ss = d["search_selectors"]
    ds = d["detail_selectors"]

    return SiteConfig(
        site_id=d["site_id"],
        display_name=d["display_name"],
        base_url=d["base_url"],
        domain_pattern=d["domain_pattern"],
        search_path_template=d["search_path_template"],
        query_param_map=d.get("query_param_map", {}),
        page_param=d.get("page_param", "page"),
        search_wait_selector=d.get("search_wait_selector", "body"),
        detail_wait_selector=d.get("detail_wait_selector", "h1"),
        property_type_map=d.get("property_type_map", {}),
        operation_map=d.get("operation_map", {}),
        search_selectors=SearchSelectors(
            listing_card=sg(ss["listing_card"]),
            title=sg(ss["title"]),
            price=sg(ss["price"]),
            features=sg(ss["features"]),
            address=sg(ss["address"]),
            thumbnail=sg(ss["thumbnail"]),
            description=sg(ss["description"]),
        ),
        detail_selectors=DetailSelectors(
            title=sg(ds["title"]),
            price=sg(ds["price"]),
            description=sg(ds["description"]),
            features_keys=sg(ds["features_keys"]),
            features_values=sg(ds["features_values"]),
            address=sg(ds["address"]),
            photos=sg(ds["photos"]),
            energy_class=sg(ds["energy_class"]),
            agency=sg(ds["agency"]),
            costs_keys=sg(ds["costs_keys"]),
            costs_values=sg(ds["costs_values"]),
        ),
    )


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class SiteAdapter(ABC):
    """Base class for all site adapters.

    Subclasses can either override methods for custom logic, or rely on the
    default config-driven implementations that use SiteConfig + SelectorGroups.
    """

    def __init__(self, config: SiteConfig):
        self.config = config
        self._domain_re = re.compile(config.domain_pattern)

    @property
    def site_id(self) -> str:
        return self.config.site_id

    def matches_url(self, url: str) -> bool:
        """Check if a URL belongs to this site."""
        return bool(self._domain_re.search(url))

    # --- URL building (config-driven default) ---

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build a full search URL from normalized filters.

        Default implementation uses config templates + query_param_map.
        Override if the site has a non-standard URL structure.
        """
        op = self.config.operation_map.get(filters.operation, filters.operation)
        pt = self.config.property_type_map.get(filters.property_type, filters.property_type)

        location = filters.city
        if filters.area:
            location = f"{location}/{filters.area.strip('/')}"

        path = self.config.search_path_template.format(
            operation=op,
            property_type=pt,
            city=location,
        )

        qmap = self.config.query_param_map
        query: dict[str, Any] = {}

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
        if filters.published_within and "published_within" in qmap:
            query[qmap["published_within"]] = filters.published_within
        if filters.sort != "rilevanza" and "sort" in qmap:  # only add if not default
            query[qmap["sort"]] = filters.sort
        if filters.page >= 1:
            query[self.config.page_param] = filters.page

        from urllib.parse import urlencode

        url = self.config.base_url + path
        if query:
            url += "?" + urlencode(query)
        return url

    # --- Parsing (config-driven defaults) ---

    def parse_search(self, html: str) -> list[ListingSummary]:
        """Parse a search results page into listing summaries.

        Default implementation uses SearchSelectors from config.
        Override for sites that need custom extraction logic.
        """
        soup = BeautifulSoup(html, "lxml")
        sels = self.config.search_selectors
        cards = sels.listing_card.find_all(soup)
        listings: list[ListingSummary] = []

        for card in cards:
            try:
                listing = self._parse_one_card(card, sels)
                if listing.url:
                    listings.append(listing)
            except Exception:
                continue

        return listings

    def _parse_one_card(self, card: Tag, sels: SearchSelectors) -> ListingSummary:
        """Parse a single listing card element."""
        from urllib.parse import urljoin

        title_el = sels.title.find(card)
        title = extract_text(title_el)

        # URL — try href from the title link, or from any link in the card
        href = extract_attr(title_el, "href")
        if not href:
            any_link = card.select_one("a[href]")
            href = extract_attr(any_link, "href")
        if href and not href.startswith("http"):
            href = urljoin(self.config.base_url, href)

        price = extract_text(sels.price.find(card))

        features = sels.features.find_all(card)
        feature_texts = [extract_text(f) for f in features if extract_text(f)]

        sqm = ""
        rooms = ""
        bathrooms = ""
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
        thumbnail = extract_attr(img_el, "data-src") or extract_attr(img_el, "src")

        desc = extract_text(sels.description.find(card))
        post_date = self.extract_post_date_from_search_card(card, feature_texts)

        return ListingSummary(
            source=self.config.display_name,
            title=title,
            url=href,
            price=price,
            sqm=sqm,
            rooms=rooms,
            bathrooms=bathrooms,
            address=address,
            thumbnail=thumbnail,
            description_snippet=desc,
            post_date=post_date,
            features_raw=feature_texts,
        )

    def extract_post_date_from_search_card(self, card: Tag, feature_texts: list[str]) -> str:
        """Best-effort post date extraction from a search-result card."""
        candidates = []
        candidates.extend(feature_texts)
        candidates.append(card.get_text(" ", strip=True))

        for candidate in candidates:
            post_date = extract_post_date_text(candidate)
            if post_date:
                return post_date
        return ""

    def extract_post_date_from_detail_html(self, html: str) -> str:
        """Best-effort post date extraction from detail page HTML."""
        soup = BeautifulSoup(html, "lxml")
        return extract_post_date_text(soup.get_text(" ", strip=True))

    def parse_detail(self, html: str, url: str) -> ListingDetail:
        """Parse a listing detail page.

        Default implementation uses DetailSelectors from config.
        Override for sites that need custom extraction logic.
        """
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "lxml")
        sels = self.config.detail_selectors

        title = extract_text(sels.title.find(soup))
        price = extract_text(sels.price.find(soup))
        description = extract_text(sels.description.find(soup))
        address = extract_text(sels.address.find(soup))

        # Features / metadata (key-value pairs)
        keys_els = sels.features_keys.find_all(soup)
        vals_els = sels.features_values.find_all(soup)
        metadata: dict[str, str] = {}
        for k_el, v_el in zip(keys_els, vals_els):
            k = extract_text(k_el)
            v = extract_text(v_el)
            if k:
                metadata[k] = v

        # Photos
        photos: list[str] = []
        for img in sels.photos.find_all(soup):
            src = extract_attr(img, "data-src") or extract_attr(img, "src")
            if src and src not in photos:
                if not src.startswith("http"):
                    src = urljoin(self.config.base_url, src)
                photos.append(src)

        energy_class = extract_text(sels.energy_class.find(soup))
        agency = extract_text(sels.agency.find(soup))
        post_date = self.extract_post_date_from_detail_html(html)

        # Costs
        cost_keys = sels.costs_keys.find_all(soup)
        cost_vals = sels.costs_values.find_all(soup)
        costs: dict[str, str] = {}
        for k_el, v_el in zip(cost_keys, cost_vals):
            k = extract_text(k_el)
            v = extract_text(v_el)
            if k:
                costs[k] = v

        return ListingDetail(
            source=self.config.display_name,
            url=url,
            title=title,
            price=price,
            description=description,
            address=address,
            metadata=metadata,
            photos=photos[:20],
            energy_class=energy_class,
            agency=agency,
            post_date=post_date,
            costs=costs,
        )
