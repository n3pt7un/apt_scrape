"""backend.runner — Core job execution pipeline.

Pipeline order: scrape → enrich → post_dates → stamp → analyse → notion_push → upsert
NEVER calls browser.close() — browser lifecycle is managed by FastAPI lifespan.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Callable

from sqlmodel import Session, select as sql_select

from apt_scrape.enrichment import enrich_post_dates, enrich_with_details
from apt_scrape.server import browser
from apt_scrape.sites import SearchFilters, get_adapter, get_adapter_with_overrides, list_adapters

logger = logging.getLogger(__name__)


def _normalize_slug(value: str) -> str:
    return value.lower().replace(" ", "-")


def _parse_property_types(raw: str) -> list[str]:
    types = [p.strip() for p in raw.split(",") if p.strip()]
    return types or ["appartamenti"]


async def run_config_job(
    config_id: int,
    log_fn: Callable[[str], None],
    existing_job_id: int | None = None,
) -> int:
    """Execute a scraping job for the given config. Returns job_id."""
    from backend.db import Job, Listing, SearchConfig, engine

    # 1. Create or reuse job record
    with Session(engine) as session:
        cfg = session.get(SearchConfig, config_id)
        if not cfg:
            raise ValueError(f"SearchConfig {config_id} not found")

        if existing_job_id is not None:
            job = session.get(Job, existing_job_id)
            job.status = "running"
            session.add(job)
            session.commit()
            job_id = existing_job_id
        else:
            job = Job(config_id=config_id, status="running", triggered_by="schedule")
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id

    def _log(msg: str) -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log_fn(line)
        with Session(engine) as s:
            j = s.get(Job, job_id)
            if j:
                j.log = (j.log or "") + line + "\n"
                s.add(j)
                s.commit()

    try:
        with Session(engine) as session:
            cfg = session.get(SearchConfig, config_id)
            site_id = getattr(cfg, "site_id", None) or "immobiliare"
            from backend.db import SiteConfigOverride
            from backend.routers.sites import resolve_base_site_id
            base_site_id = resolve_base_site_id(site_id)
            if base_site_id not in list_adapters():
                base_site_id = list_adapters()[0]
                site_id = base_site_id
            overrides = {}
            row = session.get(SiteConfigOverride, site_id)
            if row and row.overrides:
                overrides = json.loads(row.overrides) if isinstance(row.overrides, str) else (row.overrides or {})
            adapter = get_adapter_with_overrides(base_site_id, overrides if overrides else None)
            city_slug = _normalize_slug(cfg.city)
            area_slug = _normalize_slug(cfg.area) if cfg.area else None
            property_types = _parse_property_types(cfg.property_type)
            detail_concurrency = cfg.detail_concurrency
            vpn_rotate_batches = cfg.vpn_rotate_batches
            auto_analyse = cfg.auto_analyse
            auto_notion_push = cfg.auto_notion_push
            start_page = cfg.start_page
            end_page = cfg.end_page
            min_price = cfg.min_price
            max_price = cfg.max_price
            min_sqm = cfg.min_sqm
            min_rooms = cfg.min_rooms
            operation = cfg.operation
            request_delay = getattr(cfg, "request_delay_sec", 2.0)
            page_delay = getattr(cfg, "page_delay_sec", 0.0)
            # Per-site rate limit: overrides can set requests_per_minute (e.g. 15)
            rpm = overrides.get("requests_per_minute")
            if rpm is not None and float(rpm) > 0:
                min_delay = 60.0 / float(rpm)
                request_delay = max(request_delay, min_delay)
                _log(f"Site rate limit: {rpm} req/min → delay {request_delay:.1f}s between search requests")

        # 2. Scrape search pages
        all_listings: list[dict] = []
        for pt in property_types:
            for page_num in range(start_page, end_page + 1):
                if page_num > start_page and page_delay > 0:
                    await asyncio.sleep(page_delay)
                filters = SearchFilters(
                    city=city_slug, area=area_slug, operation=operation,
                    property_type=pt, min_price=min_price, max_price=max_price,
                    min_sqm=min_sqm, min_rooms=min_rooms, page=page_num,
                )
                url = adapter.build_search_url(filters)
                _log(f"Fetching {pt} page {page_num}: {url}")
                html = await browser.fetch_page(url, wait_selector=adapter.config.search_wait_selector)
                if request_delay > 0:
                    await asyncio.sleep(request_delay)
                page_listings = adapter.parse_search(html)
                if not page_listings:
                    _log(f"No listings on page {page_num}, stopping.")
                    break
                all_listings.extend([ls.to_dict() for ls in page_listings])
                _log(f"  -> {len(page_listings)} listings")

        # Deduplicate by URL
        seen: set[str] = set()
        deduped: list[dict] = []
        for listing in all_listings:
            key = str(listing.get("url", "")).strip()
            if key and key not in seen:
                seen.add(key)
                deduped.append(listing)
        _log(f"Total unique listings: {len(deduped)}")

        # 3. Enrich details
        _log(f"Enriching details (concurrency={detail_concurrency})...")
        await enrich_with_details(
            deduped, browser, adapter, None,
            concurrency=detail_concurrency,
            rotate_every_batches=vpn_rotate_batches,
        )

        # 4. Enrich post dates
        await enrich_post_dates(
            deduped, browser, adapter,
            concurrency=detail_concurrency,
            rotate_every_batches=vpn_rotate_batches,
        )

        # 5. Stamp area/city
        for listing in deduped:
            listing["_area"] = area_slug or ""
            listing["_city"] = city_slug

        # 6. AI Analysis
        if auto_analyse and deduped:
            _log("Running AI analysis...")
            from apt_scrape.analysis import analyse_listings, load_preferences
            try:
                prefs = load_preferences()
                await analyse_listings(deduped, prefs)
                _log("Analysis complete.")
            except FileNotFoundError:
                _log("[warn] preferences.txt not found — skipping analysis.")

        # 7. Notion Push
        if auto_notion_push and deduped:
            _log("Pushing to Notion...")
            from apt_scrape.notion_push import push_listings
            await push_listings(deduped)
            _log("Notion push complete.")

        # 8. Upsert listings to DB
        _log("Upserting listings to DB...")
        with Session(engine) as session:
            for listing in deduped:
                url = str(listing.get("url", "")).strip()
                if not url:
                    continue
                existing = session.exec(
                    sql_select(Listing).where(Listing.url == url)
                ).first()
                row_data = dict(
                    url=url, job_id=job_id, config_id=config_id,
                    title=listing.get("title", ""), price=listing.get("price", ""),
                    sqm=listing.get("sqm", ""), rooms=listing.get("rooms", ""),
                    area=area_slug or "", city=city_slug,
                    ai_score=listing.get("ai_score"),
                    ai_verdict=listing.get("ai_verdict"),
                    notion_page_id=listing.get("notion_page_id"),
                    raw_json=json.dumps(listing, ensure_ascii=False),
                    scraped_at=datetime.utcnow(),
                )
                if existing:
                    for k, v in row_data.items():
                        setattr(existing, k, v)
                    session.add(existing)
                else:
                    session.add(Listing(**row_data))
            session.commit()

        # 9. Mark job done
        with Session(engine) as session:
            job = session.get(Job, job_id)
            job.status = "done"
            job.finished_at = datetime.utcnow()
            job.listing_count = len(deduped)
            session.add(job)
            session.commit()

        _log(f"Job complete. {len(deduped)} listings processed.")
        return job_id

    except Exception as exc:
        logger.exception("Job %d failed", job_id)
        _log(f"[ERROR] {exc}")
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job:
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                session.add(job)
                session.commit()
        return job_id
