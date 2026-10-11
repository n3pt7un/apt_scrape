"""backend.geocoding — Background Nominatim geocoding of listings for the map view.

One asyncio task at a time walks the listings still lacking coordinates and
writes lat/lon/geocode_status per listing as it goes. Respects Nominatim's
usage policy: identifying User-Agent and at most one request per second.

geocode_status: None = not tried yet (or only transient errors), "ok", "failed"
(Nominatim found nothing for any of the candidate queries).
"""

import asyncio
import logging
import re
from typing import Optional

import httpx
from sqlalchemy import and_, func, or_
from sqlmodel import Session, select

from backend.db import Listing, engine
from backend.parsing import listing_address, load_raw

logger = logging.getLogger(__name__)

# Same endpoint and User-Agent as apt_scrape.notion_push._geocode_address. That helper
# is not reused because it caches failures in-process (breaking retry_failed) and
# swallows network errors, which here must not be recorded as "failed".
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "apt_scrape/1.0 (apartment hunter)"
REQUEST_INTERVAL_SEC = 1.1        # Nominatim policy: max 1 request/second
MAX_CONSECUTIVE_ERRORS = 5        # stop the run if Nominatim is unreachable / blocking us

# Leading property typology in scraped titles used as addresses, e.g.
# "Bilocale via Nosadella 34, ..." or "Appartamento in affitto in via Roma 1, ..."
_TYPOLOGY_PREFIX = re.compile(
    r"^\s*(?:monolocale|bilocale|trilocale|quadrilocale|pentalocale|plurilocale|"
    r"appartamento|attico|loft|mansarda|"
    r"villa(?:\s+a\s+schiera|\s+(?:uni|bi)familiare)?|villetta(?:\s+a\s+schiera)?|"
    r"casa\s+(?:indipendente|semindipendente)|rustico|open\s+space|terratetto|"
    r"stanza|camera|posto\s+letto)"
    r"(?:\s+(?:in\s+)?(?:affitto|vendita))?\b[\s,:-]*(?:in\s+)?",
    re.IGNORECASE,
)

_task: Optional[asyncio.Task] = None


async def _geocode(query: str) -> Optional[tuple[float, float]]:
    """One Nominatim lookup: (lat, lon), or None when nothing matched. Raises on HTTP/network errors."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "it"},
            headers={"User-Agent": USER_AGENT, "Accept-Language": "it"},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
    if not data:
        return None
    return float(data[0]["lat"]), float(data[0]["lon"])


async def _sleep(seconds: float) -> None:
    """Rate-limit pause between Nominatim calls (indirection so tests can skip it)."""
    await asyncio.sleep(seconds)


def _city_label(city_slug: str) -> str:
    """'reggio-emilia' -> 'Reggio Emilia'."""
    return " ".join(w.capitalize() for w in (city_slug or "").replace("-", " ").split())


def strip_typology(address: str) -> str:
    """Drop a leading property typology ('Bilocale', 'Appartamento in affitto in', ...)."""
    return _TYPOLOGY_PREFIX.sub("", address or "", count=1).strip(" ,")


def build_queries(address: str, city_slug: str) -> list[str]:
    """Candidate Nominatim queries, most precise first.

    1. the full address; 2. street + city (scraped neighbourhood labels such as
    "Saragozza dentro le Mura" often aren't OSM names and sink the full query);
    3. the part after the first comma (neighbourhood + city). City and "Italia"
    are appended when missing. Queries that would collapse to the bare city are
    skipped so a listing never lands on the city centre.
    """
    addr = strip_typology(address)
    if not addr:
        return []
    city = _city_label(city_slug)

    def _with_city(text: str) -> str:
        parts = [text]
        lowered = text.lower()
        if city and city.lower() not in lowered:
            parts.append(city)
        if "italia" not in lowered and "italy" not in lowered:
            parts.append("Italia")
        return ", ".join(parts)

    segments = [s.strip() for s in addr.split(",") if s.strip()]
    candidates = [addr]
    if len(segments) > 1:
        candidates.append(segments[0])
        candidates.append(", ".join(segments[1:]))

    queries: list[str] = []
    for text in candidates:
        if city and text.lower() == city.lower():
            continue
        query = _with_city(text)
        if query not in queries:
            queries.append(query)
    return queries


def _pending_condition(retry_failed: bool):
    status_cond = Listing.geocode_status.is_(None)
    if retry_failed:
        status_cond = or_(status_cond, Listing.geocode_status == "failed")
    return and_(Listing.lat.is_(None), status_cond)


def _save_result(listing_id: int, coords: Optional[tuple[float, float]]) -> None:
    with Session(engine) as s:
        lst = s.get(Listing, listing_id)
        if lst is None:
            return
        if coords:
            lst.lat, lst.lon = coords
            lst.geocode_status = "ok"
        else:
            lst.geocode_status = "failed"
        s.add(lst)
        s.commit()


async def run_geocoding(retry_failed: bool = False) -> None:
    """Geocode every pending listing, writing results one by one."""
    with Session(engine) as s:
        rows = s.exec(
            select(Listing.id, Listing.raw_json, Listing.title, Listing.city)
            .where(_pending_condition(retry_failed))
            .order_by(Listing.id)
        ).all()
    logger.info("Geocoding %d listings (retry_failed=%s)", len(rows), retry_failed)

    cache: dict[str, Optional[tuple[float, float]]] = {}  # per-run: identical queries hit Nominatim once
    requests_made = 0
    consecutive_errors = 0
    for listing_id, raw_json, title, city in rows:
        address = listing_address(load_raw(raw_json)) or title
        coords: Optional[tuple[float, float]] = None
        had_error = False
        for query in build_queries(address, city):
            if query in cache:
                coords = cache[query]
            else:
                if requests_made:
                    await _sleep(REQUEST_INTERVAL_SEC)
                requests_made += 1
                try:
                    coords = await _geocode(query)
                except Exception as exc:
                    logger.warning("Geocoding failed for %r: %s", query, exc)
                    had_error = True
                    consecutive_errors += 1
                    coords = None
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        break
                    continue
                consecutive_errors = 0
                cache[query] = coords
            if coords:
                break
        # Transient errors without a hit leave the listing pending for the next run
        if coords or not had_error:
            _save_result(listing_id, coords)
        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
            logger.warning("Geocoding aborted after %d consecutive errors", consecutive_errors)
            return


async def _run_safely(retry_failed: bool) -> None:
    try:
        await run_geocoding(retry_failed)
    except Exception:
        logger.exception("Geocoding task crashed")


def is_running() -> bool:
    return _task is not None and not _task.done()


def start(retry_failed: bool = False) -> bool:
    """Start the background task unless one is already running. Returns True if started.

    Must be called from within the running event loop (an async endpoint).
    """
    global _task
    if is_running():
        return False
    _task = asyncio.get_running_loop().create_task(_run_safely(retry_failed))
    return True


def current_task() -> Optional[asyncio.Task]:
    return _task


def status() -> dict:
    """Counts over all listings: pending (never tried), done (has coordinates), failed."""
    with Session(engine) as s:
        done = s.exec(select(func.count(Listing.id)).where(Listing.lat.is_not(None))).one()
        pending = s.exec(select(func.count(Listing.id)).where(_pending_condition(False))).one()
        failed = s.exec(
            select(func.count(Listing.id)).where(
                Listing.lat.is_(None), Listing.geocode_status == "failed"
            )
        ).one()
    return {"running": is_running(), "pending": pending, "done": done, "failed": failed}
