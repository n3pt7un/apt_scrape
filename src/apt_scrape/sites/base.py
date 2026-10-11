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

import copy
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

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
    "clean_agency_name",
    "config_from_dict",
    "config_to_dict",
    "deep_merge",
    "extract_agency",
    "extract_attr",
    "extract_block_text",
    "extract_post_date_text",
    "extract_text",
    "load_config_from_yaml",
    "normalize_energy_class",
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


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def extract_text(element: Tag | None, default: str = "") -> str:
    """Safely extract single-line text from a BeautifulSoup element.

    Text nodes are joined with a space (so ``<b>Bilocale</b>via X`` does not
    glue into ``Bilocalevia X``) and whitespace is collapsed; the space an
    inline tag boundary leaves before punctuation or a ``/unit`` is dropped.

    Args:
        element: A ``Tag`` or ``None``.
        default: Value returned when *element* is ``None``.

    Returns:
        Stripped text content, or *default*.
    """
    if element is None:
        return default
    text = re.sub(r"\s+", " ", element.get_text(" ", strip=True))
    return re.sub(r"\s+(?=[,.;:!?)]|/[^\s/])", "", text).strip()


# Paragraph-like blocks end with a blank line; other blocks end their line.
_PARAGRAPH_TAGS = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "ul", "ol"]
_LINE_TAGS = ["div", "li", "section", "article", "header", "footer", "tr", "dt", "dd"]


def extract_block_text(element: Tag | None, default: str = "") -> str:
    """Extract multi-line text, keeping the paragraph and line breaks a browser shows.

    ``<br>`` becomes a newline, every block element ends its line and
    paragraphs are separated by a blank line, while inline tags (``<b>``,
    ``<span>``) stay on their line. Source-code whitespace inside text is
    collapsed like HTML rendering does, and runs of blank lines shrink to one.

    Args:
        element: A ``Tag`` or ``None``.
        default: Value returned when *element* is ``None``.

    Returns:
        Text with ``\n`` line breaks, or *default*.
    """
    if element is None:
        return default
    el = copy.copy(element)
    for text_node in el.find_all(string=True):
        # Comments, scripts and CDATA are other NavigableString subclasses.
        if type(text_node) is NavigableString:
            text_node.replace_with(re.sub(r"\s+", " ", str(text_node)))
    for br in el.find_all("br"):
        br.replace_with("\n")
    for block in el.find_all(_PARAGRAPH_TAGS):
        block.insert_after("\n\n")
    for block in el.find_all(_LINE_TAGS):
        block.insert_after("\n")
    lines = [line.strip() for line in el.get_text("").split("\n")]
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return text or default


# UI labels that agency boxes render next to the name (buttons, headings).
_AGENCY_UI_SPLIT = re.compile(
    r"\n|(?i:mostra\s+telefono|mostra\s+numero|invia\s+messaggio|contatta\s+l'agenzia|contatta)"
)
_AGENCY_UI_LINES = {"agenzia", "agente", "inserzionista", "referente", "chiama", "scrivi"}


def clean_agency_name(text: str) -> str:
    """Return the agency name from a scraped agency block.

    Drops UI labels ("Agenzia", "Mostra Telefono", ...) and repeated names,
    including in older scrapes where they were glued into one string, e.g.
    ``"AgenziaBologna ImmobiliareMostra Telefono"`` -> ``"Bologna Immobiliare"``.

    Args:
        text: Raw agency text; lines may be separated by ``\n``.

    Returns:
        The first remaining name, or ``""``.
    """
    names: list[str] = []
    for part in _AGENCY_UI_SPLIT.split(text or ""):
        part = re.sub(r"\s+", " ", part).strip(" -|·,")
        # "Agenzia" glued to the name ("AgenziaBologna ...") is the box label.
        part = re.sub(r"^Agenzia(?=[A-ZÀ-Ý])", "", part).strip()
        if not part or part.lower() in _AGENCY_UI_LINES:
            continue
        if part.lower() not in (n.lower() for n in names):
            names.append(part)
    return names[0] if names else ""


def extract_agency(element: Tag | None) -> str:
    """Extract a clean agency name from an agency/contact box element."""
    if element is None:
        return ""
    el = copy.copy(element)
    for ui in el.select("button, a[role=button], [class*='phone' i]"):
        ui.decompose()
    return clean_agency_name(el.get_text("\n", strip=True))


# Statuses portals show instead of a class; kept verbatim.
_ENERGY_PENDING = ("attesa", "non classificabile", "esente", "in fase", "non soggett", "non indicat")
_ENERGY_CLASS = r"[A-G](?:[1-4]|\+{1,3})?"


def normalize_energy_class(text: str) -> str:
    """Normalize scraped energy-class text.

    Returns an uppercase class (``"A4"``, ``"B"``, ``"A+"``), a short pending
    status verbatim (``"In attesa di certificazione"``), or ``""``. Only an
    uppercase class letter counts when the value is free text, so the Italian
    words "e"/"a" (or "A norma di legge") are not read as classes.
    """
    t = re.sub(r"\s+", " ", text or "").strip()
    if not t:
        return ""
    if len(t) <= 60 and any(p in t.lower() for p in _ENERGY_PENDING):
        return t
    m = re.fullmatch(r"(?i:classe(?:\s+energetica)?\s*[:\-]?\s*)?([A-Ga-g](?:[1-4]|\+{1,3})?)", t)
    if m:
        return m.group(1).upper()
    m = re.search(rf"(?i:classe(?:\s+energetica)?|\bape)\s*[:\-]?\s*({_ENERGY_CLASS})(?![\w+])", t)
    if m:
        return m.group(1)
    # "G 175,00 kWh/m² anno" / "G (175 kWh)": a leading class then a number or separator.
    m = re.match(rf"({_ENERGY_CLASS})(?=$|\s*[\d|(,\-–])", t)
    return m.group(1) if m else ""


def _energy_from_class_attr(element: Tag | None) -> str:
    """Read a class encoded in a CSS class name (Idealista: ``icon-energy-c-8`` -> ``C``)."""
    if element is None:
        return ""
    m = re.search(r"energy-([a-g])(?:[-_ ]|$)", " ".join(element.get("class", [])))
    return m.group(1).upper() if m else ""


_ENERGY_KEYS = {"classe energetica", "efficienza energetica", "classe energia",
                "energy class", "classe energetica globale"}


def energy_class_from_features(extra_info: dict[str, str]) -> str:
    """Find the energy class among feature label/value pairs."""
    for k, v in extra_info.items():
        if k.lower().strip() in _ENERGY_KEYS or "energ" in k.lower():
            energy = normalize_energy_class(v)
            if energy:
                return energy
    return ""


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


def _today_rome() -> date:
    """Today's date in Italy (the portals' timezone), falling back to local time."""
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo("Europe/Rome")).date()
    except Exception:
        return date.today()


def extract_post_date_text(text: str, allow_bare_relative: bool = False) -> str:
    """Extract a publication or update date string from arbitrary text.

    Tries progressively less specific patterns; returns the first match.
    Relative dates ("pubblicato oggi") are resolved to an absolute date at
    scrape time, so a stored value never stays "oggi" forever.

    Args:
        text: Arbitrary text, typically from a card or full page.
        allow_bare_relative: Also accept a lone "oggi"/"ieri". Only safe for a
            short card feature string: in free text it matches phrases such
            as "libero da oggi".

    Returns:
        Date string (e.g. ``"pubblicato il 12/03/2025"``,
        ``"Annuncio aggiornato il 11/10/2026"``), or ``""`` if none is found.
    """
    if not text:
        return ""

    dated = re.search(
        r"((?:annuncio\s+)?(?:pubblicato|inserito|aggiornato)\s+(?:il\s+)?"
        r"\d{1,2}/\d{1,2}/\d{2,4})",
        text,
        flags=re.IGNORECASE,
    )
    if dated:
        return re.sub(r"\s+", " ", dated.group(1)).strip()

    relative = re.search(
        r"((?:annuncio\s+)?(?:pubblicato|inserito|aggiornato))\s+(oggi|ieri)\b",
        text,
        flags=re.IGNORECASE,
    )
    if relative:
        day = _today_rome() - timedelta(days=1 if relative.group(2).lower() == "ieri" else 0)
        prefix = re.sub(r"\s+", " ", relative.group(1)).strip()
        return f"{prefix} il {day:%d/%m/%Y}"

    if allow_bare_relative:
        bare = re.search(r"\b(oggi|ieri)\b", text, flags=re.IGNORECASE)
        if bare:
            day = _today_rome() - timedelta(days=1 if bare.group(1).lower() == "ieri" else 0)
            return f"{day:%d/%m/%Y}"

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


_COST_LABEL_RE = re.compile(r"spese|condomin|cauzione|deposito|canone|prezzo", re.IGNORECASE)


def _features_from_list(elements: list[Tag]) -> dict[str, str]:
    """Turn a flat feature list into label/value pairs.

    ``"Spese condominiali: 50 €"`` becomes a pair; items without a colon
    (``"Balcone"``, ``"2 bagni"``) are joined under ``"Caratteristiche"``.
    """
    extra_info: dict[str, str] = {}
    items: list[str] = []
    for el in elements:
        text = extract_text(el)
        if not text:
            continue
        if ":" in text:
            key, value = (part.strip() for part in text.split(":", 1))
            if key and value:
                extra_info.setdefault(key, value)
                continue
        if text not in items:
            items.append(text)
    if items:
        extra_info.setdefault("Caratteristiche", ", ".join(items))
    return extra_info


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

        for card in cards:
            try:
                listing = self._parse_one_card(card, sels)
                if listing.url:
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

        Checks feature texts first (where a lone "oggi"/"ieri" is a date),
        then falls back to all card text (which includes the description
        snippet, so a bare "oggi" there is not trusted).

        Args:
            card: The card ``Tag`` element.
            feature_texts: Already-extracted feature strings from the card.

        Returns:
            Date string if found, otherwise ``""``.
        """
        for feature in feature_texts:
            post_date = extract_post_date_text(feature, allow_bare_relative=True)
            if post_date:
                return post_date
        return extract_post_date_text(card.get_text(" ", strip=True))

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
        description = extract_block_text(sels.description.find(soup))
        address = extract_text(sels.address.find(soup))

        keys_els = sels.features_keys.find_all(soup)
        if sels.features_keys.selectors == sels.features_values.selectors:
            # Same selectors for keys and values: the site renders features as a
            # flat list (Idealista), not label/value pairs.
            extra_info = _features_from_list(keys_els)
        else:
            vals_els = sels.features_values.find_all(soup)
            extra_info = {}
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

        # The selector may match a broad container (garbled text) or encode the
        # class in a CSS class name; fall back to the features' label/value pairs.
        energy_el = sels.energy_class.find(soup)
        energy_class = (
            _energy_from_class_attr(energy_el)
            or normalize_energy_class(extract_text(energy_el))
            or energy_class_from_features(extra_info)
        )
        agency = extract_agency(sels.agency.find(soup))
        post_date = extract_post_date_text(soup.get_text(" ", strip=True))

        cost_keys = sels.costs_keys.find_all(soup)
        cost_vals = sels.costs_values.find_all(soup)
        costs: dict[str, str] = {}
        for k_el, v_el in zip(cost_keys, cost_vals):
            k = extract_text(k_el)
            v = extract_text(v_el)
            if k:
                costs[k] = v
        if not costs:
            # No dedicated costs section (Casa.it): pick the cost-like features.
            costs = {k: v for k, v in extra_info.items() if _COST_LABEL_RE.search(k)}

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
