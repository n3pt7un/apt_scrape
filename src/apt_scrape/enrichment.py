"""apt_scrape.enrichment — Detail-page enrichment for listing summaries.

Both ``apt_scrape.cli`` and ``apt_scrape.server`` need to optionally fetch
each listing's detail page and merge the richer data into the summary dict.
This module provides the shared implementation so both callers stay thin.

All functions accept a *browser* parameter (a ``Fetcher`` instance) so they
remain independent of the module-level singleton defined in ``apt_scrape.server``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apt_scrape.browser import Fetcher

from apt_scrape.sites import adapter_for_url

__all__ = [
    "enrich_post_dates",
    "enrich_with_details",
]

logger = logging.getLogger(__name__)


async def enrich_with_details(
    listings: list[dict[str, Any]],
    browser: Fetcher,
    fallback_adapter: Any,
    detail_limit: int | None = None,
    *,
    concurrency: int = 5,
    rotate_every_batches: int = 3,
) -> tuple[int, list[dict[str, str]]]:
    """Fetch detail pages and merge data into listing dicts in-place.

    Listings are fetched in parallel batches of *concurrency*.  Proxy is
    rotated before every *rotate_every_batches*-th batch (starting from
    batch 2) so that long runs spread traffic across servers.

    For each listing, the function fetches the detail page, calls the
    appropriate adapter's ``parse_detail``, and adds several convenience keys
    to the listing dict:

    - ``detail`` — full ``ListingDetail`` dict
    - ``post_date`` — overwritten if the detail page has one
    - ``detail_description``, ``detail_address``, ``detail_features``,
      ``detail_costs``, ``detail_energy_class``, ``detail_agency``

    Args:
        listings: Listing dicts to enrich (modified in-place).
        browser: ``Fetcher`` instance used to fetch pages.
        fallback_adapter: ``SiteAdapter`` used when the listing URL cannot be
            matched to any registered adapter.
        detail_limit: Maximum number of listings to enrich. ``None`` means all.
        concurrency: Number of parallel fetches per batch (default 5).
        rotate_every_batches: Rotate proxy every N batches (default 3).

    Returns:
        Tuple of ``(enriched_count, error_list)`` where each error entry is a
        dict with ``url`` and ``error`` keys.
    """
    to_enrich = listings if detail_limit is None else listings[:detail_limit]
    enriched = 0
    errors: list[dict[str, str]] = []

    batches = [
        to_enrich[i : i + concurrency]
        for i in range(0, len(to_enrich), concurrency)
    ]

    for batch_idx, batch in enumerate(batches):
        # Rotate proxy before every rotate_every_batches-th batch (skip batch 0).
        if batch_idx > 0 and batch_idx % rotate_every_batches == 0:
            logger.info(
                "Rotating proxy before detail batch %d/%d.", batch_idx + 1, len(batches)
            )
            browser._proxy.rotate()
            # Force browser restart with new proxy
            await browser.close()

        logger.info(
            "Detail batch %d/%d: fetching %d listing(s) in parallel.",
            batch_idx + 1,
            len(batches),
            len(batch),
        )

        async def _fetch_detail(
            listing: dict[str, Any], slot: int
        ) -> dict[str, str] | None:
            """Fetch and parse one detail page; mutates *listing* on success."""
            listing_url = str(listing.get("url", "")).strip()
            if not listing_url:
                return None
            listing_adapter = adapter_for_url(listing_url) or fallback_adapter
            try:
                detail_html = await browser.fetch_with_retry(
                    listing_url,
                    wait_selector=listing_adapter.config.detail_wait_selector,
                )
                detail = listing_adapter.parse_detail(detail_html, listing_url).to_dict()
                listing["detail"] = detail
                listing["post_date"] = detail.get("post_date", "") or listing.get("post_date", "")
                listing["detail_description"] = detail.get("description", "")
                listing["detail_address"] = detail.get("address", "")
                listing["detail_features"] = detail.get("extra_info", detail.get("features", {}))
                listing["detail_costs"] = detail.get("costs", {})
                listing["detail_energy_class"] = detail.get("energy_class", "")
                listing["detail_agency"] = detail.get("agency", "")
                return None  # success — no error
            except Exception as exc:
                logger.warning("Failed to enrich detail for %s: %s", listing_url, exc)
                return {"url": listing_url, "error": str(exc)}

        coros = [_fetch_detail(listing, slot) for slot, listing in enumerate(batch)]
        results = await asyncio.gather(*coros, return_exceptions=True)

        for result in results:
            if isinstance(result, BaseException):
                errors.append({"url": "", "error": str(result)})
            elif result is None:
                enriched += 1
            else:
                errors.append(result)

    return enriched, errors


async def enrich_post_dates(
    listings: list[dict[str, Any]],
    browser: Fetcher,
    fallback_adapter: Any,
    *,
    concurrency: int = 5,
    rotate_every_batches: int = 3,
) -> tuple[int, list[dict[str, str]]]:
    """Fetch detail pages to fill in missing ``post_date`` fields in-place.

    Skips listings that already have a non-empty ``post_date``.  Fetches are
    done in parallel batches of *concurrency* with optional proxy rotation
    between batches.

    Args:
        listings: Listing dicts to enrich (modified in-place).
        browser: ``Fetcher`` instance used to fetch pages.
        fallback_adapter: ``SiteAdapter`` used when the listing URL cannot be
            matched to any registered adapter.
        concurrency: Number of parallel fetches per batch (default 5).
        rotate_every_batches: Rotate proxy every N batches (default 3).

    Returns:
        Tuple of ``(enriched_count, error_list)`` where each error entry is a
        dict with ``url`` and ``error`` keys.
    """
    to_process = [
        listing
        for listing in listings
        if not str(listing.get("post_date", "")).strip()
        and str(listing.get("url", "")).strip()
    ]
    enriched = 0
    errors: list[dict[str, str]] = []

    batches = [
        to_process[i : i + concurrency]
        for i in range(0, len(to_process), concurrency)
    ]

    for batch_idx, batch in enumerate(batches):
        if batch_idx > 0 and batch_idx % rotate_every_batches == 0:
            logger.info(
                "Rotating proxy before post-date batch %d/%d.", batch_idx + 1, len(batches)
            )
            browser._proxy.rotate()
            await browser.close()

        logger.info(
            "Post-date batch %d/%d: fetching %d listing(s) in parallel.",
            batch_idx + 1,
            len(batches),
            len(batch),
        )

        async def _fetch_post_date(
            listing: dict[str, Any], slot: int
        ) -> dict[str, str] | None:
            listing_url = str(listing.get("url", "")).strip()
            listing_adapter = adapter_for_url(listing_url) or fallback_adapter
            try:
                detail_html = await browser.fetch_with_retry(
                    listing_url,
                    wait_selector=listing_adapter.config.detail_wait_selector,
                )
                post_date = listing_adapter.extract_post_date_from_detail_html(detail_html)
                listing["post_date"] = post_date
                if post_date:
                    return None  # counted as enriched
                return {"url": listing_url, "error": "post_date not found on page"}
            except Exception as exc:
                logger.warning("Failed to fetch post_date for %s: %s", listing_url, exc)
                return {"url": listing_url, "error": str(exc)}

        coros = [_fetch_post_date(listing, slot) for slot, listing in enumerate(batch)]
        results = await asyncio.gather(*coros, return_exceptions=True)

        for result in results:
            if isinstance(result, BaseException):
                errors.append({"url": "", "error": str(result)})
            elif result is None:
                enriched += 1
            else:
                errors.append(result)

    return enriched, errors
