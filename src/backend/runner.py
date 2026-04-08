"""backend.runner — Core job execution pipeline.

Pipeline order: scrape → dedup → enrich → analyse → notion_push → upsert
Uses the streaming Pipeline with Stage-based processing.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Callable

from sqlmodel import Session, select as sql_select

from apt_scrape.server import fetcher
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
                    html = await fetcher.fetch_with_retry(
                        url,
                        wait_selector=adapter.config.search_wait_selector,
                        wait_timeout=search_wait_timeout / 1000,
                        rejection_checker=adapter.detect_rejection,
                        page_load_wait=page_load_wait,
                    )
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

        # --- Pipeline processing ---
        scraped_count = len(all_listings)

        from apt_scrape.pipeline import Pipeline
        from apt_scrape.stages import DedupStage, EnrichStage, AnalyseStage, NotionPushStage

        dedup = DedupStage()
        stages: list = [dedup]

        stages.append(EnrichStage(fetcher, adapter))

        if auto_analyse:
            from apt_scrape.analysis import load_preferences
            try:
                prefs = load_preferences()
                stages.append(AnalyseStage(prefs))
            except FileNotFoundError:
                _log("[warn] preferences.txt not found — skipping analysis.")

        if auto_notion_push:
            stages.append(NotionPushStage())

        pipeline = Pipeline(stages)
        for listing_dict in all_listings:
            await pipeline.push(listing_dict)
        await pipeline.finish()

        stats = pipeline.stats()
        _log(f"Pipeline stats: {stats}")

        # Collect token usage from AnalyseStage if present
        ai_usage: dict | None = None
        for stage in pipeline._stages:
            if hasattr(stage, 'tokens_used'):
                ai_usage = {
                    'tokens_used': stage.tokens_used,
                    'cost_usd': stage.estimated_cost_usd(),
                }
                break

        # Stamp area/city on all listings
        for listing in all_listings:
            listing["_area"] = listing.pop("_search_area", "")
            listing["_city"] = city_slug

        # Collect deduplicated results for DB upsert
        # The dedup stage tracked unique URLs — rebuild from all_listings
        deduped = []
        seen_urls = set()
        for listing in all_listings:
            url = str(listing.get("url", "")).strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduped.append(listing)

        dupes_removed = scraped_count - len(deduped)
        _log(f"Total unique listings: {len(deduped)} ({dupes_removed} dupes removed)")

        # 8. Upsert listings to DB
        _log("Upserting listings to DB...")
        with Session(engine) as session:
            urls = [str(l.get("url", "")).strip() for l in deduped if l.get("url")]
            existing_map = {
                row.url: row
                for row in session.exec(sql_select(Listing).where(Listing.url.in_(urls))).all()
            }
            now = datetime.utcnow()
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
                else:
                    session.add(Listing(**row_data))
            session.commit()

        # 9. Mark job done with stats
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
            job.ai_tokens_used = ai_usage['tokens_used'] if ai_usage else None
            job.ai_cost_usd = ai_usage['cost_usd'] if ai_usage else None
            job.area_stats = json.dumps(area_stats)
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
    finally:
        # Runs on all exit paths — Exception, BaseException (CancelledError, KeyboardInterrupt), and normal return.
        _flush_log()
