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

import os
import re
from datetime import datetime, timezone
from typing import Optional

import click
import httpx
from notion_client import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_price_numeric(price_str: str) -> Optional[float]:
    """Extract the first numeric value from a price string (handles dots/commas as thousands sep)."""
    if not price_str:
        return None
    # Remove thousands separators (. or ,) then find digits
    cleaned = re.sub(r"[.,](?=\d{3})", "", price_str)
    m = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


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
_geocode_cache: dict[str, Optional[tuple[float, float]]] = {}


async def _geocode_address(address: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) for *address* using Nominatim, or None on failure.

    Results are cached in-process to avoid duplicate requests within a run.
    """
    if not address:
        return None
    if address in _geocode_cache:
        return _geocode_cache[address]
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"q": address, "format": "json", "limit": 1},
                headers={"User-Agent": "apt_scrape/1.0 (apartment hunter)"},
                timeout=10.0,
            )
            data = resp.json()
            if data:
                result: Optional[tuple[float, float]] = (float(data[0]["lat"]), float(data[0]["lon"]))
            else:
                result = None
    except Exception as exc:
        click.echo(f"  [warn] Geocoding failed for '{address}': {exc}", err=True)
        result = None
    _geocode_cache[address] = result
    return result


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
    # Only use the value if it looks like a valid energy class (A–G, optionally A1–A4)
    _energy_match = re.search(r'\b([A-Ga-g][1-4]?)\b', _raw_energy)
    energy = _energy_match.group(1).upper() if _energy_match else ""
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


async def fetch_all_notion_listings(
    log_fn: Optional[callable] = None,
) -> dict[str, str]:
    """Fetch all listing URLs from Notion Apartments DB in bulk (paginated).

    Returns a dict mapping ``{listing_url: notion_page_id}``.
    Much faster than checking one-by-one with ``_is_duplicate``.
    """
    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    if not api_key or not apartments_db_id:
        return {}

    _log = log_fn or (lambda msg: None)
    url_to_page: dict[str, str] = {}

    async with AsyncClient(auth=api_key) as client:
        start_cursor: Optional[str] = None
        page_num = 0
        while True:
            page_num += 1
            kwargs: dict = {
                "database_id": apartments_db_id,
                "filter_properties": ["Listing URL"],
                "page_size": 100,
            }
            if start_cursor:
                kwargs["start_cursor"] = start_cursor
            resp = await client.databases.query(**kwargs)
            for result in resp.get("results", []):
                props = result.get("properties", {})
                url_prop = props.get("Listing URL", {})
                url_val = url_prop.get("url")
                if url_val:
                    url_to_page[url_val.strip()] = result["id"]
            _log(f"  Notion sync page {page_num}: {len(resp.get('results', []))} entries (total so far: {len(url_to_page)})")
            if not resp.get("has_more"):
                break
            start_cursor = resp.get("next_cursor")

    return url_to_page


async def mark_notion_duplicates(listings: list[dict]) -> int:
    """Check Notion for duplicates and mark them in-place to avoid re-enrichment.
    Returns the number of duplicates found.
    """
    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    if not api_key or not apartments_db_id or not listings:
        return 0

    skipped = 0
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
    return skipped


async def push_listings(listings: list[dict]) -> None:
    """Create Notion Apartments pages for each listing in-place.

    Adds notion_page_id, notion_page_url, notion_skipped to each listing dict.
    Reads DB IDs from env vars. Deduplicates by Listing URL.
    """
    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    areas_db_id = os.environ.get("NOTION_AREAS_DB_ID", "")
    agencies_db_id = os.environ.get("NOTION_AGENCIES_DB_ID", "")

    area_cache: dict[str, Optional[str]] = {}
    agency_cache: dict[str, Optional[str]] = {}

    async with AsyncClient(auth=api_key) as client:
        await _ensure_schema(client, apartments_db_id)

        created = skipped = 0
        for listing in listings:
            if listing.get("notion_skipped"):
                skipped += 1
                continue

            url = listing.get("url", "")
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

            # Geocode address for Place (map view)
            fields: dict = listing.get("notion_fields") or {}
            address_for_geocode = (
                fields.get("address")
                or listing.get("detail_address")
                or listing.get("address", "")
            )
            lat_lon = await _geocode_address(address_for_geocode)

            props = _build_properties(listing, area_page_id, agency_page_id, lat_lon)
            page = await client.pages.create(
                parent={"database_id": apartments_db_id},
                properties=props,
            )
            listing["notion_page_id"] = page["id"]
            listing["notion_page_url"] = page.get("url", "")
            listing["notion_skipped"] = False
            created += 1

        click.echo(f"Notion push: {created} created, {skipped} skipped.", err=True)
