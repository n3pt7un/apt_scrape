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
from apt_scrape.sites import SearchFilters, get_adapter_with_overrides, list_adapters

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

    _log_buffer: list[str] = []

    def _flush_log() -> None:
        if not _log_buffer:
            return
        chunk = "".join(_log_buffer)
        _log_buffer.clear()
        with Session(engine) as s:
            j = s.get(Job, job_id)
            if j:
                j.log = (j.log or "") + chunk
                s.add(j)
                s.commit()

    def _log(msg: str) -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}\n"
        log_fn(line.rstrip())
        _log_buffer.append(line)
        if len(_log_buffer) >= 10:
            _flush_log()

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
            raw_areas = [a.strip() for a in (cfg.area or "").split(",")]
            area_slugs = [_normalize_slug(a) for a in raw_areas if a]
            if not area_slugs:
                area_slugs = [None]
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
        for area_slug in area_slugs:
            for pt in property_types:
                seen_in_run: set[str] = set()  # track URLs within this area/pt run to detect redirect loops
                for page_num in range(start_page, end_page + 1):
                    if page_num > start_page and page_delay > 0:
                        await asyncio.sleep(page_delay)
                    filters = SearchFilters(
                        city=city_slug, area=area_slug, operation=operation,
                        property_type=pt, min_price=min_price, max_price=max_price,
                        min_sqm=min_sqm, min_rooms=min_rooms, page=page_num,
                    )
                    url = adapter.build_search_url(filters)
                    a_name = f" (area: {area_slug})" if area_slug else ""
                    _log(f"Fetching {pt}{a_name} page {page_num}: {url}")
                    page_load_wait = getattr(adapter.config, "page_load_wait", "domcontentloaded")
                    search_wait_timeout = getattr(adapter.config, "search_wait_timeout", 15000)
                    html = await browser.fetch_page(url, wait_selector=adapter.config.search_wait_selector, wait_until=page_load_wait, wait_selector_timeout=search_wait_timeout)
                    if request_delay > 0:
                        await asyncio.sleep(request_delay)
                    page_listings = adapter.parse_search(html)
                    if not page_listings:
                        _log(f"No listings on page {page_num}, stopping.")
                        break

                    # Detect redirect loops: stop if all listings on this page were
                    # already seen in a previous page (site redirected to last valid page)
                    page_urls = {str(ls.url).strip() for ls in page_listings if ls.url}
                    new_urls = page_urls - seen_in_run
                    if not new_urls and seen_in_run:
                        _log(f"  -> Page {page_num} is a duplicate of a previous page (redirect detected), stopping.")
                        break
                    seen_in_run |= page_urls

                    for ls in page_listings:
                        l_dict = ls.to_dict()
                        l_dict["_search_area"] = area_slug or ""
                        all_listings.append(l_dict)

                    _log(f"  -> {len(page_listings)} listings ({len(new_urls)} new)")

        # Deduplicate by URL
        scraped_count = len(all_listings)
        seen: set[str] = set()
        deduped: list[dict] = []
        for listing in all_listings:
            key = str(listing.get("url", "")).strip()
            if key and key not in seen:
                seen.add(key)
                deduped.append(listing)
        dupes_removed = scraped_count - len(deduped)
        _log(f"Total unique listings: {len(deduped)} ({dupes_removed} dupes removed)")

        # ── 2a. Sync Notion → local DB (bulk fetch, then upsert stubs) ──
        notion_synced = 0
        if auto_notion_push:
            _log("Syncing Notion listings to local DB (bulk fetch)...")
            try:
                from apt_scrape.notion_push import fetch_all_notion_listings
                notion_url_map = await fetch_all_notion_listings(log_fn=_log)
                if notion_url_map:
                    with Session(engine) as session:
                        existing_urls = {
                            row.url
                            for row in session.exec(
                                sql_select(Listing).where(
                                    Listing.url.in_(list(notion_url_map.keys()))
                                )
                            ).all()
                        }
                        now = datetime.utcnow()
                        for n_url, n_page_id in notion_url_map.items():
                            if n_url not in existing_urls:
                                session.add(Listing(
                                    url=n_url, job_id=job_id, config_id=config_id,
                                    notion_page_id=n_page_id, scraped_at=now,
                                ))
                                notion_synced += 1
                        if notion_synced:
                            session.commit()
                    _log(f"Notion sync complete: {len(notion_url_map)} in Notion, {notion_synced} new stubs saved to local DB")
                else:
                    _log("Notion sync: database is empty or not configured")
            except Exception as e:
                _log(f"[warn] Notion sync failed (continuing without): {e}")

        # ── 2b. Filter out already-known listings ──
        with Session(engine) as session:
            deduped_urls = [str(l.get("url", "")).strip() for l in deduped if l.get("url")]
            known_rows = {
                row.url: row
                for row in session.exec(
                    sql_select(Listing).where(Listing.url.in_(deduped_urls))
                ).all()
            }

        new_listings = []
        already_known = []
        for listing in deduped:
            url = str(listing.get("url", "")).strip()
            existing = known_rows.get(url)
            if existing:
                # Carry over Notion page ID so push_listings can skip them
                if existing.notion_page_id:
                    listing["notion_skipped"] = True
                    listing["notion_page_id"] = existing.notion_page_id
                already_known.append(listing)
            else:
                new_listings.append(listing)

        _log(f"Pre-enrichment filter: {len(new_listings)} new, {len(already_known)} already in DB → skipping enrichment for known listings")

        # ── 3. Enrich details (new listings only) ──
        if new_listings:
            _log(f"Enriching {len(new_listings)} new listings (concurrency={detail_concurrency})...")
            await enrich_with_details(
                new_listings, browser, adapter, None,
                concurrency=detail_concurrency,
                rotate_every_batches=vpn_rotate_batches,
            )

            # 4. Enrich post dates
            _log(f"Enriching post dates for {len(new_listings)} new listings...")
            await enrich_post_dates(
                new_listings, browser, adapter,
                concurrency=detail_concurrency,
                rotate_every_batches=vpn_rotate_batches,
            )
        else:
            _log("No new listings to enrich — all already known.")

        # 5. Stamp area/city
        for listing in deduped:
            listing["_area"] = listing.pop("_search_area", "")
            listing["_city"] = city_slug

        # ── 6. AI Analysis (new listings only) ──
        ai_usage: dict = {}
        if auto_analyse and new_listings:
            _log(f"Running AI analysis on {len(new_listings)} new listings...")
            from apt_scrape.analysis import analyse_listings, load_preferences
            try:
                prefs = load_preferences()
                ai_usage = await analyse_listings(new_listings, prefs)
                _log(f"Analysis complete: ~{ai_usage.get('tokens_used', 0)} tokens, ${ai_usage.get('cost_usd', 0):.4f}")
            except FileNotFoundError:
                _log("[warn] preferences.txt not found — skipping analysis.")
        elif auto_analyse:
            _log("Skipping AI analysis — no new listings.")

        # ── 7. Notion Push ──
        if auto_notion_push and deduped:
            _log(f"Pushing to Notion ({len(new_listings)} new, {len(already_known)} pre-existing)...")
            from apt_scrape.notion_push import push_listings
            await push_listings(deduped)
            _log("Notion push complete.")

        # ── 8. Upsert all listings to DB ──
        _log("Upserting listings to local DB...")
        with Session(engine) as session:
            urls = [str(l.get("url", "")).strip() for l in deduped if l.get("url")]
            existing_map = {
                row.url: row
                for row in session.exec(sql_select(Listing).where(Listing.url.in_(urls))).all()
            }
            now = datetime.utcnow()
            upserted_new = 0
            upserted_existing = 0
            for listing in deduped:
                url = str(listing.get("url", "")).strip()
                if not url:
                    continue
                row_data = dict(
                    url=url, job_id=job_id, config_id=config_id,
                    title=listing.get("title", ""), price=listing.get("price", ""),
                    sqm=listing.get("sqm", ""), rooms=listing.get("rooms", ""),
                    area=listing.get("_area", ""), city=city_slug,
                    ai_score=listing.get("ai_score"),
                    ai_verdict=listing.get("ai_verdict"),
                    notion_page_id=listing.get("notion_page_id"),
                    raw_json=json.dumps(listing, ensure_ascii=False),
                    scraped_at=now,
                )
                existing = existing_map.get(url)
                if existing:
                    for k, v in row_data.items():
                        setattr(existing, k, v)
                    session.add(existing)
                    upserted_existing += 1
                else:
                    session.add(Listing(**row_data))
                    upserted_new += 1
            session.commit()
        _log(f"DB upsert: {upserted_new} inserted, {upserted_existing} updated")

        # ── 9. Mark job done with stats ──
        area_stats: dict[str, int] = {}
        for listing in deduped:
            a = listing.get("_area") or ""
            area_stats[a] = area_stats.get(a, 0) + 1

        with Session(engine) as session:
            job = session.get(Job, job_id)
            job.status = "done"
            job.finished_at = datetime.utcnow()
            job.listing_count = len(deduped)
            job.scraped_count = scraped_count
            job.dupes_removed = dupes_removed
            job.ai_tokens_used = ai_usage.get("tokens_used")
            job.ai_cost_usd = ai_usage.get("cost_usd")
            job.area_stats = json.dumps(area_stats)
            session.add(job)
            session.commit()

        _log(
            f"Job complete: {scraped_count} scraped → {dupes_removed} in-run dupes "
            f"→ {len(deduped)} unique ({len(new_listings)} new, {len(already_known)} known) "
            f"→ {len(new_listings)} enriched & analysed"
        )
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
    finally:
        # Runs on all exit paths — Exception, BaseException (CancelledError, KeyboardInterrupt), and normal return.
        _flush_log()
