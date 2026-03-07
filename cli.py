#!/usr/bin/env python3
"""
CLI wrapper for the rental scraper.

Usage:
    python cli.py search --city milano --min-price 500 --max-price 1200 --source immobiliare
    python cli.py detail --url "https://www.immobiliare.it/annunci/123456/"
    python cli.py sites
    python cli.py dump --url "https://www.immobiliare.it/affitto-case/milano/" -o dump.html
"""

import argparse
import asyncio
import csv
import io
import json
import sys
from pathlib import Path

from sites import (
    SearchFilters,
    adapter_for_url,
    get_adapter,
    list_adapter_details,
    list_adapters,
)
from server import browser


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _escape_md(text):
    return str(text or "").replace("|", "\\|").replace("\n", " ").strip()


def _listing_export_row(listing):
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


def _listings_to_csv(listings):
    fieldnames = ["title", "price", "post_date", "sqm", "rooms", "bathrooms", "address", "url"]
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for listing in listings:
        writer.writerow(_listing_export_row(listing))
    return output.getvalue()


def _listings_to_markdown_table(listings, max_rows):
    rows = [_listing_export_row(ls) for ls in listings[:max_rows]]
    header = "| title | price | post_date | sqm | rooms | address | url |"
    sep = "|---|---|---|---|---|---|---|"
    body = [
        "| "
        + " | ".join(
            [
                _escape_md(r["title"]),
                _escape_md(r["price"]),
                _escape_md(r["post_date"]),
                _escape_md(r["sqm"]),
                _escape_md(r["rooms"]),
                _escape_md(r["address"]),
                _escape_md(r["url"]),
            ]
        )
        + " |"
        for r in rows
    ]
    table = "\n".join([header, sep] + body)
    if len(listings) > max_rows:
        table += f"\n\nShown {max_rows} of {len(listings)} rows."
    return table


def _normalize_slug(value):
    return value.lower().replace(" ", "-")


def _parse_property_types(raw_value):
    types = [part.strip() for part in str(raw_value or "").split(",")]
    types = [t for t in types if t]
    return types or ["case"]


async def cmd_search(args):
    adapter = get_adapter(args.source)
    all_listings = []
    search_urls = []
    property_types = _parse_property_types(args.property_type)

    city_slug = _normalize_slug(args.city)
    area_slug = _normalize_slug(args.area) if args.area else None

    if args.end_page is not None:
        start_page = args.start_page
        end_page = args.end_page
    else:
        start_page = args.start_page
        end_page = args.start_page + args.max_pages - 1

    if start_page < 1 or end_page < start_page:
        raise ValueError("Invalid page range: ensure start-page >= 1 and end-page >= start-page")

    for property_type in property_types:
        for page_num in range(start_page, end_page + 1):
            filters = SearchFilters(
                city=city_slug,
                area=area_slug,
                operation=args.operation,
                property_type=property_type,
                min_price=args.min_price,
                max_price=args.max_price,
                min_sqm=args.min_sqm,
                max_sqm=args.max_sqm,
                min_rooms=args.min_rooms,
                max_rooms=args.max_rooms,
                published_within=args.published_within,
                sort=args.sort,
                page=page_num,
            )
            url = adapter.build_search_url(filters)
            search_urls.append(url)
            print(
                f"Fetching {property_type} page {page_num}: {url}",
                file=sys.stderr,
            )

            html = await browser.fetch_page(
                url, wait_selector=adapter.config.search_wait_selector
            )
            page_listings = adapter.parse_search(html)

            if not page_listings:
                print(
                    f"No {property_type} listings on page {page_num}, stopping.",
                    file=sys.stderr,
                )
                break

            all_listings.extend([ls.to_dict() for ls in page_listings])
            print(
                f"  → {len(page_listings)} {property_type} listings",
                file=sys.stderr,
            )

    # De-duplicate entries when multiple property types overlap the same listing.
    deduped_listings = []
    seen_urls = set()
    for listing in all_listings:
        listing_url = str(listing.get("url", "")).strip()
        key = listing_url or json.dumps(listing, sort_keys=True, ensure_ascii=False)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        deduped_listings.append(listing)

    ref = SearchFilters(
        city=city_slug,
        area=area_slug,
        operation=args.operation,
        property_type=property_types[0],
        min_price=args.min_price,
        max_price=args.max_price,
        min_sqm=args.min_sqm,
        max_sqm=args.max_sqm,
        min_rooms=args.min_rooms,
        max_rooms=args.max_rooms,
        published_within=args.published_within,
        sort=args.sort,
        page=start_page,
    )

    detail_enriched = 0
    detail_errors = []
    post_date_enriched = 0
    post_date_errors = []

    if args.include_details and deduped_listings:
        to_enrich = deduped_listings
        if args.detail_limit is not None:
            to_enrich = deduped_listings[: args.detail_limit]

        for listing in to_enrich:
            listing_url = str(listing.get("url", "")).strip()
            if not listing_url:
                continue

            listing_adapter = adapter_for_url(listing_url) or adapter
            print(f"Fetching detail: {listing_url}", file=sys.stderr)
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
                listing["detail_features"] = detail.get("metadata", detail.get("features", {}))
                listing["detail_costs"] = detail.get("costs", {})
                listing["detail_energy_class"] = detail.get("energy_class", "")
                listing["detail_agency"] = detail.get("agency", "")
                detail_enriched += 1
            except Exception as e:
                detail_errors.append({"url": listing_url, "error": str(e)})

    # post_date is required by default for all scrapes.
    for listing in deduped_listings:
        if str(listing.get("post_date", "")).strip():
            continue

        listing_url = str(listing.get("url", "")).strip()
        if not listing_url:
            continue

        listing_adapter = adapter_for_url(listing_url) or adapter
        print(f"Fetching post date: {listing_url}", file=sys.stderr)
        try:
            detail_html = await browser.fetch_page(
                listing_url,
                wait_selector=listing_adapter.config.detail_wait_selector,
            )
            post_date = listing_adapter.extract_post_date_from_detail_html(detail_html)
            listing["post_date"] = post_date
            if post_date:
                post_date_enriched += 1
        except Exception as e:
            post_date_errors.append({"url": listing_url, "error": str(e)})

    result = {
        "count": len(deduped_listings),
        "source": adapter.config.display_name,
        "search_url": adapter.build_search_url(ref),
        "search_urls": search_urls,
        "city": city_slug,
        "area": area_slug,
        "property_type": property_types if len(property_types) > 1 else property_types[0],
        "start_page": start_page,
        "end_page": end_page,
        "details_requested": args.include_details,
        "details_enriched": detail_enriched,
        "detail_errors": detail_errors,
        "post_date_enriched": post_date_enriched,
        "post_date_errors": post_date_errors,
        "csv": _listings_to_csv(deduped_listings) if args.include_csv else "",
        "table": _listings_to_markdown_table(deduped_listings, args.table_max_rows)
        if args.include_table
        else "",
        "listings": deduped_listings,
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


async def cmd_detail(args):
    adapter = adapter_for_url(args.url)
    if adapter is None:
        return json.dumps(
            {"error": f"No adapter matches URL: {args.url}"},
            indent=2,
            ensure_ascii=False,
        )

    print(f"Fetching: {args.url}", file=sys.stderr)
    html = await browser.fetch_page(
        args.url, wait_selector=adapter.config.detail_wait_selector
    )
    detail = adapter.parse_detail(html, args.url)
    return json.dumps(detail.to_dict(), indent=2, ensure_ascii=False)


async def cmd_dump(args):
    print(f"Fetching: {args.url}", file=sys.stderr)
    html = await browser.fetch_page(args.url, wait_selector=args.wait_selector)
    return html


def cmd_sites(_args):
    details = list_adapter_details()
    header = f"{'ID':<16} {'Name':<20} {'Base URL'}"
    print(header)
    print("-" * len(header))
    for d in details:
        print(f"{d['site_id']:<16} {d['display_name']:<20} {d['base_url']}")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def build_parser():
    available_sites = list_adapters()

    parser = argparse.ArgumentParser(
        description="Italian Real Estate Listing Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Search apartments for rent in Milan, 500-1200 EUR, 40-80 sqm
  python cli.py search --city milano --operation affitto \\
    --property-type appartamenti --min-price 500 --max-price 1200 \\
    --min-sqm 40 --max-sqm 80

  # Search on Casa.it instead
  python cli.py search --city bologna --source casa --max-price 900

  # Get full details of a specific listing (auto-detects site)
  python cli.py detail --url "https://www.immobiliare.it/annunci/123456/"

  # List all supported sites
  python cli.py sites

  # Dump raw HTML for debugging selectors
  python cli.py dump --url "https://www.immobiliare.it/affitto-case/milano/" -o dump.html

Available sites: {', '.join(available_sites)}
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # --- search ---
    p_search = sub.add_parser("search", help="Search for listings")
    p_search.add_argument("--city", required=True, help="City slug")
    p_search.add_argument(
        "--area",
        default=None,
        help="Optional area slug inside city (e.g. precotto)",
    )
    p_search.add_argument(
        "--operation", choices=["affitto", "vendita"], default="affitto"
    )
    p_search.add_argument(
        "--property-type",
        default="case",
        help="Property type slug(s). Use comma-separated values for OR logic, e.g. appartamenti,attici",
    )
    p_search.add_argument("--min-price", type=int, default=None)
    p_search.add_argument("--max-price", type=int, default=None)
    p_search.add_argument("--min-sqm", type=int, default=None)
    p_search.add_argument("--max-sqm", type=int, default=None)
    p_search.add_argument("--min-rooms", type=int, default=None)
    p_search.add_argument("--max-rooms", type=int, default=None)
    p_search.add_argument(
        "--published-within", choices=["1", "3", "7", "14", "30"], default=None
    )
    p_search.add_argument("--sort", default="rilevanza", help="Sort order: rilevanza, piu-recenti, etc.")
    p_search.add_argument(
        "--source", choices=available_sites, default=available_sites[0]
    )
    p_search.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First result page to fetch (1-based)",
    )
    p_search.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="Last result page to fetch (inclusive). Overrides --max-pages when set",
    )
    p_search.add_argument("--max-pages", type=int, default=1)
    p_search.add_argument(
        "--include-details",
        action="store_true",
        help="Fetch each listing URL and enrich results with full detail fields",
    )
    p_search.add_argument(
        "--detail-limit",
        type=int,
        default=None,
        help="Max number of listing detail pages to fetch (default: all)",
    )
    p_search.add_argument(
        "--include-csv",
        action="store_true",
        help="Include CSV export in JSON output under key 'csv'",
    )
    p_search.add_argument(
        "--include-table",
        action="store_true",
        help="Include markdown table preview in JSON output under key 'table'",
    )
    p_search.add_argument(
        "--table-max-rows",
        type=int,
        default=20,
        help="Maximum rows in markdown table preview",
    )
    p_search.add_argument("-o", "--output", type=str, default=None)

    # --- detail ---
    p_detail = sub.add_parser("detail", help="Get full listing details")
    p_detail.add_argument("--url", required=True)
    p_detail.add_argument("-o", "--output", type=str, default=None)

    # --- dump ---
    p_dump = sub.add_parser("dump", help="Dump raw HTML (debug)")
    p_dump.add_argument("--url", required=True)
    p_dump.add_argument("--wait-selector", default=None)
    p_dump.add_argument("-o", "--output", type=str, default=None)

    # --- sites ---
    sub.add_parser("sites", help="List supported sites")

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "sites":
            cmd_sites(args)
            return

        if args.command == "search":
            result = await cmd_search(args)
        elif args.command == "detail":
            result = await cmd_detail(args)
        elif args.command == "dump":
            result = await cmd_dump(args)
        else:
            parser.print_help()
            sys.exit(1)

        if hasattr(args, "output") and args.output:
            Path(args.output).write_text(result, encoding="utf-8")
            print(f"Saved to {args.output}", file=sys.stderr)
        else:
            print(result)

    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
