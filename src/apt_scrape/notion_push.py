"""apt_scrape.notion_push — Push scraped listings into a Notion Apartments database.

Creates pages in the Apartments DB with relational links to Areas and Agencies.
Deduplicates by Listing URL. Adds new schema properties on first run via
_ensure_schema(). Geocodes the address field via Nominatim to populate the
Place property for map view.

Required env vars:
    NOTION_API_KEY              — Notion integration token
    NOTION_APARTMENTS_DB_ID     — Apartments database ID
    NOTION_AREAS_DB_ID          — Areas database ID
    NOTION_AGENCIES_DB_ID       — Agencies database ID
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import click
import httpx
from notion_client import AsyncClient

from apt_scrape.sites.base import normalize_energy_class


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_price_numeric(price_str: str) -> Optional[float]:
    """Extract the first numeric value from a price string (same rule as backend.parsing.parse_price).

    A '.' or ',' between a digit and exactly three digits is a thousands separator
    ('1.200', '1,200'); any other ',' is a decimal comma ('1.200,50').
    """
    if not price_str:
        return None
    cleaned = re.sub(r"(?<=\d)[.,](?=\d{3}(?!\d))", "", price_str).replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", cleaned)
    return float(m.group(0)) if m else None


def _parse_sqm_numeric(sqm_str: str) -> Optional[float]:
    """Extract the numeric value from a sqm string like '65 m²'."""
    if not sqm_str:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", sqm_str)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _deslugify_area(slug: str) -> str:
    """Convert 'porta-venezia' → 'Porta Venezia'."""
    return " ".join(word.capitalize() for word in slug.split("-"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _score_to_stars(score: int) -> str:
    """Map a 0–100 integer score to a star-emoji string."""
    if score < 20:
        return "⭐"
    if score < 40:
        return "⭐⭐"
    if score < 60:
        return "⭐⭐⭐"
    if score < 80:
        return "⭐⭐⭐⭐"
    return "⭐⭐⭐⭐⭐"


_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Nominatim's usage policy allows at most one request per second.
_NOMINATIM_INTERVAL_SEC = 1.1
_geocode_cache: dict[str, Optional[tuple[float, float]]] = {}
_last_geocode_at = 0.0
_geocode_lock = asyncio.Lock()


async def _geocode_address(
    address: str, client: Optional[httpx.AsyncClient] = None
) -> Optional[tuple[float, float]]:
    """Return (lat, lon) for *address* using Nominatim, or None on failure.

    Definitive answers (found / not found) are cached in-process; a network
    error is not, so a later push can retry it. Requests are spaced by
    ``_NOMINATIM_INTERVAL_SEC``. Pass *client* to reuse one connection pool.
    """
    global _last_geocode_at
    if not address:
        return None
    if address in _geocode_cache:
        return _geocode_cache[address]
    async with _geocode_lock:
        wait = _NOMINATIM_INTERVAL_SEC - (time.monotonic() - _last_geocode_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_geocode_at = time.monotonic()
        try:
            if client is None:
                async with httpx.AsyncClient() as own_client:
                    resp = await _nominatim_get(own_client, address)
            else:
                resp = await _nominatim_get(client, address)
            data = resp.json()
        except Exception as exc:
            click.echo(f"  [warn] Geocoding failed for '{address}': {exc}", err=True)
            return None
    result: Optional[tuple[float, float]] = (
        (float(data[0]["lat"]), float(data[0]["lon"])) if data else None
    )
    _geocode_cache[address] = result
    return result


async def _nominatim_get(client: httpx.AsyncClient, address: str) -> httpx.Response:
    resp = await client.get(
        _NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1},
        headers={"User-Agent": "apt_scrape/1.0 (apartment hunter)"},
        timeout=10.0,
    )
    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# Schema setup
# ---------------------------------------------------------------------------

_NEW_PROPERTIES = {
    "Source": {"select": {}},
    "AI Score": {"number": {"format": "number"}},
    "AI Reason": {"rich_text": {}},
    "Energy Class": {"select": {}},
    "Scraped At": {"date": {}},
}


async def _ensure_schema(client: AsyncClient, db_id: str) -> None:
    """Add new properties to the Apartments DB if they don't already exist."""
    db = await client.databases.retrieve(database_id=db_id)
    existing = set(db.get("properties", {}).keys())
    missing = {k: v for k, v in _NEW_PROPERTIES.items() if k not in existing}
    if missing:
        await client.databases.update(database_id=db_id, properties=missing)
        click.echo(f"Added {len(missing)} new properties to Apartments DB: {list(missing)}", err=True)


# ---------------------------------------------------------------------------
# Relation lookups
# ---------------------------------------------------------------------------


async def _find_area_page_id(
    client: AsyncClient,
    areas_db_id: str,
    area_slug: str,
    cache: dict,
) -> Optional[str]:
    """Return the Notion page ID for the given area slug, or None."""
    if area_slug in cache:
        return cache[area_slug]
    area_name = _deslugify_area(area_slug)
    resp = await client.databases.query(
        database_id=areas_db_id,
        filter={"property": "Area Name", "title": {"equals": area_name}},
    )
    page_id = resp["results"][0]["id"] if resp["results"] else None
    if not page_id:
        click.echo(f"  [warn] No Areas page found for '{area_name}'", err=True)
    cache[area_slug] = page_id
    return page_id


async def _find_or_create_agency_page_id(
    client: AsyncClient,
    agencies_db_id: str,
    agency_name: str,
    cache: dict,
) -> Optional[str]:
    """Return the Notion page ID for the agency, creating it if necessary."""
    if not agency_name:
        return None
    if agency_name in cache:
        return cache[agency_name]
    resp = await client.databases.query(
        database_id=agencies_db_id,
        filter={"property": "Agency Name", "title": {"equals": agency_name}},
    )
    if resp["results"]:
        page_id = resp["results"][0]["id"]
    else:
        new_page = await client.pages.create(
            parent={"database_id": agencies_db_id},
            properties={
                "Agency Name": {"title": [{"text": {"content": agency_name}}]},
                "Status": {"select": {"name": "⚪ Not Yet Contacted"}},
            },
        )
        page_id = new_page["id"]
        click.echo(f"  Created new Agency page: {agency_name}", err=True)
    cache[agency_name] = page_id
    return page_id


async def _is_duplicate(client: AsyncClient, apartments_db_id: str, listing_url: str) -> Optional[str]:
    """Return existing page ID if listing URL already in DB, else None."""
    resp = await client.databases.query(
        database_id=apartments_db_id,
        filter={"property": "Listing URL", "url": {"equals": listing_url}},
    )
    if resp["results"]:
        return resp["results"][0]["id"]
    return None


# URLs that mark_notion_duplicates found absent from Notion -> monotonic check
# time. push_listings trusts a recent negative check instead of querying the
# same URL again. Bounded by the TTL; an entry is dropped once the URL is pushed.
_DUP_CHECK_TTL_SEC = 3600.0
_recent_negative_checks: dict[str, float] = {}


def _recently_checked(url: str) -> bool:
    checked_at = _recent_negative_checks.get(url)
    return checked_at is not None and time.monotonic() - checked_at < _DUP_CHECK_TTL_SEC


# ---------------------------------------------------------------------------
# Property builder
# ---------------------------------------------------------------------------


def _build_properties(
    listing: dict,
    area_page_id: Optional[str],
    agency_page_id: Optional[str],
    lat_lon: Optional[tuple[float, float]] = None,
) -> dict:
    """Build the Notion page properties dict from a listing dict.

    Prefers structured values from ``listing["notion_fields"]`` (populated by
    the LLM analysis step) and falls back to raw listing fields when absent.
    """
    fields: dict = listing.get("notion_fields") or {}
    detail = listing.get("detail") or {}

    # Resolve each field: structured output first, then raw fallbacks
    title = fields.get("title") or detail.get("title") or listing.get("title") or "Untitled"
    price = fields.get("rent_per_month") or _parse_price_numeric(listing.get("price", ""))
    size = fields.get("size_sqm") or _parse_sqm_numeric(detail.get("size") or listing.get("sqm", ""))
    floor_val = fields.get("floor") or detail.get("floor", "")
    address = fields.get("address") or listing.get("detail_address") or listing.get("address", "")
    rooms = fields.get("rooms") or listing.get("rooms", "")
    source = listing.get("source", "")
    _raw_energy = fields.get("energy_class") or listing.get("detail_energy_class", "") or ""
    # Only use the value if it is a real class (A–G, A1–A4, A+); pending statuses
    # and free text ("E' in fase di rilascio") are not a select option.
    energy = normalize_energy_class(_raw_energy)
    if not re.fullmatch(r"[A-G](?:[1-4]|\+{1,3})?", energy):
        energy = ""
    furnished: Optional[bool] = fields.get("furnished")
    available_from: Optional[str] = fields.get("available_from")
    notes_extra: Optional[str] = fields.get("notes")
    url = listing.get("url", "")

    props: dict = {
        "Apartment": {"title": [{"text": {"content": title}}]},
        "Status": {"select": {"name": "👀 To Visit"}},
        "Listing URL": {"url": url} if url else {"url": None},
        "Scraped At": {"date": {"start": _now_iso()}},
    }

    if price is not None:
        props["Rent (€/mo)"] = {"number": price}
    if size is not None:
        props["Size (m²)"] = {"number": size}
    if rooms:
        props["Rooms"] = {"rich_text": [{"text": {"content": str(rooms)}}]}
    if floor_val:
        props["Floor"] = {"rich_text": [{"text": {"content": str(floor_val)}}]}
    if address:
        props["Address"] = {"rich_text": [{"text": {"content": address}}]}
    if source:
        props["Source"] = {"select": {"name": source}}
    if energy:
        props["Energy Class"] = {"select": {"name": energy}}
    if furnished is not None:
        props["Furnished"] = {"checkbox": furnished}
    if available_from and re.match(r"^\d{4}-\d{2}-\d{2}(T|$)", available_from):
        props["Available From"] = {"date": {"start": available_from}}
    if lat_lon:
        props["Place"] = {"place": {"lat": lat_lon[0], "lon": lat_lon[1]}}

    # AI analysis fields
    ai_score = fields.get("ai_score") if fields else listing.get("ai_score")
    ai_verdict = fields.get("ai_verdict") if fields else listing.get("ai_verdict", "")
    ai_reason = fields.get("ai_reason") if fields else listing.get("ai_reason", "")
    if ai_score is not None:
        props["AI Score"] = {"number": ai_score}
        stars = _score_to_stars(int(ai_score))
        props["Score"] = {"select": {"name": stars}}
    if ai_verdict or ai_reason or notes_extra:
        parts = []
        if ai_verdict and ai_reason:
            parts.append(f"{ai_verdict}: {ai_reason}")
        elif ai_verdict or ai_reason:
            parts.append(ai_verdict or ai_reason)
        if notes_extra:
            parts.append(notes_extra)
        props["Notes"] = {"rich_text": [{"text": {"content": "\n\n".join(parts)[:2000]}}]}
    if ai_reason:
        props["AI Reason"] = {"rich_text": [{"text": {"content": ai_reason[:2000]}}]}

    # Relations
    if area_page_id:
        props["Area"] = {"relation": [{"id": area_page_id}]}
    if agency_page_id:
        props["Agency"] = {"relation": [{"id": agency_page_id}]}

    return props


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def mark_notion_duplicates(listings: list[dict]) -> int:
    """Check Notion for duplicates and mark them in-place to avoid re-enrichment.
    Returns the number of duplicates found.
    """
    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    if not api_key or not apartments_db_id or not listings:
        return 0

    skipped = 0
    now = time.monotonic()
    for url, checked_at in list(_recent_negative_checks.items()):
        if now - checked_at >= _DUP_CHECK_TTL_SEC:
            del _recent_negative_checks[url]
    async with AsyncClient(auth=api_key) as client:
        # Minimal check, not doing full schema or caching areas
        for listing in listings:
            if "notion_skipped" in listing:
                continue
            url = listing.get("url", "")
            if not url:
                continue
            existing_id = await _is_duplicate(client, apartments_db_id, url)
            if existing_id:
                listing["notion_skipped"] = True
                listing["notion_page_id"] = existing_id
                listing["notion_page_url"] = f"https://www.notion.so/{existing_id.replace('-', '')}"
                skipped += 1
            else:
                _recent_negative_checks[url] = time.monotonic()
    return skipped


async def push_listings(listings: list[dict]) -> None:
    """Create Notion Apartments pages for each listing in-place.

    Adds notion_page_id, notion_page_url, notion_skipped to each listing dict.
    Reads DB IDs from env vars. Deduplicates by Listing URL, reusing a recent
    ``mark_notion_duplicates`` check instead of querying the URL twice.
    Geocodes with the listing's own ``lat``/``lon`` when present.
    """
    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    areas_db_id = os.environ.get("NOTION_AREAS_DB_ID", "")
    agencies_db_id = os.environ.get("NOTION_AGENCIES_DB_ID", "")

    area_cache: dict[str, Optional[str]] = {}
    agency_cache: dict[str, Optional[str]] = {}

    async with AsyncClient(auth=api_key) as client, httpx.AsyncClient() as http:
        await _ensure_schema(client, apartments_db_id)

        created = skipped = 0
        for listing in listings:
            if listing.get("notion_skipped"):
                skipped += 1
                continue

            url = listing.get("url", "")
            existing_id = None
            if not _recently_checked(url):
                existing_id = await _is_duplicate(client, apartments_db_id, url)

            if existing_id:
                listing["notion_skipped"] = True
                listing["notion_page_id"] = existing_id
                listing["notion_page_url"] = f"https://www.notion.so/{existing_id.replace('-', '')}"
                skipped += 1
                continue

            area_slug = listing.get("_area", "")
            area_page_id = None
            if area_slug and areas_db_id:
                area_page_id = await _find_area_page_id(client, areas_db_id, area_slug, area_cache)

            agency_name = listing.get("detail_agency", "")
            agency_page_id = None
            if agency_name and agencies_db_id:
                agency_page_id = await _find_or_create_agency_page_id(
                    client, agencies_db_id, agency_name, agency_cache
                )

            # Geocode address for Place (map view); reuse coordinates the
            # backend already resolved.
            lat_lon: Optional[tuple[float, float]] = None
            if listing.get("lat") is not None and listing.get("lon") is not None:
                lat_lon = (float(listing["lat"]), float(listing["lon"]))
            else:
                fields: dict = listing.get("notion_fields") or {}
                address_for_geocode = (
                    fields.get("address")
                    or listing.get("detail_address")
                    or listing.get("address", "")
                )
                lat_lon = await _geocode_address(address_for_geocode, client=http)

            props = _build_properties(listing, area_page_id, agency_page_id, lat_lon)
            page = await client.pages.create(
                parent={"database_id": apartments_db_id},
                properties=props,
            )
            listing["notion_page_id"] = page["id"]
            listing["notion_page_url"] = page.get("url", "")
            listing["notion_skipped"] = False
            _recent_negative_checks.pop(url, None)
            created += 1

        click.echo(f"Notion push: {created} created, {skipped} skipped.", err=True)
