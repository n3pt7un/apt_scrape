"""apt_scrape.sites.immobiliare — Adapter for Immobiliare.it.

URL pattern: ``/{operation}-{property_type}/{city}/?prezzoMinimo=X&...``
Detail URL:  ``/annunci/{id}/``
Config:      ``apt_scrape/sites/configs/immobiliare.yaml``
"""

import re
from pathlib import Path
from urllib.parse import urlencode, urljoin

from .base import (
    ListingDetail,
    ListingSummary,
    SearchFilters,
    SearchSelectors,
    SiteAdapter,
    SiteConfig,
    Tag,
    classify_feature,
    energy_class_from_features,
    extract_agency,
    extract_attr,
    extract_block_text,
    extract_post_date_text,
    extract_text,
    load_config_from_yaml,
    normalize_energy_class,
)

_CONFIG_PATH = Path(__file__).parent / "configs" / "immobiliare.yaml"

# Energy class written in the description ("APE: G", "classe energetica E").
_DESCRIPTION_ENERGY_RE = re.compile(r"(?i:\b(?:APE|classe\s+energetica))\s*[:“\"']?\s*([A-G][1-4]?)\b")


def _full_res_photo(src: str) -> str:
    """Rewrite an im-cdn size variant (``m-c.jpg``, ``cover-m-c.jpg``, ``xxs-c.jpg``...) to ``r.jpg``."""
    if "im-cdn.it/image/" in src:
        return re.sub(r"/[a-z-]+\.jpg$", "/r.jpg", src)
    return src


def _dd_text(dd: Tag) -> str:
    """Value of a ``<dd>``; a ``<dd>`` made only of chip elements is comma-joined."""
    chips = [extract_text(c) for c in dd.find_all(["li", "span"], recursive=False)]
    chips = [c for c in chips if c]
    own_text = "".join(dd.find_all(string=True, recursive=False)).strip()
    if len(chips) > 1 and not own_text:
        return ", ".join(chips)
    return extract_text(dd)


def _other_features(soup) -> str:
    """Return the "Altre caratteristiche" chips (cantina, fibra ottica, ...) comma-joined."""
    items: list[str] = []
    for label in soup.find_all(string=re.compile(r"^\s*Altre caratteristiche\s*$", re.IGNORECASE)):
        heading = label.parent
        container = heading.find_next_sibling() if heading is not None else None
        if container is None:
            continue
        leaves = container.select("li") or [
            el for el in container.find_all(["span", "div"]) if not el.find(["span", "div"])
        ]
        for leaf in leaves:
            text = extract_text(leaf)
            if text and text not in items:
                items.append(text)
    return ", ".join(items)


class ImmobiliareAdapter(SiteAdapter):
    """Adapter for Immobiliare.it — Italy's largest real estate portal.

    Overrides ``build_search_url`` to handle Immobiliare's non-standard sort
    parameters, ``_parse_one_card`` to read feature data from ``aria-label``
    attributes, and ``parse_detail`` for full-resolution photos, composite
    address assembly, and dedicated cost-section extraction.
    """

    def __init__(self, config: SiteConfig | None = None) -> None:
        if config is None:
            config = load_config_from_yaml(_CONFIG_PATH)
        super().__init__(config)

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build an Immobiliare search URL with site-specific sort handling.

        Immobiliare encodes the "newest first" sort as ``criterio=data&ordine=desc``
        rather than a single ``ordine=piu-recenti`` parameter.

        Args:
            filters: Normalized search parameters.

        Returns:
            Fully qualified Immobiliare search URL.
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
        query: dict = {}

        # A 0 bound means "no filter". Immobiliare redirects URLs carrying e.g.
        # superficieMinima=0 to the canonical URL and drops ``pag`` on the way,
        # so every page would silently become page 1.
        for field in ("min_price", "max_price", "min_sqm", "max_sqm", "min_rooms", "max_rooms"):
            value = getattr(filters, field)
            if value and field in qmap:
                query[qmap[field]] = value
        if filters.published_within and "published_within" in qmap:
            query[qmap["published_within"]] = filters.published_within

        sort_value = (filters.sort or "").strip().lower()
        if sort_value in {"piu-recenti", "recenti", "data", "newest", "latest"}:
            query["criterio"] = "data"
            query["ordine"] = "desc"
        elif sort_value and sort_value != "rilevanza" and "sort" in qmap:
            query[qmap["sort"]] = filters.sort

        if filters.page >= 1:
            query[self.config.page_param] = filters.page

        url = self.config.base_url + path
        if query:
            url += "?" + urlencode(query)
        return url

    def parse_search(self, html: str) -> list[ListingSummary]:
        """Parse search results, keeping only cards that link to a listing.

        The broad ``li.nd-list__item`` fallback selector also matches navigation
        and footer list items; those resolve to non-listing URLs (home page,
        filter links, ``/info/...``) and are dropped here.
        """
        return [ls for ls in super().parse_search(html) if "/annunci/" in ls.url]

    def _parse_one_card(self, card: Tag, sels: SearchSelectors) -> ListingSummary:
        """Parse a single Immobiliare search result card.

        Reads feature data from ``aria-label`` attributes, falling back to
        element text when the attribute is absent.

        Args:
            card: The card ``Tag`` element.
            sels: Search selector groups from the site config.

        Returns:
            A populated ``ListingSummary``.
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

        features_els = sels.features.find_all(card)
        feature_texts: list[str] = []
        for f in features_els:
            aria = f.get("aria-label", "").strip()
            feature_texts.append(aria if aria else extract_text(f))
        feature_texts = [t for t in feature_texts if t]

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

        thumbnail = extract_attr(sels.thumbnail.find(card), "src")
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

    def parse_detail(self, html: str, url: str) -> ListingDetail:
        """Parse an Immobiliare listing detail page.

        Improvements over the generic base implementation:

        - **address**: Joins all ``LocationInfo_location`` spans in reverse DOM
          order to produce a human-readable ``street, neighbourhood, city``
          string.
        - **price**: Extracts only the primary price span, ignoring any
          crossed-out original price.
        - **size / floor**: Promoted to dedicated top-level fields from
          ``extra_info``.
        - **photos**: Rewrites every im-cdn size variant (``m-c.jpg``,
          ``cover-m-c.jpg``, ``xxs-c.jpg``, ...) to full-resolution ``r.jpg``.
        - **costs**: Extracts only the financial extras ``<dl>`` (the one
          preceded by a sibling containing "costi" or "prezzo").
        - **extra_info**: Merges every other ``<dl>`` (main facts, energy
          section, ...) plus the "Altre caratteristiche" chips.
        - **energy_class**: Selector text, else the features, else an "APE: X"
          mention in the description.

        Args:
            html: Raw HTML of the Immobiliare listing detail page.
            url: Canonical URL of the listing.

        Returns:
            A fully populated ``ListingDetail``.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        # Title
        title_el = (
            soup.select_one("h1[class*='Title_title']")
            or soup.select_one("h1[class*='title']")
            or soup.select_one("h1")
        )
        title = extract_text(title_el)

        # Address: join LocationInfo spans in reverse DOM order for readability.
        loc_spans = soup.select("span[class*='LocationInfo_location']")
        if loc_spans:
            parts = [s.get_text(strip=True) for s in reversed(loc_spans) if s.get_text(strip=True)]
            address = ", ".join(parts)
        else:
            address = extract_text(self.config.detail_selectors.address.find(soup))

        # Price: first direct <span> child of the price container.
        price = ""
        price_container = soup.select_one("div[class*='Price_price']") or soup.select_one(
            "[class*='overview__price']"
        )
        if price_container:
            for child in price_container.children:
                if getattr(child, "name", None) == "span":
                    txt = child.get_text(strip=True)
                    if txt:
                        price = txt
                        break
        if not price:
            price = extract_text(self.config.detail_selectors.price.find(soup))

        description = extract_block_text(self.config.detail_selectors.description.find(soup))

        # Costs: only the <dl> preceded by a sibling mentioning "costi" or "prezzo".
        costs: dict[str, str] = {}
        cost_dls: set[int] = set()
        for dl in soup.select("dl"):
            prev = dl.find_previous_sibling()
            prev_txt = (prev.get_text(strip=True) if prev else "").lower()
            if "costi" in prev_txt or "prezzo" in prev_txt:
                cost_dls.add(id(dl))
                for dt, dd in zip(dl.select("dt"), dl.select("dd")):
                    k = extract_text(dt)
                    if k:
                        costs[k] = extract_text(dd)

        # Features: every other <dl> (core facts first, then e.g. the energy
        # section). The first section wins when a label repeats.
        extra_info: dict[str, str] = {}
        for dl in soup.select("dl"):
            if id(dl) in cost_dls:
                continue
            for dt, dd in zip(dl.select("dt"), dl.select("dd")):
                k = extract_text(dt)
                if k:
                    extra_info.setdefault(k, _dd_text(dd))
        if "Altre caratteristiche" not in extra_info:
            other = _other_features(soup)
            if other:
                extra_info["Altre caratteristiche"] = other

        # Promote size and floor to top-level fields.
        size_raw = extra_info.get("Superficie", "")
        # Strip commercial-area suffix: "56 m² | commerciale 56,6 m²" → "56 m²"
        size = re.split(r"\s*\|", size_raw)[0].strip()
        floor = extra_info.get("Piano", "")

        # Photos: rewrite thumbnail URLs to full-resolution.
        photos: list[str] = []
        for img in soup.select("[class*='ListingPhotos'] img"):
            src = img.get("src") or img.get("data-src", "")
            if src:
                src = _full_res_photo(src)
                if src not in photos:
                    photos.append(src)
        if not photos:
            for img in self.config.detail_selectors.photos.find_all(soup):
                src = extract_attr(img, "data-src") or extract_attr(img, "src")
                if src:
                    src = _full_res_photo(src)
                    if src not in photos:
                        photos.append(src)

        energy_class = (
            normalize_energy_class(extract_text(self.config.detail_selectors.energy_class.find(soup)))
            or energy_class_from_features(extra_info)
        )
        if not energy_class:
            m = _DESCRIPTION_ENERGY_RE.search(description)
            energy_class = m.group(1) if m else ""
        agency = extract_agency(self.config.detail_selectors.agency.find(soup))
        post_date = extract_post_date_text(soup.get_text(" ", strip=True))

        return ListingDetail(
            source=self.config.display_name,
            url=url,
            title=title,
            price=price,
            description=description,
            address=address,
            size=size,
            floor=floor,
            extra_info=extra_info,
            photos=photos[:20],
            energy_class=energy_class,
            agency=agency,
            post_date=post_date,
            costs=costs,
        )
