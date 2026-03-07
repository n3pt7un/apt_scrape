"""
sites.immobiliare — Adapter for Immobiliare.it

URL pattern: /{operation}-{property_type}/{city}/?prezzoMinimo=X&prezzoMassimo=Y&...
Detail URL:  /annunci/{id}/
Config:       sites/configs/immobiliare.yaml
"""

from pathlib import Path
from urllib.parse import urlencode, urljoin

import re

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
    """Immobiliare.it — Italy's #1 real estate portal.

    Uses the default config-driven parsing. Override methods here only
    if Immobiliare needs site-specific logic beyond selector changes.
    """

    def __init__(self):
        super().__init__(load_config_from_yaml(_CONFIG_PATH))

    def build_search_url(self, filters: SearchFilters) -> str:
        """Build Immobiliare URL with site-specific sort handling.

        Immobiliare uses `criterio=data&ordine=desc` for newest listings,
        not `ordine=piu-recenti`.
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
        query = {}

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
        """Parse a single listing card, handling aria-label for features."""
        from urllib.parse import urljoin

        title_el = sels.title.find(card)
        title = extract_text(title_el)

        # URL — try href from the title link, or from any link in the card
        href = extract_attr(title_el, "href")
        if not href:
            any_link = card.select_one("a[href]")
            href = extract_attr(any_link, "href")
        if href and not href.startswith("http"):  # type: ignore[arg-type]
            href = urljoin(self.config.base_url, href)

        price = extract_text(sels.price.find(card))

        # For Immobiliare, features are in aria-label
        features_els = sels.features.find_all(card)
        feature_texts = []
        for f in features_els:
            aria = f.get("aria-label", "").strip()
            if aria:
                feature_texts.append(aria)
            else:
                # fallback to text
                txt = extract_text(f)
                if txt:
                    feature_texts.append(txt)

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
            features_raw=feature_texts,
        )

    def parse_detail(self, html: str, url: str) -> ListingDetail:
        """Immobiliare-specific detail page parser.

        Improvements over the generic base implementation:
        - address: joins all LocationInfo_location spans (street, neighbourhood, city)
        - price: extracts only the primary price, ignoring crossed-out original
        - size / floor: promoted to dedicated top-level fields
        - photos: uses full-resolution URL (replaces /m-c.jpg with /r.jpg)
        - costs: only the financial extras section (Spese condominio, Cauzione)
        - metadata: all remaining key/value feature pairs
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")

        # ── title ────────────────────────────────────────────────
        title_el = (soup.select_one("h1[class*='Title_title']") or
                    soup.select_one("h1[class*='title']") or
                    soup.select_one("h1"))
        title = extract_text(title_el)

        # ── address: join all LocationInfo spans in DOM order ────
        loc_spans = soup.select("span[class*='LocationInfo_location']")
        if loc_spans:
            # order is city → neighbourhood → street; reverse for human-readable
            parts = [s.get_text(strip=True) for s in reversed(loc_spans) if s.get_text(strip=True)]
            address = ", ".join(parts)
        else:
            address = extract_text(self.config.detail_selectors.address.find(soup))

        # ── price: first direct <span> inside the price container ─
        price = ""
        price_container = (soup.select_one("div[class*='Price_price']") or
                           soup.select_one("[class*='overview__price']"))
        if price_container:
            for child in price_container.children:
                if getattr(child, 'name', None) == 'span':
                    txt = child.get_text(strip=True)
                    if txt:
                        price = txt
                        break
        if not price:
            price = extract_text(self.config.detail_selectors.price.find(soup))

        # ── description ──────────────────────────────────────────
        description = extract_text(self.config.detail_selectors.description.find(soup))

        # ── main features dl (Caratteristiche) ───────────────────
        # We want only the *first* dl — it holds the core property facts.
        # Subsequent dls are surface-area breakdowns or price/cost sections.
        metadata: dict[str, str] = {}
        first_dl = soup.select_one("dl[class*='FeaturesGrid']") or soup.select_one("dl")
        if first_dl:
            dts = first_dl.select("dt")
            dds = first_dl.select("dd")
            for dt, dd in zip(dts, dds):
                k = dt.get_text(strip=True)
                v = dd.get_text(strip=True)
                if k:
                    metadata[k] = v

        # ── size & floor: promoted from metadata ─────────────────
        size_raw = metadata.get("Superficie", "")
        # Strip commercial-area suffix: "56 m² | commerciale 56,6 m²" → "56 m²"
        size = re.split(r"\s*\|", size_raw)[0].strip()
        floor = metadata.get("Piano", "")

        # ── photos: full-resolution ───────────────────────────────
        photos: list[str] = []
        for img in soup.select("[class*='ListingPhotos'] img"):
            src = img.get("src") or img.get("data-src", "")
            if src:
                # swap medium-crop thumbnail for full-resolution variant
                src = re.sub(r"/m-c\.jpg$", "/r.jpg", src)
                src = re.sub(r"/s-c\.jpg$", "/r.jpg", src)
                if src not in photos:
                    photos.append(src)
        # fallback to config-driven selector
        if not photos:
            for img in self.config.detail_selectors.photos.find_all(soup):
                src = extract_attr(img, "data-src") or extract_attr(img, "src")
                if src and src not in photos:
                    photos.append(src)

        # ── energy class ─────────────────────────────────────────
        energy_class = extract_text(self.config.detail_selectors.energy_class.find(soup))

        # ── agency ───────────────────────────────────────────────
        agency = extract_text(self.config.detail_selectors.agency.find(soup))

        # ── post date ────────────────────────────────────────────
        post_date = extract_post_date_text(soup.get_text(" ", strip=True))

        # ── costs: only the "Dettaglio dei costi" dl ─────────────
        # Find the dl that follows a sibling/header containing "costi"
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
            metadata=metadata,
            photos=photos[:20],
            energy_class=energy_class,
            agency=agency,
            post_date=post_date,
            costs=costs,
        )
