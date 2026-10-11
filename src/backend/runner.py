"""backend.runner — Core job execution pipeline.

Pipeline order: scrape → plan (incremental) → enrich → checkpoint upsert →
analyse → notion_push → upsert.

Runs are incremental: only new listings, listings whose stored detail page is
missing or unreadable, and listings whose price changed get their detail page
fetched; only listings that were (re)read, changed price, have no valid score or
still owe a rescore (ai_rescore_pending) are sent to the LLM. Upserts merge into
the stored row, so a blocked fetch or a failed scoring never wipes data an
earlier run collected.

Search and detail fetches share the browser's rate limiter, spaced by the
config's request_delay_sec (raised by a site's requests_per_minute override);
search pages also pause that long after the previous page finished loading.

NEVER calls browser.close(): the scheduler closes the shared browser after the
last queued run, and the FastAPI lifespan on shutdown.
"""

import asyncio
import json
import logging
import time
from collections import Counter
from datetime import datetime
from typing import Any, Callable, Iterable

from sqlmodel import Session, select as sql_select

from apt_scrape.enrichment import enrich_with_details
from apt_scrape.server import BlockedError, browser
from apt_scrape.sites import SearchFilters, get_adapter_with_overrides, list_adapters
from backend.parsing import detail_status_of, load_raw, parse_price

logger = logging.getLogger(__name__)

# Max seconds a log line may sit in the in-memory buffer before being written to the DB
LOG_FLUSH_INTERVAL_SEC = 1.0
# Searches (area x property type) blocked in a row before the remaining ones are
# skipped: with proxies each block has already cycled through every proxy.
SEARCH_BLOCK_LIMIT = 2

# Outcomes enrich_with_details records in listing["detail_status"]
_DETAIL_STATUSES = ("ok", "blocked", "error", "empty", "skipped")
# raw_json keys written by AI scoring: kept from the stored row unless this run scored the listing
_AI_KEYS = ("ai_score", "ai_verdict", "ai_reason", "ai_notes", "ai_stars", "notion_fields", "ai_error")
# A fresh value equal to one of these never blanks a stored raw_json value
_EMPTY_VALUES = ("", None, [], {})


def _normalize_slug(value: str) -> str:
    return value.lower().replace(" ", "-")


def _parse_property_types(raw: str) -> list[str]:
    types = [p.strip() for p in raw.split(",") if p.strip()]
    return types or ["appartamenti"]


def _url_of(listing: dict) -> str:
    return str(listing.get("url", "")).strip()


def _is_detail_key(key: str) -> bool:
    return key == "detail" or key.startswith("detail_")


def _has_ok_detail(raw: dict[str, Any]) -> bool:
    """True when a listing dict / stored raw_json holds a usable detail page.

    Rows saved before detail_status existed count as ok only if their detail has
    a non-blank title, description or extra_info value (blocked pages used to be
    stored blank): the same rule the API reports, so what it calls unread is retried.
    """
    status = raw.get("detail_status")
    if status is not None:
        return status == "ok"
    return detail_status_of(raw) == "ok"


def _has_valid_score(ai_score: Any, ai_verdict: Any) -> bool:
    return ai_score is not None and ai_verdict != "Error"


def _price_changed(stored: str, fresh: str) -> bool:
    """True when the search card shows another price than the stored row (an empty card price is no change)."""
    fresh = str(fresh or "").strip()
    if not fresh:
        return False
    stored = str(stored or "").strip()
    old_num, new_num = parse_price(stored), parse_price(fresh)
    if old_num is not None and new_num is not None:
        return old_num != new_num
    return stored != fresh


def _copy_stored_detail(listing: dict, raw: dict[str, Any]) -> None:
    """Put a stored, usable detail page back into this run's listing dict instead of refetching it."""
    for key, value in raw.items():
        if _is_detail_key(key):
            listing[key] = value
    listing["detail_status"] = "ok"
    listing.pop("detail_error", None)
    if not listing.get("post_date") and raw.get("post_date"):
        listing["post_date"] = raw["post_date"]


def _copy_stored_ai(listing: dict, raw: dict[str, Any]) -> None:
    """Carry a stored AI outcome into a listing that is not scored this run (Notion push reads it)."""
    for key in _AI_KEYS:
        if key != "ai_error" and key in raw:
            listing[key] = raw[key]


def _merge_raw(old: dict[str, Any], new: dict[str, Any], *, take_new_ai: bool) -> dict[str, Any]:
    """Merge this run's listing dict into the stored raw_json.

    - Card fields: fresh values win, but an empty fresh value never blanks a stored one.
    - Detail ('detail' and detail_* keys): this run's when it read the page
      (detail_status 'ok'); else the stored one when it is usable; else this
      run's failure status (blocked/error/empty/skipped) when it tried.
    - AI keys: this run's outcome only when take_new_ai, else the stored ones; a
      successful new score also clears ai_rescore_pending.
    """
    merged = {**old, **{k: v for k, v in new.items() if v not in _EMPTY_VALUES}}

    new_status = new.get("detail_status")
    use_new_detail = new_status == "ok" or (new_status is not None and not _has_ok_detail(old))
    detail_src = new if use_new_detail else old
    merged = {k: v for k, v in merged.items() if not _is_detail_key(k)}
    merged.update({k: v for k, v in detail_src.items() if _is_detail_key(k)})

    ai_src = new if take_new_ai else old
    merged = {k: v for k, v in merged.items() if k not in _AI_KEYS}
    merged.update({k: v for k, v in ai_src.items() if k in _AI_KEYS})
    if take_new_ai:
        merged.pop("ai_last_error", None)
        if "ai_error" not in new:
            merged.pop("ai_rescore_pending", None)
    return merged


def _load_stored(urls: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Snapshot of the stored rows for *urls*: {url: {raw, price, valid_score}}."""
    from backend.db import Listing, engine

    urls = list(urls)
    if not urls:
        return {}
    with Session(engine) as session:
        rows = session.exec(sql_select(Listing).where(Listing.url.in_(urls))).all()
        return {
            row.url: {
                "raw": load_raw(row.raw_json),
                "price": row.price,
                "valid_score": _has_valid_score(row.ai_score, row.ai_verdict),
            }
            for row in rows
        }


def _upsert_listings(
    listings: list[dict],
    *,
    job_id: int,
    config_id: int,
    city: str,
    scored_urls: set[str],
) -> None:
    """Insert new listings and merge known ones into their stored rows.

    Safe to call several times per run (checkpoint, final, failure paths).
    scraped_at/job_id (first found) are set on insert only; last_seen_at and
    last_job_id move on every call. Triage, seen and geocode columns are never
    touched. A listing counts as scored when its URL is in *scored_urls*; a
    failed scoring (ai_error) never replaces a valid stored score and is kept
    as ai_last_error instead.

    A valid stored score that predates a new price or a newly read detail page
    gets raw_json ai_rescore_pending until a scoring succeeds, so the next run
    retries it whatever stopped this one (failed or skipped scoring, cancel,
    timeout). The first upsert that sees the change sets it: the checkpoint
    before the AI step, or the partial save of a run that stopped earlier.
    """
    from backend.db import Listing, engine

    by_url = {_url_of(l): l for l in listings if _url_of(l)}
    if not by_url:
        return
    now = datetime.utcnow()
    with Session(engine) as session:
        existing_map = {
            row.url: row
            for row in session.exec(sql_select(Listing).where(Listing.url.in_(list(by_url)))).all()
        }
        for url, listing in by_url.items():
            existing = existing_map.get(url)
            if existing is None:
                session.add(Listing(
                    url=url, job_id=job_id, config_id=config_id,
                    title=listing.get("title", ""), price=listing.get("price", ""),
                    sqm=listing.get("sqm", ""), rooms=listing.get("rooms", ""),
                    area=listing.get("_area", ""), city=city,
                    ai_score=listing.get("ai_score"),
                    ai_verdict=listing.get("ai_verdict"),
                    notion_page_id=listing.get("notion_page_id"),
                    raw_json=json.dumps(listing, ensure_ascii=False),
                    scraped_at=now, last_seen_at=now, last_job_id=job_id,
                ))
                continue

            scored = url in scored_urls
            failed = "ai_error" in listing
            valid_score = _has_valid_score(existing.ai_score, existing.ai_verdict)
            take_new_ai = scored and not (failed and valid_score)
            old_raw = load_raw(existing.raw_json)
            merged = _merge_raw(old_raw, listing, take_new_ai=take_new_ai)
            if scored and not take_new_ai:
                merged["ai_last_error"] = listing["ai_error"]
            elif not scored and valid_score and (
                _price_changed(existing.price, listing.get("price", ""))
                or (listing.get("detail_status") == "ok" and not _has_ok_detail(old_raw))
            ):
                merged["ai_rescore_pending"] = True
            if take_new_ai:
                existing.ai_score = listing.get("ai_score")
                existing.ai_verdict = listing.get("ai_verdict")
            existing.config_id = config_id
            existing.title = listing.get("title") or existing.title
            existing.price = listing.get("price") or existing.price
            existing.sqm = listing.get("sqm") or existing.sqm
            existing.rooms = listing.get("rooms") or existing.rooms
            existing.area = listing.get("_area") or existing.area
            existing.city = city
            existing.notion_page_id = listing.get("notion_page_id") or existing.notion_page_id
            existing.raw_json = json.dumps(merged, ensure_ascii=False)
            existing.last_seen_at = now
            existing.last_job_id = job_id
            session.add(existing)
        session.commit()


async def run_config_job(
    config_id: int,
    log_fn: Callable[[str], None],
    existing_job_id: int | None = None,
) -> int:
    """Execute a scraping job for the given config. Returns job_id."""
    from backend.db import Job, SearchConfig, engine

    # 1. Create or reuse job record
    with Session(engine) as session:
        cfg = session.get(SearchConfig, config_id)
        if existing_job_id is not None:
            job = session.get(Job, existing_job_id)
            if job is None:
                raise ValueError(f"Job {existing_job_id} not found")
            if not cfg:
                # Fail the queued job instead of leaving it 'pending' forever
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                job.log = (job.log or "") + f"[ERROR] SearchConfig {config_id} not found\n"
                session.add(job)
                session.commit()
                raise ValueError(f"SearchConfig {config_id} not found")
            job.status = "running"
            job.started_at = datetime.utcnow()  # it may have waited in the queue as 'pending'
            session.add(job)
            session.commit()
            job_id = existing_job_id
        else:
            if not cfg:
                raise ValueError(f"SearchConfig {config_id} not found")
            job = Job(config_id=config_id, status="running", triggered_by="schedule")
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id

    _log_buffer: list[str] = []
    # monotonic time of the last flush; 0.0 makes the very first line flush immediately
    _last_flush = 0.0

    def _flush_log() -> None:
        nonlocal _last_flush
        if not _log_buffer:
            return
        chunk = "".join(_log_buffer)
        _log_buffer.clear()
        _last_flush = time.monotonic()
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
        # Flush every 10 lines, or sooner once a second has passed, so the live
        # log stream (GET /jobs/{id}/stream) stays close to real time.
        if len(_log_buffer) >= 10 or time.monotonic() - _last_flush >= LOG_FLUSH_INTERVAL_SEC:
            _flush_log()

    # State the failure paths need: what was collected so far and what was scored
    deduped: list[dict] = []
    scored_urls: set[str] = set()
    city_slug = ""
    timeout_sec: int | None = None
    run_timeout: asyncio.Timeout | None = None

    def _persist() -> None:
        _upsert_listings(deduped, job_id=job_id, config_id=config_id, city=city_slug, scored_urls=scored_urls)

    def _save_partial() -> None:
        """Best effort on failure: keep the listings collected so far (merged, so nothing stored is lost)."""
        if not deduped:
            return
        try:
            _persist()
            _log(f"Saved the {len(deduped)} listings collected before the failure.")
        except Exception:
            logger.exception("Job %d: could not save partial results", job_id)

    def _mark_failed() -> None:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job:
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                if deduped:
                    job.listing_count = len(deduped)
                session.add(job)
                session.commit()

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
            timeout_sec = getattr(cfg, "timeout_sec", None)
            # Per-site rate limit: overrides can set requests_per_minute (e.g. 15)
            rpm = overrides.get("requests_per_minute")
            if rpm is not None and float(rpm) > 0:
                min_delay = 60.0 / float(rpm)
                request_delay = max(request_delay, min_delay)
                _log(f"Site rate limit: {rpm} req/min → delay {request_delay:.1f}s between requests")

        # Overall time limit (SearchConfig.timeout_sec); 0/NULL means no limit
        async with asyncio.timeout(timeout_sec or None) as run_timeout:
            if timeout_sec:
                _log(f"Time limit: {timeout_sec}s for the whole run")

            # 2. Scrape search pages. Cards are deduplicated by URL and stamped as they
            # arrive, so a timeout or cancel later in the run still saves them.
            seen_urls: set[str] = set()
            scraped_count = 0
            pages_fetched = 0
            fetch_failures = 0
            last_fetch_error = ""
            search_requests = 0
            blocked_in_a_row = 0
            for area_slug in area_slugs:
                if blocked_in_a_row >= SEARCH_BLOCK_LIMIT:
                    break
                for pt in property_types:
                    if blocked_in_a_row >= SEARCH_BLOCK_LIMIT:
                        break
                    seen_in_run: set[str] = set()  # track URLs within this area/pt run to detect redirect loops
                    first_page_size = 0
                    for page_num in range(start_page, end_page + 1):
                        if page_num > start_page and page_delay > 0:
                            await asyncio.sleep(page_delay)
                        # The rate limiter only spaces request starts: also pause after
                        # the previous page finished loading, as a person paging would.
                        if search_requests and request_delay > 0:
                            await asyncio.sleep(request_delay)
                        search_requests += 1
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
                        # One failed search page (block, timeout) skips the rest of this
                        # area/type instead of failing the whole job. The browser's rate
                        # limiter spaces this request from the previous one.
                        fetch_error: Exception | None = None
                        try:
                            html = await browser.fetch_page(
                                url, wait_selector=adapter.config.search_wait_selector,
                                wait_until=page_load_wait, wait_selector_timeout=search_wait_timeout,
                                min_interval=request_delay,
                            )
                            # BeautifulSoup is CPU-bound; keep it off the event loop
                            page_listings = await asyncio.to_thread(adapter.parse_search, html)
                            pages_fetched += 1
                        except Exception as exc:
                            fetch_error = exc
                        if fetch_error is not None:
                            fetch_failures += 1
                            if isinstance(fetch_error, BlockedError):
                                last_fetch_error = "blocked by the portal"
                                blocked_in_a_row += 1
                                _log(f"[warn] {pt}{a_name} page {page_num} blocked by the portal, skipping the rest of this search.")
                                if blocked_in_a_row >= SEARCH_BLOCK_LIMIT:
                                    _log(f"[warn] {blocked_in_a_row} searches in a row blocked by the portal: "
                                         "not trying the remaining ones in this run.")
                            else:
                                last_fetch_error = repr(fetch_error)
                                _log(f"[warn] {pt}{a_name} page {page_num} failed ({fetch_error!r}), skipping the rest of this search.")
                            break
                        blocked_in_a_row = 0
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
                            scraped_count += 1
                            key = _url_of(l_dict)
                            if key and key not in seen_urls:  # first occurrence wins
                                seen_urls.add(key)
                                l_dict["_area"] = area_slug or ""
                                l_dict["_city"] = city_slug
                                deduped.append(l_dict)

                        _log(f"  -> {len(page_listings)} listings ({len(new_urls)} new)")

                        # A page shorter than the first one is the last page: don't fetch an empty one
                        if not first_page_size:
                            first_page_size = len(page_listings)
                        elif len(page_listings) < first_page_size:
                            _log(f"  -> Fewer listings than page {start_page}: last page reached, stopping.")
                            break

            if fetch_failures and not pages_fetched:
                # The cause stays in the message: the UI explains the run's [ERROR] line from it
                raise RuntimeError(
                    f"No search page could be fetched ({fetch_failures} attempt(s) failed; last: {last_fetch_error})"
                )
            if fetch_failures:
                _log(f"[warn] {fetch_failures} search(es) stopped early after a fetch error: results are partial.")

            dupes_removed = scraped_count - len(deduped)
            _log(f"Total unique listings: {len(deduped)} ({dupes_removed} dupes removed)")

            # 2a. Check Notion duplicates upfront
            if auto_notion_push:
                _log("Checking Notion for already-pushed listings to skip enrichment...")
                try:
                    from apt_scrape.notion_push import mark_notion_duplicates
                    num_skipped = await mark_notion_duplicates(deduped)
                    if num_skipped > 0:
                        _log(f"Found {num_skipped} listings already in Notion. Skipping heavy enrichment for them.")
                except Exception as e:
                    _log(f"[warn] Failed to do Notion pre-check: {e}")

            # 2b. Incremental plan: fetch detail pages only for new listings, listings
            # whose stored detail is missing or unreadable (this also backfills rows
            # saved while the portal was blocking us) and listings whose price changed.
            stored = _load_stored(_url_of(l) for l in deduped)
            to_enrich: list[dict] = []
            price_changed: set[str] = set()
            n_backfill = n_reused = 0
            for listing in deduped:
                url = _url_of(listing)
                snap = stored.get(url)
                if snap and _price_changed(snap["price"], listing.get("price", "")):
                    price_changed.add(url)
                if snap and url not in price_changed and _has_ok_detail(snap["raw"]):
                    _copy_stored_detail(listing, snap["raw"])
                    n_reused += 1
                elif not listing.get("notion_skipped"):
                    to_enrich.append(listing)
                    if snap and url not in price_changed:
                        n_backfill += 1
            _log(
                f"{len(deduped) - len(stored)} new, {len(stored)} already known. "
                f"Detail pages to fetch: {len(to_enrich)} ({n_backfill} known without a readable detail, "
                f"{len(price_changed)} with a new price); {n_reused} reuse their stored detail."
            )

            # 3. Enrich details (parse_detail also reads the post date, so there is
            # no separate post-date pass over the same pages)
            enriched_ok: set[str] = set()
            if to_enrich:
                _log(f"Enriching details for {len(to_enrich)} listings (concurrency={detail_concurrency})...")
                try:
                    await enrich_with_details(
                        to_enrich, browser, adapter, None,
                        concurrency=detail_concurrency,
                        rotate_every_batches=vpn_rotate_batches,
                        min_interval=request_delay,
                    )
                except Exception as exc:
                    _log(f"[warn] Detail enrichment stopped early: {exc!r}")

                counts = Counter(l.get("detail_status") or "error" for l in to_enrich)
                summary = ", ".join(f"{counts.get(s, 0)} {s}" for s in _DETAIL_STATUSES)
                _log(f"Details: {summary} (of {len(to_enrich)})")
                failures = [l for l in to_enrich if l.get("detail_status") != "ok"]
                for l in failures[:3]:
                    _log(f"  - {_url_of(l)}: {l.get('detail_status') or 'error'} ({l.get('detail_error') or 'no detail'})")
                if (counts.get("blocked", 0) + counts.get("skipped", 0)) * 2 > len(to_enrich):
                    _log("[warn] Most detail pages were blocked by the portal: stored details are kept "
                         "and these listings are retried on the next run.")

                enriched_ok = {_url_of(l) for l in to_enrich if l.get("detail_status") == "ok"}
                # A refetch that failed falls back to the stored detail (what the upsert keeps anyway)
                for listing in failures:
                    snap = stored.get(_url_of(listing))
                    if snap and _has_ok_detail(snap["raw"]):
                        _copy_stored_detail(listing, snap["raw"])
            else:
                _log("No listings require detail enrichment.")

            # Checkpoint: save cards and detail pages before the slow, paid AI step
            _persist()

            # 6. AI Analysis: only listings that were (re)read, changed price, have no
            # valid stored score or still owe a rescore an earlier run could not finish;
            # the others keep their score.
            def _needs_score(listing: dict) -> bool:
                url = _url_of(listing)
                snap = stored.get(url)
                return bool(
                    snap is None or not snap["valid_score"] or snap["raw"].get("ai_rescore_pending")
                    or url in price_changed or url in enriched_ok
                )

            to_score = [l for l in deduped if not l.get("notion_skipped") and _needs_score(l)]
            n_retry = sum(1 for l in to_score if stored.get(_url_of(l), {}).get("raw", {}).get("ai_rescore_pending"))
            score_urls = {_url_of(l) for l in to_score} if auto_analyse else set()
            for listing in deduped:
                snap = stored.get(_url_of(listing))
                if snap and _url_of(listing) not in score_urls:
                    _copy_stored_ai(listing, snap["raw"])

            ai_usage: dict = {}
            if auto_analyse and to_score:
                _log(f"Running AI analysis on {len(to_score)} listings "
                     f"({len(deduped) - len(to_score)} keep their stored score)...")
                if n_retry:
                    _log(f"  {n_retry} of them retry a rescore an earlier run could not finish.")
                from apt_scrape.analysis import analyse_listings, load_preferences
                try:
                    prefs = load_preferences()
                    ai_usage = await analyse_listings(to_score, prefs)
                    n_failed = ai_usage.get("failed", 0)
                    _log(
                        f"Analysis complete: {ai_usage.get('scored', len(to_score))} scored, "
                        f"{n_failed} failed. {ai_usage.get('tokens_used', 0)} tokens, "
                        f"${ai_usage.get('cost_usd', 0):.4f}"
                    )
                    if n_failed:
                        errors = [l.get("ai_error") for l in to_score if l.get("ai_error")]
                        _log(f"[warn] AI scoring failed for {n_failed} listing(s) (a previous valid score is kept). "
                             f"First error: {errors[0] if errors else 'unknown'}")
                except FileNotFoundError:
                    _log("[warn] preferences.txt not found — skipping analysis.")
                except Exception as exc:
                    _log(f"[warn] AI analysis failed: {exc!r}")
                finally:
                    # Listings get their outcome in place, so this also holds after a partial run
                    scored_urls.update(_url_of(l) for l in to_score if "ai_verdict" in l)
                    # A failed scoring keeps the stored valid score (as the upsert does), so the
                    # Notion push below sees that score instead of the error marker
                    for listing in to_score:
                        snap = stored.get(_url_of(listing))
                        if listing.get("ai_error") and snap and snap["valid_score"]:
                            _copy_stored_ai(listing, snap["raw"])
            elif auto_analyse:
                _log("No listings need AI analysis: all keep their stored score.")

            # 7. Notion Push
            if auto_notion_push and deduped:
                _log("Pushing to Notion...")
                try:
                    from apt_scrape.notion_push import push_listings
                    await push_listings(deduped)
                    _log("Notion push complete.")
                except Exception as exc:
                    # push_listings sets notion_page_id in place, so pages pushed so far are kept
                    _log(f"[warn] Notion push failed: {exc!r}")

            # 8. Upsert listings to DB
            _log("Upserting listings to DB...")
            _persist()

        # 9. Mark job done with stats
        area_stats: dict[str, int] = {}
        for listing in deduped:
            a = listing.get("_area") or ""
            area_stats[a] = area_stats.get(a, 0) + 1

        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                # Deleted while running (DELETE /jobs refuses that, older clients did not)
                logger.warning("Job %d was deleted while running; results saved, status not recorded", job_id)
                return job_id
            job.status = "done"
            job.finished_at = datetime.utcnow()
            job.listing_count = len(deduped)
            job.scraped_count = scraped_count
            job.dupes_removed = dupes_removed
            job.ai_tokens_used = ai_usage.get("tokens_used")
            job.ai_cost_usd = ai_usage.get("cost_usd")
            if ai_usage:
                job.ai_scored_count = ai_usage.get("scored", 0) + ai_usage.get("failed", 0)
            job.area_stats = json.dumps(area_stats)
            session.add(job)
            session.commit()

        _log(f"Job complete. {len(deduped)} listings processed.")
        return job_id

    except asyncio.CancelledError:
        # Backend shutdown/restart or a cancelled task: never leave the job 'running'
        _log("[ERROR] Run cancelled before it finished (backend stopped or restarted).")
        _save_partial()
        try:
            _mark_failed()
        except Exception:
            logger.exception("Job %d: could not mark the cancelled job failed", job_id)
        raise
    except Exception as exc:
        if run_timeout is not None and run_timeout.expired():
            logger.warning("Job %d timed out after %ss", job_id, timeout_sec)
            _log(f"[ERROR] Run timed out after {timeout_sec}s.")
        else:
            logger.exception("Job %d failed", job_id)
            _log(f"[ERROR] {str(exc) or repr(exc)}")
        _save_partial()
        _mark_failed()
        return job_id
    finally:
        # Runs on all exit paths — Exception, BaseException (CancelledError, KeyboardInterrupt), and normal return.
        _flush_log()
