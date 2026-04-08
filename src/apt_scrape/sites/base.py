"""apt_scrape.sites.base — Abstract base class and shared types for site adapters.

To add a new site:
    1. Copy ``templates/new_site_adapter.py`` to ``apt_scrape/sites/your_site.py``.
    2. Define a ``SiteConfig`` (or load one from ``apt_scrape/sites/configs/your_site.yaml``).
    3. Subclass ``SiteAdapter`` and override only the methods that differ from the
       config-driven defaults.
    4. Register the adapter in ``apt_scrape/sites/__init__.py``.

The config-driven approach keeps selectors and URL templates in data rather than
buried in Python, so you can patch a broken selector without touching code.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag

__all__ = [
    "ClassifyResult",
    "DetailSelectors",
    "ListingDetail",
    "ListingSummary",
    "SearchFilters",
    "SearchSelectors",
    "SelectorGroup",
    "SiteAdapter",
    "SiteConfig",
    "Tag",
    "classify_feature",
    "config_from_dict",
    "config_to_dict",
    "deep_merge",
    "extract_attr",
    "extract_post_date_text",
    "extract_text",
    "load_config_from_yaml",
]

logger = logging.getLogger(__name__)

# Type alias kept in __all__ so adapter modules can import it from here.
ClassifyResult = tuple[str, str]


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------


@dataclass
class SearchFilters:
    """Normalized search filters passed from the caller to any site adapter.

    Attributes:
        city: City slug (e.g. ``"milano"``).
        area: Optional sub-area slug inside the city (e.g. ``"navigli"``).
        operation: Contract type — ``"affitto"`` (rent) or ``"vendita"`` (sale).
        property_type: Property category slug (e.g. ``"appartamenti"``).
        min_price: Minimum price in EUR, or ``None`` for no lower bound.
        max_price: Maximum price in EUR, or ``None`` for no upper bound.
        min_sqm: Minimum surface area in m², or ``None``.
        max_sqm: Maximum surface area in m², or ``None``.
        min_rooms: Minimum room count, or ``None``.
        max_rooms: Maximum room count, or ``None``.
        published_within: Recency filter in days as a string (``"1"``, ``"3"``,
            ``"7"``, ``"14"``, ``"30"``), or ``None`` to disable.
        sort: Sort order slug (e.g. ``"rilevanza"``, ``"piu-recenti"``).
        page: 1-based result page number.
    """

    city: str
    area: str | None = None
    operation: str = "affitto"
    property_type: str = "case"
    min_price: int | None = None
    max_price: int | None = None
    min_sqm: int | None = None
    max_sqm: int | None = None
    min_rooms: int | None = None
    max_rooms: int | None = None
    published_within: str | None = None
    sort: str = "rilevanza"
    page: int = 1


@dataclass
class ListingSummary:
    """One listing card extracted from a search results page.

    Attributes:
        source: Human-readable site name (e.g. ``"Immobiliare.it"``).
        title: Listing headline.
        url: Full URL of the listing detail page.
        price: Price string as shown on the site (e.g. ``"€ 1.200/mese"``).
        sqm: Surface area string (e.g. ``"65 m²"``).
        rooms: Room count string (e.g. ``"3 locali"``).
        bathrooms: Bathroom count string.
        address: Location text.
        thumbnail: URL of the thumbnail image.
        description_snippet: Short description excerpt.
        post_date: Publication or update date text.
        raw_features: All raw feature strings extracted from the card.
    """

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
    raw_features: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this summary."""
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class ListingDetail:
    """Full detail extracted from a single listing page.

    Attributes:
        source: Human-readable site name.
        url: Full URL of this listing page.
        title: Listing headline.
        price: Price string.
        description: Full description text.
        address: Full address string.
        size: Surface area (promoted from ``extra_info`` when available).
        floor: Floor number or description.
        extra_info: Key/value pairs from the features/characteristics section.
        photos: List of full-resolution photo URLs (capped at 20).
        energy_class: Energy efficiency class label.
        agency: Agency or landlord name.
        post_date: Publication or update date text.
        costs: Additional financial costs (e.g. condominium fees, deposit).
        extra: Catch-all dict for adapter-specific fields.
    """

    source: str
    url: str
    title: str = ""
    price: str = ""
    description: str = ""
    address: str = ""
    size: str = ""
    floor: str = ""
    extra_info: dict[str, str] = field(default_factory=dict)
    photos: list[str] = field(default_factory=list)
    energy_class: str = ""
    agency: str = ""
    post_date: str = ""
    costs: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict representation of this detail."""
        return {k: v for k, v in self.__dict__.items()}


# ---------------------------------------------------------------------------
# Selector config schema
# ---------------------------------------------------------------------------


@dataclass
class SelectorGroup:
    """A group of CSS selectors tried in order; first match wins.

    Storing fallback chains rather than single selectors makes parsing
    resilient to the frequent class-name churn on real estate sites.

    Attributes:
        selectors: Ordered list of CSS selector strings.
    """

    selectors: list[str]

    def find(self, soup: BeautifulSoup | Tag) -> Tag | None:
        """Return the first element matched by any selector.

        Args:
            soup: A BeautifulSoup tree or subtree to search.

        Returns:
            The first matching ``Tag``, or ``None`` if nothing matches.
        """
        for sel in self.selectors:
            el = soup.select_one(sel)
            if el is not None:
                return el
        return None

    def find_all(self, soup: BeautifulSoup | Tag) -> list[Tag]:
        """Return all elements matched by any selector, deduplicated by identity.

        Args:
            soup: A BeautifulSoup tree or subtree to search.

        Returns:
            List of matching ``Tag`` objects in document order, with duplicates
            removed.
        """
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
    """All CSS selector groups needed to parse a search results page.

    Attributes:
        listing_card: Container element for each result card.
        title: Title/headline link inside a card.
        price: Price element inside a card.
        features: Feature items (sqm, rooms, etc.) inside a card.
        address: Address or location element inside a card.
        thumbnail: Thumbnail ``<img>`` inside a card.
        description: Short description snippet inside a card.
    """

    listing_card: SelectorGroup
    title: SelectorGroup
    price: SelectorGroup
    features: SelectorGroup
    address: SelectorGroup
    thumbnail: SelectorGroup
    description: SelectorGroup


@dataclass
class DetailSelectors:
    """All CSS selector groups needed to parse a listing detail page.

    Attributes:
        title: Listing headline element.
        price: Price element.
        description: Full description element.
        features_keys: ``<dt>``-like labels in the features section.
        features_values: ``<dd>``-like values in the features section.
        address: Address element.
        photos: Photo ``<img>`` elements.
        energy_class: Energy class label element.
        agency: Agency or landlord name element.
        costs_keys: Labels in the costs section.
        costs_values: Values in the costs section.
    """

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
    """Full configuration for a site adapter, loadable from YAML or a dict.

    Attributes:
        site_id: Short slug used as the ``--source`` identifier (e.g.
            ``"immobiliare"``).
        display_name: Human-readable name shown in output (e.g.
            ``"Immobiliare.it"``).
        base_url: Scheme + host (e.g. ``"https://www.immobiliare.it"``).
        domain_pattern: Regex pattern matched against listing URLs to identify
            which site they belong to.
        search_path_template: ``str.format()`` template for the search path.
            Available placeholders: ``{operation}``, ``{property_type}``,
            ``{city}``.
        query_param_map: Mapping from normalized filter names (e.g.
            ``"min_price"``) to this site's query parameter names.
        page_param: Query parameter name used for pagination (e.g. ``"pag"``).
        search_wait_selector: CSS selector Camoufox waits for after page load
            on search pages.
        detail_wait_selector: CSS selector Camoufox waits for on detail pages.
        search_selectors: Selector groups for search result parsing.
        detail_selectors: Selector groups for detail page parsing.
        property_type_map: Mapping from normalized property type slugs to
            site-specific slugs used in the URL.
        operation_map: Mapping from normalized operation names to site-specific
            slugs (e.g. ``{"affitto": "affitto", "vendita": "vendita"}``).
    """

    site_id: str
    display_name: str
    base_url: str
    domain_pattern: str
    search_path_template: str
    query_param_map: dict[str, str]
    page_param: str
    search_wait_selector: str
    detail_wait_selector: str
    search_selectors: SearchSelectors
    detail_selectors: DetailSelectors
    property_type_map: dict[str, str] = field(default_factory=dict)
    operation_map: dict[str, str] = field(default_factory=dict)
    # Playwright wait_until strategy for page.goto().
    # Use "networkidle" for sites that decode/hydrate content via JS after load.
    page_load_wait: str = "domcontentloaded"
    # Milliseconds to wait for search_wait_selector to appear (default 15 s).
    # Increase for SPAs that take longer to hydrate (e.g. Casa.it ~45 s).
    search_wait_timeout: int = 15000
    # URL for the site's login page (used by the `login` CLI command).
    login_url: str = ""
    # Per-site rate limiting: jittered delay range between requests.
    min_request_delay: float = 2.0
    max_request_delay: float = 4.0
    # Substring that must appear in a listing detail URL.
    # Used to filter out non-listing links (nav, agency, filter pages)
    # extracted by the search parser's fallback href logic.
    detail_url_contains: str = ""


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def extract_text(element: Tag | None, default: str = "") -> str:
    """Safely extract stripped text from a BeautifulSoup element.

    Args:
        element: A ``Tag`` or ``None``.
        default: Value returned when *element* is ``None``.

    Returns:
        Stripped text content, or *default*.
    """
    if element is None:
        return default
    return element.get_text(strip=True)


def extract_attr(element: Tag | None, attr: str, default: str = "") -> str:
    """Safely extract an attribute value from a BeautifulSoup element.

    Args:
        element: A ``Tag`` or ``None``.
        attr: Attribute name (e.g. ``"href"``, ``"src"``).
        default: Value returned when *element* is ``None`` or the attribute
            is absent.

    Returns:
        Attribute string value, or *default*.
    """
    if element is None:
        return default
    val = element.get(attr, default)
    return val if isinstance(val, str) else (val[0] if val else default)


def classify_feature(text: str) -> ClassifyResult | None:
    """Classify a feature string as sqm, rooms, or bathrooms.

    Args:
        text: Raw feature string from a listing card.

    Returns:
        A ``(field_name, raw_text)`` tuple if the feature is recognized, or
        ``None`` if the text does not match any known category.
    """
    t = text.lower()
    if "m²" in t or "mq" in t or "m2" in t:
        return ("sqm", text)
    if "local" in t or "vani" in t:
        return ("rooms", text)
    if "bagn" in t:
        return ("bathrooms", text)
    return None


def extract_post_date_text(text: str) -> str:
    """Extract a publication or update date string from arbitrary page text.

    Tries progressively less specific patterns; returns the first match.

    Args:
        text: Arbitrary text, typically from a card or full page.

    Returns:
        Matched date string (e.g. ``"pubblicato il 12/03/2025"``), or ``""``
        if no date pattern is found.
    """
    if not text:
        return ""

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
            return re.sub(
                r"\s+", " ", match.group(1) if match.groups() else match.group(0)
            ).strip()

    return ""


# ---------------------------------------------------------------------------
# YAML config loader and config dict support
# ---------------------------------------------------------------------------


def _sg(value: list[str] | str) -> SelectorGroup:
    """Build a SelectorGroup from a list or single string."""
    return SelectorGroup(value if isinstance(value, list) else [value])


def config_from_dict(d: dict[str, Any]) -> SiteConfig:
    """Build a ``SiteConfig`` from a nested dict (same structure as YAML).

    Args:
        d: Config dict with keys like search_selectors, detail_selectors, etc.

    Returns:
        A fully populated ``SiteConfig`` instance.
    """
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
        page_load_wait=d.get("page_load_wait", "domcontentloaded"),
        search_wait_timeout=d.get("search_wait_timeout", 15000),
        login_url=d.get("login_url", ""),
        min_request_delay=d.get("min_request_delay", 2.0),
        max_request_delay=d.get("max_request_delay", 4.0),
        detail_url_contains=d.get("detail_url_contains", ""),
        search_selectors=SearchSelectors(
            listing_card=_sg(ss["listing_card"]),
            title=_sg(ss["title"]),
            price=_sg(ss["price"]),
            features=_sg(ss["features"]),
            address=_sg(ss["address"]),
            thumbnail=_sg(ss["thumbnail"]),
            description=_sg(ss["description"]),
        ),
        detail_selectors=DetailSelectors(
            title=_sg(ds["title"]),
            price=_sg(ds["price"]),
            description=_sg(ds["description"]),
            features_keys=_sg(ds["features_keys"]),
            features_values=_sg(ds["features_values"]),
            address=_sg(ds["address"]),
            photos=_sg(ds["photos"]),
            energy_class=_sg(ds["energy_class"]),
            agency=_sg(ds["agency"]),
            costs_keys=_sg(ds["costs_keys"]),
            costs_values=_sg(ds["costs_values"]),
        ),
    )


def config_to_dict(config: SiteConfig) -> dict[str, Any]:
    """Serialize a ``SiteConfig`` to a nested dict (selector groups as lists of strings)."""
    def sg_to_list(sg: SelectorGroup) -> list[str]:
        return list(sg.selectors)

    ss = config.search_selectors
    ds = config.detail_selectors
    return {
        "site_id": config.site_id,
        "display_name": config.display_name,
        "base_url": config.base_url,
        "domain_pattern": config.domain_pattern,
        "search_path_template": config.search_path_template,
        "query_param_map": config.query_param_map,
        "page_param": config.page_param,
        "search_wait_selector": config.search_wait_selector,
        "detail_wait_selector": config.detail_wait_selector,
        "property_type_map": config.property_type_map,
        "operation_map": config.operation_map,
        "page_load_wait": config.page_load_wait,
        "search_wait_timeout": config.search_wait_timeout,
        "login_url": config.login_url,
        "min_request_delay": config.min_request_delay,
        "max_request_delay": config.max_request_delay,
        "detail_url_contains": config.detail_url_contains,
        "search_selectors": {
            "listing_card": sg_to_list(ss.listing_card),
            "title": sg_to_list(ss.title),
            "price": sg_to_list(ss.price),
            "features": sg_to_list(ss.features),
            "address": sg_to_list(ss.address),
            "thumbnail": sg_to_list(ss.thumbnail),
            "description": sg_to_list(ss.description),
        },
        "detail_selectors": {
            "title": sg_to_list(ds.title),
            "price": sg_to_list(ds.price),
            "description": sg_to_list(ds.description),
            "features_keys": sg_to_list(ds.features_keys),
            "features_values": sg_to_list(ds.features_values),
            "address": sg_to_list(ds.address),
            "photos": sg_to_list(ds.photos),
            "energy_class": sg_to_list(ds.energy_class),
            "agency": sg_to_list(ds.agency),
            "costs_keys": sg_to_list(ds.costs_keys),
            "costs_values": sg_to_list(ds.costs_values),
        },
    }


def deep_merge(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overrides into base. Overrides win; lists in overrides replace base lists."""
    result = dict(base)
    for k, v in overrides.items():
        if k not in result:
            result[k] = v
        elif isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config_from_yaml(path: str) -> SiteConfig:
    """Load a ``SiteConfig`` from a YAML file.

    Args:
        path: Absolute or relative path to the YAML configuration file.

    Returns:
        A fully populated ``SiteConfig`` instance.

    Raises:
        FileNotFoundError: If *path* does not exist.
        yaml.YAMLError: If the file is not valid YAML.
        KeyError: If a required key is missing from the config dict.
    """
    import yaml
    with open(path, encoding="utf-8") as fh:
        d = yaml.safe_load(fh)
    return config_from_dict(d)


# ---------------------------------------------------------------------------
# Abstract adapter
# ---------------------------------------------------------------------------


class SiteAdapter(ABC):
    """Base class for all site adapters.

    Subclasses may rely entirely on the config-driven default implementations
    of ``build_search_url``, ``parse_search``, and ``parse_detail``, or
    override any of them for site-specific logic.

    Attributes:
        config: The ``SiteConfig`` describing this site's URL structure and
            CSS selectors.
    """

    def __init__(self, config: SiteConfig) -> None:
        self.config = config
        self._domain_re = re.compile(config.domain_pattern)

    @property
    def site_id(self) -> str:
        """Short slug identifying this adapter (delegates to ``config.site_id``)."""
        return self.config.site_id

    def matches_url(self, url: str) -> bool:
        """Return ``True`` if *url* belongs to this site.

        Args:
            url: A URL to test.

        Returns:
            ``True`` when the site's ``domain_pattern`` matches the URL.
        """
        return bool(self._domain_re.search(url))

    # --- Rejection detection ----------------------------------------------------

    # Phrases indicating a site-level rejection (HTTP 200 but error content).
    _REJECTION_PHRASES = (
        "too many requests",
        "rate limit",
        "temporarily unavailable",
        "service unavailable",
        "please try again later",
        "riprova più tardi",
        "troppi tentativi",
        "troppe richieste",
        "errore del server",
        "internal server error",
        "si è verificato un errore",
    )

    _ERROR_CODE_RE = re.compile(
        r"\b(?:error|errore|código)\s*(\d{3})\b", re.IGNORECASE
    )

    def detect_rejection(self, html: str) -> str | None:
        """Check if the page content indicates the site rejected the request.

        Uses lightweight regex/string checks (no DOM parsing) so it can run
        on every fetch without meaningful overhead.  ``detect_block`` in
        ``browser.py`` already handles bot-detection pages (CAPTCHA, DataDome,
        tiny responses); this method catches application-level rejections
        (rate-limit pages, error pages served as HTTP 200).

        Override in subclasses for site-specific rejection patterns.
        """
        if not html:
            return "empty response"

        # Extract title via regex (same approach as detect_block)
        title = ""
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        if title_match:
            title = title_match.group(1).strip().lower()

        # Check a slice of raw HTML for rejection phrases
        sample = html[:5000].lower()
        for phrase in self._REJECTION_PHRASES:
            if phrase in title or phrase in sample:
                return f"rejection detected: '{phrase}'"

        # Error code in title (e.g. "Error 503", "Errore 429")
        if title:
            m = self._ERROR_CODE_RE.search(title)
            if m and m.group(1) in ("403", "429", "500", "502", "503", "504"):
                return f"error code {m.group(1)} in page title"

        return None

    # --- URL building (config-driven default) ---------------------------------

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build a full search URL from normalized filters.

        Uses the config's ``search_path_template`` and ``query_param_map``.
        Override this method when the site requires non-standard URL logic.

        Args:
            filters: Normalized search parameters.

        Returns:
            A fully qualified search URL string.
        """
        from urllib.parse import urlencode

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
        if filters.sort != "rilevanza" and "sort" in qmap:
            query[qmap["sort"]] = filters.sort
        if filters.page >= 1:
            query[self.config.page_param] = filters.page

        url = self.config.base_url + path
        if query:
            url += "?" + urlencode(query)
        return url

    # --- Parsing (config-driven defaults) -------------------------------------

    def parse_search(self, html: str) -> list[ListingSummary]:
        """Parse a search results page into listing summaries.

        Default implementation uses ``SearchSelectors`` from the config.
        Override when the site requires custom extraction logic.

        Args:
            html: Raw HTML string of a search results page.

        Returns:
            List of ``ListingSummary`` objects for listings that have a URL.
        """
        soup = BeautifulSoup(html, "lxml")
        sels = self.config.search_selectors
        cards = sels.listing_card.find_all(soup)
        listings: list[ListingSummary] = []

        if not cards:
            # Diagnostic: log page title, meta robots, and body class to help diagnose
            # wrong selectors, CAPTCHAs, or redirects.
            title_tag = soup.find("title")
            body_tag = soup.find("body")
            body_class = body_tag.get("class", []) if body_tag else []
            # Capture first ~600 chars of visible body text as a hint
            body_text = body_tag.get_text(" ", strip=True)[:600] if body_tag else ""
            logger.warning(
                "DIAG [%s] 0 cards with selector %r — page title=%r body_class=%r body_text=%r",
                self.config.site_id,
                list(sels.listing_card.selectors),
                title_tag.get_text(strip=True) if title_tag else "",
                body_class,
                body_text,
            )

        url_filter = self.config.detail_url_contains
        for card in cards:
            try:
                listing = self._parse_one_card(card, sels)
                if listing.url:
                    # Skip non-listing URLs (agency pages, filter links, etc.)
                    if url_filter and url_filter not in listing.url:
                        logger.debug("Skipping non-listing URL: %s", listing.url)
                        continue
                    listings.append(listing)
            except Exception as exc:
                logger.debug("Skipping unparseable card: %s", exc)

        return listings

    def _parse_one_card(self, card: Tag, sels: SearchSelectors) -> ListingSummary:
        """Parse a single search result card element.

        Args:
            card: The card ``Tag`` element.
            sels: Search selector groups from the site config.

        Returns:
            A populated ``ListingSummary`` (``url`` may be empty on failure).
        """
        from urllib.parse import urljoin

        title_el = sels.title.find(card)
        title = extract_text(title_el)

        href = extract_attr(title_el, "href")
        if not href:
            any_link = card.select_one("a[href]")
            href = extract_attr(any_link, "href")
        if href and not href.startswith("http"):
            href = urljoin(self.config.base_url, href)

        price = extract_text(sels.price.find(card))

        features = sels.features.find_all(card)
        feature_texts = [extract_text(f) for f in features if extract_text(f)]

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
            raw_features=feature_texts,
        )

    def extract_post_date_from_search_card(
        self, card: Tag, feature_texts: list[str]
    ) -> str:
        """Extract the publication date from a search result card.

        Checks feature texts first, then falls back to all card text.

        Args:
            card: The card ``Tag`` element.
            feature_texts: Already-extracted feature strings from the card.

        Returns:
            Date string if found, otherwise ``""``.
        """
        candidates = list(feature_texts) + [card.get_text(" ", strip=True)]
        for candidate in candidates:
            post_date = extract_post_date_text(candidate)
            if post_date:
                return post_date
        return ""

    def extract_post_date_from_detail_html(self, html: str) -> str:
        """Extract the publication date from a detail page's full text.

        Args:
            html: Raw HTML of a listing detail page.

        Returns:
            Date string if found, otherwise ``""``.
        """
        soup = BeautifulSoup(html, "lxml")
        return extract_post_date_text(soup.get_text(" ", strip=True))

    def parse_detail(self, html: str, url: str) -> ListingDetail:
        """Parse a listing detail page.

        Default implementation uses ``DetailSelectors`` from the config.
        Override when the site requires custom extraction logic.

        Args:
            html: Raw HTML string of the listing detail page.
            url: Canonical URL of the listing.

        Returns:
            A populated ``ListingDetail``.
        """
        from urllib.parse import urljoin

        soup = BeautifulSoup(html, "lxml")
        sels = self.config.detail_selectors

        title = extract_text(sels.title.find(soup))
        price = extract_text(sels.price.find(soup))
        description = extract_text(sels.description.find(soup))
        address = extract_text(sels.address.find(soup))

        keys_els = sels.features_keys.find_all(soup)
        vals_els = sels.features_values.find_all(soup)
        extra_info: dict[str, str] = {}
        for k_el, v_el in zip(keys_els, vals_els):
            k = extract_text(k_el)
            v = extract_text(v_el)
            if k:
                extra_info[k] = v

        photos: list[str] = []
        for img in sels.photos.find_all(soup):
            src = extract_attr(img, "data-src") or extract_attr(img, "src")
            if src and src not in photos:
                if not src.startswith("http"):
                    src = urljoin(self.config.base_url, src)
                photos.append(src)

        energy_class = extract_text(sels.energy_class.find(soup))
        # If the CSS selector matched a broad container (garbled text), fall back to
        # the features dict — Immobiliare.it usually exposes "Classe energetica: G"
        # as a <dt>/<dd> pair, which is already parsed into extra_info above.
        if energy_class and not re.fullmatch(r'[A-Ga-g][1-4]?', energy_class.strip()):
            _match = re.search(r'\b([A-Ga-g][1-4]?)\b', energy_class)
            energy_class = _match.group(1).upper() if _match else ""
        if not energy_class:
            _ENERGY_KEYS = {"classe energetica", "efficienza energetica", "classe energia",
                            "energy class", "classe energetica globale"}
            for k, v in extra_info.items():
                if k.lower().strip() in _ENERGY_KEYS or "energe" in k.lower():
                    _m = re.search(r'\b([A-Ga-g][1-4]?)\b', v)
                    if _m:
                        energy_class = _m.group(1).upper()
                        break
        agency = extract_text(sels.agency.find(soup))
        post_date = self.extract_post_date_from_detail_html(html)

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
            extra_info=extra_info,
            photos=photos[:20],
            energy_class=energy_class,
            agency=agency,
            post_date=post_date,
            costs=costs,
        )
