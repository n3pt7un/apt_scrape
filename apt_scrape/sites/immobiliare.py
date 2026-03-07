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
    Tag,
    classify_feature,
    extract_attr,
    extract_post_date_text,
    extract_text,
    load_config_from_yaml,
)

_CONFIG_PATH = Path(__file__).parent / "configs" / "immobiliare.yaml"


class ImmobiliareAdapter(SiteAdapter):
    """Adapter for Immobiliare.it — Italy's largest real estate portal.

    Overrides ``build_search_url`` to handle Immobiliare's non-standard sort
    parameters, ``_parse_one_card`` to read feature data from ``aria-label``
    attributes, and ``parse_detail`` for full-resolution photos, composite
    address assembly, and dedicated cost-section extraction.
    """

    def __init__(self) -> None:
        super().__init__(load_config_from_yaml(_CONFIG_PATH))

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
        - **photos**: Rewrites thumbnail URLs to full-resolution (replacing
          ``/m-c.jpg`` and ``/s-c.jpg`` suffixes with ``/r.jpg``).
        - **costs**: Extracts only the financial extras ``<dl>`` (the one
          preceded by a sibling containing "costi" or "prezzo").

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

        description = extract_text(self.config.detail_selectors.description.find(soup))

        # Main features <dl> (first one = core property facts).
        extra_info: dict[str, str] = {}
        first_dl = soup.select_one("dl[class*='FeaturesGrid']") or soup.select_one("dl")
        if first_dl:
            for dt, dd in zip(first_dl.select("dt"), first_dl.select("dd")):
                k = dt.get_text(strip=True)
                v = dd.get_text(strip=True)
                if k:
                    extra_info[k] = v

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
                src = re.sub(r"/m-c\.jpg$", "/r.jpg", src)
                src = re.sub(r"/s-c\.jpg$", "/r.jpg", src)
                if src not in photos:
                    photos.append(src)
        if not photos:
            for img in self.config.detail_selectors.photos.find_all(soup):
                src = extract_attr(img, "data-src") or extract_attr(img, "src")
                if src and src not in photos:
                    photos.append(src)

        energy_class = extract_text(self.config.detail_selectors.energy_class.find(soup))
        agency = extract_text(self.config.detail_selectors.agency.find(soup))
        post_date = extract_post_date_text(soup.get_text(" ", strip=True))

        # Costs: only the <dl> preceded by a sibling mentioning "costi" or "prezzo".
        costs: dict[str, str] = {}
        for dl in soup.select("dl"):
            prev = dl.find_previous_sibling()
            prev_txt = (prev.get_text(strip=True) if prev else "").lower()
            if "costi" in prev_txt or "prezzo" in prev_txt:
                for dt, dd in zip(dl.select("dt"), dl.select("dd")):
                    k = dt.get_text(strip=True)
                    v = dd.get_text(strip=True)
                    if k:
                        costs[k] = v

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
