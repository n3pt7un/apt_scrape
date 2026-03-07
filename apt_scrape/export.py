"""apt_scrape.export — CSV and Markdown table export helpers for listing data.

Both ``apt_scrape.cli`` and ``apt_scrape.server`` produce listing output in
CSV and Markdown formats. This module holds the shared implementation so
those modules stay thin.
"""

import csv
import io
from typing import Any

__all__ = [
    "listing_export_row",
    "listings_to_csv",
    "listings_to_markdown_table",
]

# Ordered column set used by both CSV and Markdown exports.
_EXPORT_FIELDS = ["title", "price", "post_date", "sqm", "rooms", "bathrooms", "address", "url"]


def listing_export_row(listing: dict[str, Any]) -> dict[str, str]:
    """Convert a listing dict to a flat, string-only export row.

    Prefers ``detail_address`` over ``address`` when both are present, which
    is the case after detail-page enrichment.

    Args:
        listing: A listing dict produced by ``ListingSummary.to_dict()`` or
            enriched with detail fields.

    Returns:
        Dict with the same keys as ``_EXPORT_FIELDS``, all string values.
    """
    return {
        "title": str(listing.get("title", "")),
        "price": str(listing.get("price", "")),
        "post_date": str(listing.get("post_date", "")),
        "sqm": str(listing.get("sqm", "")),
        "rooms": str(listing.get("rooms", "")),
        "bathrooms": str(listing.get("bathrooms", "")),
        "address": str(listing.get("detail_address") or listing.get("address", "")),
        "url": str(listing.get("url", "")),
    }


def listings_to_csv(listings: list[dict[str, Any]]) -> str:
    """Serialize a list of listings to CSV format.

    Args:
        listings: List of listing dicts.

    Returns:
        CSV string including a header row, encoded as UTF-8 text.
    """
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_EXPORT_FIELDS)
    writer.writeheader()
    for listing in listings:
        writer.writerow(listing_export_row(listing))
    return output.getvalue()


def _escape_md(text: Any) -> str:
    """Escape Markdown table special characters in *text*."""
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def listings_to_markdown_table(listings: list[dict[str, Any]], max_rows: int) -> str:
    """Format a list of listings as a Markdown table.

    Args:
        listings: List of listing dicts.
        max_rows: Maximum number of data rows to include. When the list is
            longer than this, a truncation note is appended.

    Returns:
        Markdown table string.
    """
    rows = [listing_export_row(ls) for ls in listings[:max_rows]]
    header = "| title | price | post_date | sqm | rooms | address | url |"
    sep = "|---|---|---|---|---|---|---|"
    body = [
        "| "
        + " | ".join([
            _escape_md(r["title"]),
            _escape_md(r["price"]),
            _escape_md(r["post_date"]),
            _escape_md(r["sqm"]),
            _escape_md(r["rooms"]),
            _escape_md(r["address"]),
            _escape_md(r["url"]),
        ])
        + " |"
        for r in rows
    ]
    table = "\n".join([header, sep] + body)
    if len(listings) > max_rows:
        table += f"\n\nShown {max_rows} of {len(listings)} rows."
    return table
