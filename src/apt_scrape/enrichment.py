"""apt_scrape.enrichment — Detail-page enrichment for listing summaries.

Both ``apt_scrape.cli`` and ``apt_scrape.server`` need to optionally fetch
each listing's detail page and merge the richer data into the summary dict.
This module provides the shared implementation so both callers stay thin.

All functions accept a *browser* parameter so they remain independent of the
``BrowserManager`` singleton defined in ``apt_scrape.server``.

Every listing ``enrich_with_details`` processes gets a ``detail_status``:

- ``ok`` — the page was parsed; ``detail`` and the ``detail_*`` keys are set.
- ``blocked`` — the portal served a bot-challenge page.
- ``error`` — navigation or parsing failed.
- ``empty`` — the page parsed to no title, description or features.
- ``skipped`` — not fetched because the circuit breaker tripped.

Non-``ok`` listings also get a short English ``detail_error`` and never
receive ``detail`` / ``detail_*`` keys, so callers can keep older data.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    from apt_scrape.server import BrowserManager

from apt_scrape.sites import adapter_for_url

__all__ = [
    "BLOCK_BREAKER_THRESHOLD",
    "DETAIL_STATUSES",
    "detail_page_budget",
    "enrich_post_dates",
    "enrich_with_details",
]

logger = logging.getLogger(__name__)

# Seconds between successive slot launches within one parallel batch.
# slot 0 starts immediately, slot 1 after 0.4 s, slot 2 after 0.8 s, etc.
_STAGGER_SECONDS = 0.4

# Stop fetching after this many consecutive blocked pages: a blocked IP does
# not clear within a run, and every further hit deepens the block.
BLOCK_BREAKER_THRESHOLD = 3

DETAIL_STATUSES = ("ok", "blocked", "error", "empty", "skipped")

_SKIPPED_ERROR = "stopped after repeated blocks"
_BLOCKED_ERROR = "blocked by bot protection"
_EMPTY_ERROR = "detail page had no title, description or features"


def _blocked_error_type() -> type[Exception]:
    """Return ``BlockedError`` (imported lazily: ``apt_scrape.server`` imports this module)."""
    from apt_scrape.server import BlockedError

    return BlockedError


def _aborted_error_type() -> type[Exception]:
    """Return ``FetchAborted`` (imported lazily, like ``BlockedError``)."""
    from apt_scrape.server import FetchAborted

    return FetchAborted


def _pick_adapter(listing_url: str, preferred: Any) -> Any:
    """Return the adapter to parse *listing_url* with.

    The caller's adapter wins when it owns the URL, because it carries the
    per-site config overrides (detail selectors, wait selector, page-load
    strategy); the bare registry adapter is only a fallback.
    """
    if preferred is not None and preferred.matches_url(listing_url):
        return preferred
    return adapter_for_url(listing_url) or preferred


def _short_error(exc: BaseException) -> str:
    """First line of *exc* (Playwright appends a long call log), capped at 200 chars."""
    text = str(exc).strip()
    return (text.splitlines()[0] if text else type(exc).__name__)[:200]


def _is_empty_detail(detail: dict[str, Any]) -> bool:
    """Return ``True`` when a parsed detail carries none of the core content.

    Blank strings count as missing, and a features table counts only with at
    least one non-blank value (a ``dd`` without text parses to ``{label: ""}``):
    the same rule the backend API and the LLM context use for "read".
    """
    extra = detail.get("extra_info")
    return not (
        str(detail.get("title") or "").strip()
        or str(detail.get("description") or "").strip()
        or (
            isinstance(extra, dict)
            and any(str(v).strip() for v in extra.values() if not isinstance(v, (dict, list)) and v is not None)
        )
    )


def _fail(listing: dict[str, Any], url: str, kind: str, error: str) -> dict[str, str]:
    """Record a non-ok outcome on *listing* and return the matching error entry."""
    listing["detail_status"] = kind
    listing["detail_error"] = error
    return {"url": url, "error": error, "kind": kind}


def detail_page_budget(listings: list[dict[str, Any]], detail_limit: int | None) -> int | None:
    """Return how many detail pages the post-date pass may still fetch.

    *detail_limit* caps the detail-page fetches of both passes together:
    listings ``enrich_with_details`` actually fetched count against it.

    Returns:
        Remaining page budget, or ``None`` when *detail_limit* is ``None``.
    """
    if detail_limit is None:
        return None
    used = sum(1 for ls in listings if ls.get("detail_status") not in (None, "skipped"))
    return max(0, detail_limit - used)


class _BlockBreaker:
    """Count consecutive blocked fetches across parallel slots.

    A real page (``ok``/``empty``) resets the count; navigation errors leave
    it unchanged.
    """

    def __init__(self, threshold: int = BLOCK_BREAKER_THRESHOLD) -> None:
        self.threshold = threshold
        self.consecutive = 0
        self.tripped = False

    def record(self, kind: str) -> None:
        if kind == "blocked":
            self.consecutive += 1
            if self.consecutive >= self.threshold and not self.tripped:
                self.tripped = True
                logger.warning(
                    "%d consecutive blocked pages — skipping the remaining fetches.",
                    self.consecutive,
                )
        elif kind in ("ok", "empty"):
            self.consecutive = 0


async def _run_in_batches(
    items: list[dict[str, Any]],
    worker: Callable[[dict[str, Any], int], Awaitable[dict[str, str] | None]],
    browser: BrowserManager,
    breaker: _BlockBreaker,
    *,
    concurrency: int,
    rotate_every_batches: int,
    label: str,
) -> list[Any]:
    """Run ``worker(item, slot)`` over *items* in parallel batches.

    The proxy is rotated before every *rotate_every_batches*-th batch
    (starting from batch 2). Rotation closes the shared browser context, so
    it only happens between batches, never with pages in flight. Once the
    breaker trips, workers return without fetching and rotation stops; slots
    of the batch that tripped it are called off when their turn comes (the
    workers pass ``should_abort``), except those already navigating.

    Returns:
        One result per item, in order (exceptions included as values).
    """
    concurrency = max(1, int(concurrency))
    rotate_every_batches = max(1, int(rotate_every_batches))
    batches = [items[i : i + concurrency] for i in range(0, len(items), concurrency)]
    results: list[Any] = []
    for batch_idx, batch in enumerate(batches):
        if not breaker.tripped:
            if batch_idx > 0 and batch_idx % rotate_every_batches == 0:
                logger.info(
                    "Rotating proxy before %s batch %d/%d.", label.lower(), batch_idx + 1, len(batches)
                )
                await browser.rotate_proxy()
            logger.info(
                "%s batch %d/%d: fetching %d listing(s) in parallel.",
                label,
                batch_idx + 1,
                len(batches),
                len(batch),
            )
        coros = [worker(item, slot) for slot, item in enumerate(batch)]
        results.extend(await asyncio.gather(*coros, return_exceptions=True))
    return results


async def enrich_with_details(
    listings: list[dict[str, Any]],
    browser: BrowserManager,
    fallback_adapter: Any,
    detail_limit: int | None = None,
    *,
    concurrency: int = 5,
    rotate_every_batches: int = 3,
    min_interval: float | None = None,
) -> tuple[int, list[dict[str, str]]]:
    """Fetch detail pages and merge data into listing dicts in-place.

    Listings are fetched in parallel batches of *concurrency*.  VPN is rotated
    before every *rotate_every_batches*-th batch (starting from batch 2) so
    that long runs spread traffic across servers.  Within each batch, slot
    launches are staggered by ``_STAGGER_SECONDS * slot_index``, and the
    browser's shared rate limiter spaces request starts by *min_interval*.

    Every processed listing gets ``detail_status`` (see the module docstring).
    On ``ok`` it also gets:

    - ``detail`` — full ``ListingDetail`` dict
    - ``post_date`` — overwritten if the detail page has one
    - ``detail_description``, ``detail_address``, ``detail_features``,
      ``detail_costs``, ``detail_energy_class``, ``detail_agency``

    After ``BLOCK_BREAKER_THRESHOLD`` consecutive blocked pages the remaining
    listings are marked ``skipped`` without being fetched.

    Args:
        listings: Listing dicts to enrich (modified in-place).
        browser: ``BrowserManager`` instance used to fetch pages.
        fallback_adapter: The caller's ``SiteAdapter``. Used for every listing
            whose URL it matches (so per-site overrides apply), and as the
            fallback when no registered adapter matches the URL.
        detail_limit: Maximum number of listings to enrich. ``None`` means all.
        concurrency: Number of parallel fetches per batch (default 5).
        rotate_every_batches: Rotate VPN every N batches (default 3).
        min_interval: Minimum seconds between request starts; ``None`` uses
            the browser's default delay.

    Returns:
        Tuple of ``(enriched_count, error_list)`` where each error entry is a
        dict with ``url``, ``error`` and ``kind`` (``blocked``, ``error``,
        ``empty`` or ``skipped``) keys.
    """
    blocked_error = _blocked_error_type()
    aborted_error = _aborted_error_type()
    to_enrich = listings if detail_limit is None else listings[: max(0, detail_limit)]
    breaker = _BlockBreaker()

    async def _fetch_detail(listing: dict[str, Any], slot: int) -> dict[str, str] | None:
        """Fetch and parse one detail page; mutates *listing* (status always, data on ok)."""
        listing_url = str(listing.get("url", "")).strip()
        if not listing_url:
            return _fail(listing, "", "error", "listing has no URL")
        if breaker.tripped:
            return _fail(listing, listing_url, "skipped", _SKIPPED_ERROR)
        listing_adapter = _pick_adapter(listing_url, fallback_adapter)
        try:
            detail_html = await browser.fetch_page_parallel(
                listing_url,
                wait_selector=listing_adapter.config.detail_wait_selector,
                stagger_secs=slot * _STAGGER_SECONDS,
                wait_until=getattr(listing_adapter.config, "page_load_wait", "domcontentloaded"),
                min_interval=min_interval,
                # Re-checked when this slot's turn comes: an earlier slot may have tripped it
                should_abort=lambda: breaker.tripped,
            )
        except aborted_error:
            return _fail(listing, listing_url, "skipped", _SKIPPED_ERROR)
        except blocked_error:
            breaker.record("blocked")
            logger.warning("Detail page blocked by bot protection: %s", listing_url)
            return _fail(listing, listing_url, "blocked", _BLOCKED_ERROR)
        except Exception as exc:
            logger.warning("Failed to enrich detail for %s: %s", listing_url, exc)
            return _fail(listing, listing_url, "error", _short_error(exc))

        try:
            # BeautifulSoup is CPU-bound; keep it off the event loop.
            parsed = await asyncio.to_thread(listing_adapter.parse_detail, detail_html, listing_url)
            detail = parsed.to_dict()
        except Exception as exc:
            logger.warning("Failed to parse detail page %s: %s", listing_url, exc)
            return _fail(listing, listing_url, "error", f"parse failed: {_short_error(exc)}")

        if _is_empty_detail(detail):
            breaker.record("empty")
            logger.warning("Detail page for %s parsed empty (selector drift?).", listing_url)
            return _fail(listing, listing_url, "empty", _EMPTY_ERROR)

        breaker.record("ok")
        listing["detail"] = detail
        listing["post_date"] = detail.get("post_date", "") or listing.get("post_date", "")
        listing["detail_description"] = detail.get("description", "")
        listing["detail_address"] = detail.get("address", "")
        listing["detail_features"] = detail.get("extra_info", detail.get("features", {}))
        listing["detail_costs"] = detail.get("costs", {})
        listing["detail_energy_class"] = detail.get("energy_class", "")
        listing["detail_agency"] = detail.get("agency", "")
        listing["detail_status"] = "ok"
        listing.pop("detail_error", None)
        return None

    results = await _run_in_batches(
        to_enrich,
        _fetch_detail,
        browser,
        breaker,
        concurrency=concurrency,
        rotate_every_batches=rotate_every_batches,
        label="Detail",
    )

    enriched = 0
    errors: list[dict[str, str]] = []
    for listing, result in zip(to_enrich, results):
        if isinstance(result, BaseException):
            url = str(listing.get("url", "")).strip()
            errors.append(_fail(listing, url, "error", _short_error(result)))
        elif result is None:
            enriched += 1
        else:
            errors.append(result)

    if to_enrich:
        counts = Counter(str(listing.get("detail_status")) for listing in to_enrich)
        logger.info(
            "Detail enrichment: %s.",
            ", ".join(f"{counts.get(s, 0)} {s}" for s in DETAIL_STATUSES),
        )
    return enriched, errors


async def enrich_post_dates(
    listings: list[dict[str, Any]],
    browser: BrowserManager,
    fallback_adapter: Any,
    *,
    concurrency: int = 5,
    rotate_every_batches: int = 3,
    min_interval: float | None = None,
    limit: int | None = None,
) -> tuple[int, list[dict[str, str]]]:
    """Fetch detail pages to fill in missing ``post_date`` fields in-place.

    Skips listings that already have a non-empty ``post_date`` and listings
    ``enrich_with_details`` already processed (they carry ``detail_status``):
    ``parse_detail`` reads the date from the same page, so fetching it again
    cannot add anything. Fetches are done in parallel batches of
    *concurrency* with staggered slot launches, optional VPN rotation between
    batches, and the same block circuit breaker as ``enrich_with_details``.
    ``post_date`` is only written when the page has one.

    Args:
        listings: Listing dicts to enrich (modified in-place).
        browser: ``BrowserManager`` instance used to fetch pages.
        fallback_adapter: The caller's ``SiteAdapter`` (preferred when it
            matches the URL, see ``enrich_with_details``).
        concurrency: Number of parallel fetches per batch (default 5).
        rotate_every_batches: Rotate VPN every N batches (default 3).
        min_interval: Minimum seconds between request starts; ``None`` uses
            the browser's default delay.
        limit: Maximum number of pages to fetch. ``None`` means no limit.

    Returns:
        Tuple of ``(enriched_count, error_list)`` where each error entry is a
        dict with ``url``, ``error`` and ``kind`` (``blocked``, ``error``,
        ``empty`` — no date on the page — or ``skipped``) keys.
    """
    blocked_error = _blocked_error_type()
    to_process = [
        listing
        for listing in listings
        if not str(listing.get("post_date", "")).strip()
        and str(listing.get("url", "")).strip()
        and "detail_status" not in listing
        and "detail" not in listing
    ]
    if limit is not None:
        to_process = to_process[: max(0, limit)]
    aborted_error = _aborted_error_type()
    breaker = _BlockBreaker()

    async def _fetch_post_date(listing: dict[str, Any], slot: int) -> dict[str, str] | None:
        listing_url = str(listing.get("url", "")).strip()
        if breaker.tripped:
            return {"url": listing_url, "error": _SKIPPED_ERROR, "kind": "skipped"}
        listing_adapter = _pick_adapter(listing_url, fallback_adapter)
        try:
            detail_html = await browser.fetch_page_parallel(
                listing_url,
                wait_selector=listing_adapter.config.detail_wait_selector,
                stagger_secs=slot * _STAGGER_SECONDS,
                wait_until=getattr(listing_adapter.config, "page_load_wait", "domcontentloaded"),
                min_interval=min_interval,
                should_abort=lambda: breaker.tripped,
            )
        except aborted_error:
            return {"url": listing_url, "error": _SKIPPED_ERROR, "kind": "skipped"}
        except blocked_error:
            breaker.record("blocked")
            logger.warning("Post-date page blocked by bot protection: %s", listing_url)
            return {"url": listing_url, "error": _BLOCKED_ERROR, "kind": "blocked"}
        except Exception as exc:
            logger.warning("Failed to fetch post_date for %s: %s", listing_url, exc)
            return {"url": listing_url, "error": _short_error(exc), "kind": "error"}

        breaker.record("ok")
        try:
            post_date = await asyncio.to_thread(
                listing_adapter.extract_post_date_from_detail_html, detail_html
            )
        except Exception as exc:
            logger.warning("Failed to parse post_date for %s: %s", listing_url, exc)
            return {"url": listing_url, "error": f"parse failed: {_short_error(exc)}", "kind": "error"}
        if post_date:
            listing["post_date"] = post_date
            return None  # counted as enriched
        return {"url": listing_url, "error": "post_date not found on page", "kind": "empty"}

    results = await _run_in_batches(
        to_process,
        _fetch_post_date,
        browser,
        breaker,
        concurrency=concurrency,
        rotate_every_batches=rotate_every_batches,
        label="Post-date",
    )

    enriched = 0
    errors: list[dict[str, str]] = []
    for listing, result in zip(to_process, results):
        if isinstance(result, BaseException):
            url = str(listing.get("url", "")).strip()
            errors.append({"url": url, "error": _short_error(result), "kind": "error"})
        elif result is None:
            enriched += 1
        else:
            errors.append(result)
    return enriched, errors
