"""apt_scrape.notion_push — Push scraped listings into a Notion Apartments database.

Creates pages in the Apartments DB with relational links to Areas and Agencies.
Deduplicates by Listing URL. Adds new schema properties on first run via
_ensure_schema().

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


def _build_properties(listing: dict, area_page_id: Optional[str], agency_page_id: Optional[str]) -> dict:
    """Build the Notion page properties dict from a listing dict."""
    detail = listing.get("detail") or {}

    title = detail.get("title") or listing.get("title") or "Untitled"
    price = _parse_price_numeric(listing.get("price", ""))
    size_str = detail.get("size") or listing.get("sqm", "")
    size = _parse_sqm_numeric(size_str)
    floor_val = detail.get("floor", "")
    address = listing.get("detail_address") or listing.get("address", "")
    rooms = listing.get("rooms", "")
    url = listing.get("url", "")
    source = listing.get("source", "")
    energy = listing.get("detail_energy_class", "")

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
        props["Rooms"] = {"rich_text": [{"text": {"content": rooms}}]}
    if floor_val:
        props["Floor"] = {"rich_text": [{"text": {"content": floor_val}}]}
    if address:
        props["Address"] = {"rich_text": [{"text": {"content": address}}]}
    if source:
        props["Source"] = {"select": {"name": source}}
    if energy:
        props["Energy Class"] = {"select": {"name": energy}}

    # AI analysis fields (only if present)
    ai_stars = listing.get("ai_stars")
    if ai_stars:
        props["Score"] = {"select": {"name": ai_stars}}
    ai_score = listing.get("ai_score")
    if ai_score is not None:
        props["AI Score"] = {"number": ai_score}
    ai_verdict = listing.get("ai_verdict", "")
    ai_reason = listing.get("ai_reason", "")
    if ai_verdict or ai_reason:
        notes = f"{ai_verdict}: {ai_reason}" if ai_verdict else ai_reason
        props["Notes"] = {"rich_text": [{"text": {"content": notes[:2000]}}]}
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

            props = _build_properties(listing, area_page_id, agency_page_id)
            page = await client.pages.create(
                parent={"database_id": apartments_db_id},
                properties=props,
            )
            listing["notion_page_id"] = page["id"]
            listing["notion_page_url"] = page.get("url", "")
            listing["notion_skipped"] = False
            created += 1

        click.echo(f"Notion push: {created} created, {skipped} skipped.", err=True)
