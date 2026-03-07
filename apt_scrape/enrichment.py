"""apt_scrape.enrichment — Detail-page enrichment for listing summaries.

Both ``apt_scrape.cli`` and ``apt_scrape.server`` need to optionally fetch
each listing's detail page and merge the richer data into the summary dict.
This module provides the shared implementation so both callers stay thin.

All functions accept a *browser* parameter so they remain independent of the
``BrowserManager`` singleton defined in ``apt_scrape.server``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apt_scrape.server import BrowserManager

from apt_scrape.sites import adapter_for_url

__all__ = [
    "enrich_post_dates",
    "enrich_with_details",
]

logger = logging.getLogger(__name__)


async def enrich_with_details(
    listings: list[dict[str, Any]],
    browser: BrowserManager,
    fallback_adapter: Any,
    detail_limit: int | None = None,
) -> tuple[int, list[dict[str, str]]]:
    """Fetch detail pages and merge data into listing dicts in-place.

    For each listing, the function fetches the detail page, calls the
    appropriate adapter's ``parse_detail``, and adds several convenience keys
    to the listing dict:

    - ``detail`` — full ``ListingDetail`` dict
    - ``post_date`` — overwritten if the detail page has one
    - ``detail_description``, ``detail_address``, ``detail_features``,
      ``detail_costs``, ``detail_energy_class``, ``detail_agency``

    Args:
        listings: Listing dicts to enrich (modified in-place).
        browser: ``BrowserManager`` instance used to fetch pages.
        fallback_adapter: ``SiteAdapter`` used when the listing URL cannot be
            matched to any registered adapter.
        detail_limit: Maximum number of listings to enrich. ``None`` means all.

    Returns:
        Tuple of ``(enriched_count, error_list)`` where each error entry is a
        dict with ``url`` and ``error`` keys.
    """
    to_enrich = listings if detail_limit is None else listings[:detail_limit]
    enriched = 0
    errors: list[dict[str, str]] = []

    for listing in to_enrich:
        listing_url = str(listing.get("url", "")).strip()
        if not listing_url:
            continue

        listing_adapter = adapter_for_url(listing_url) or fallback_adapter
        try:
            detail_html = await browser.fetch_page(
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
            enriched += 1
        except Exception as exc:
            logger.warning("Failed to enrich detail for %s: %s", listing_url, exc)
            errors.append({"url": listing_url, "error": str(exc)})

    return enriched, errors


async def enrich_post_dates(
    listings: list[dict[str, Any]],
    browser: BrowserManager,
    fallback_adapter: Any,
) -> tuple[int, list[dict[str, str]]]:
    """Fetch detail pages to fill in missing ``post_date`` fields in-place.

    Skips listings that already have a non-empty ``post_date``.

    Args:
        listings: Listing dicts to enrich (modified in-place).
        browser: ``BrowserManager`` instance used to fetch pages.
        fallback_adapter: ``SiteAdapter`` used when the listing URL cannot be
            matched to any registered adapter.

    Returns:
        Tuple of ``(enriched_count, error_list)`` where each error entry is a
        dict with ``url`` and ``error`` keys.
    """
    enriched = 0
    errors: list[dict[str, str]] = []

    for listing in listings:
        if str(listing.get("post_date", "")).strip():
            continue

        listing_url = str(listing.get("url", "")).strip()
        if not listing_url:
            continue

        listing_adapter = adapter_for_url(listing_url) or fallback_adapter
        try:
            detail_html = await browser.fetch_page(
                listing_url,
                wait_selector=listing_adapter.config.detail_wait_selector,
            )
            post_date = listing_adapter.extract_post_date_from_detail_html(detail_html)
            listing["post_date"] = post_date
            if post_date:
                enriched += 1
        except Exception as exc:
            logger.warning("Failed to fetch post_date for %s: %s", listing_url, exc)
            errors.append({"url": listing_url, "error": str(exc)})

    return enriched, errors
