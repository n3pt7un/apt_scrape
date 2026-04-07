#!/usr/bin/env python3
"""apt_scrape.cli — Command-line interface for the rental scraper.

Usage::

    python -m apt_scrape.cli search --city milano --min-price 500 --max-price 1200
    python -m apt_scrape.cli detail --url "https://www.immobiliare.it/annunci/123456/"
    python -m apt_scrape.cli sites
    python -m apt_scrape.cli dump --url "https://www.immobiliare.it/affitto-case/milano/" -o dump.html
"""

import asyncio
import json
import os
from pathlib import Path

import click

from apt_scrape.enrichment import enrich_post_dates, enrich_with_details
from apt_scrape.export import listings_to_csv, listings_to_markdown_table
from apt_scrape.server import browser
from apt_scrape.sites import (
    SearchFilters,
    adapter_for_url,
    get_adapter,
    list_adapter_details,
    list_adapters,
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_slug(value: str) -> str:
    """Return *value* lowercased with spaces replaced by hyphens."""
    return value.lower().replace(" ", "-")


def _parse_property_types(raw_value: str) -> list[str]:
    """Split a comma-separated property-type string into individual slugs.

    Args:
        raw_value: Raw option value, e.g. ``"appartamenti,attici"``.

    Returns:
        Non-empty list of slug strings; defaults to ``["case"]``.
    """
    types = [part.strip() for part in str(raw_value or "").split(",")]
    types = [t for t in types if t]
    return types or ["case"]


def _write_output(result: str, output: str | None) -> None:
    """Write *result* to *output* file, or print to stdout."""
    if output:
        Path(output).write_text(result, encoding="utf-8")
        click.echo(f"Saved to {output}", err=True)
    else:
        click.echo(result)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
def cli() -> None:
    """Italian real estate listing scraper.

    Scrapes Immobiliare.it, Casa.it, and other supported sites via a stealth
    browser. All commands write JSON to stdout (or -o/--output) and progress
    messages to stderr.
    """


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@cli.command("search")
@click.option("--city", required=True, help="City slug (e.g. milano, roma).")
@click.option("--area", default=None, help="Sub-area slug inside city (e.g. precotto).")
@click.option(
    "--operation",
    type=click.Choice(["affitto", "vendita"]),
    default="affitto",
    show_default=True,
    help="Contract type.",
)
@click.option(
    "--property-type",
    default="case",
    show_default=True,
    help=(
        "Property category slug. Comma-separate multiple values for OR logic "
        "(e.g. appartamenti,attici)."
    ),
)
@click.option("--min-price", type=int, default=None, help="Minimum price in EUR.")
@click.option("--max-price", type=int, default=None, help="Maximum price in EUR.")
@click.option("--min-sqm", type=int, default=None, help="Minimum surface area in m².")
@click.option("--max-sqm", type=int, default=None, help="Maximum surface area in m².")
@click.option("--min-rooms", type=int, default=None, help="Minimum number of rooms.")
@click.option("--max-rooms", type=int, default=None, help="Maximum number of rooms.")
@click.option(
    "--published-within",
    type=click.Choice(["1", "3", "7", "14", "30"]),
    default=None,
    help="Only show listings published within N days.",
)
@click.option(
    "--sort",
    default="rilevanza",
    show_default=True,
    help="Sort order (e.g. rilevanza, piu-recenti).",
)
@click.option(
    "--source",
    default=None,
    help="Site adapter to use. Defaults to the first registered site.",
)
@click.option(
    "--start-page",
    type=int,
    default=1,
    show_default=True,
    help="First result page to fetch (1-based).",
)
@click.option(
    "--end-page",
    type=int,
    default=None,
    help="Last result page to fetch (inclusive). Overrides --max-pages.",
)
@click.option(
    "--max-pages",
    type=int,
    default=1,
    show_default=True,
    help="Number of result pages to fetch.",
)
@click.option(
    "--include-details",
    is_flag=True,
    help="Fetch each listing's detail page and enrich results.",
)
@click.option(
    "--detail-limit",
    type=int,
    default=None,
    help="Max number of detail pages to fetch (default: all).",
)
@click.option(
    "--detail-concurrency",
    type=int,
    default=None,
    show_default=True,
    help="Parallel detail page fetches per batch (default: DETAIL_CONCURRENCY env var or 5).",
)
@click.option(
    "--vpn-rotate-batches",
    type=int,
    default=None,
    show_default=True,
    help="Rotate VPN every N batches of detail fetches (default: VPN_ROTATE_EVERY_BATCHES env var or 3).",
)
@click.option("--include-csv", is_flag=True, help="Embed CSV export in JSON output.")
@click.option("--include-table", is_flag=True, help="Embed markdown table in JSON output.")
@click.option(
    "--table-max-rows",
    type=int,
    default=20,
    show_default=True,
    help="Row limit for the markdown table preview.",
)
@click.option("--analyse", is_flag=True, help="Score each listing with AI against preferences.txt.")
@click.option("--push-notion", "push_notion", is_flag=True, help="Push listings to Notion Apartments DB.")
@click.option("-o", "--output", default=None, type=click.Path(), help="Write output to file.")
def search(
    city: str,
    area: str | None,
    operation: str,
    property_type: str,
    min_price: int | None,
    max_price: int | None,
    min_sqm: int | None,
    max_sqm: int | None,
    min_rooms: int | None,
    max_rooms: int | None,
    published_within: str | None,
    sort: str,
    source: str | None,
    start_page: int,
    end_page: int | None,
    max_pages: int,
    include_details: bool,
    detail_limit: int | None,
    detail_concurrency: int | None,
    vpn_rotate_batches: int | None,
    include_csv: bool,
    include_table: bool,
    table_max_rows: int,
    analyse: bool,
    push_notion: bool,
    output: str | None,
) -> None:
    """Search for property listings and output structured JSON."""
    available_sites = list_adapters()
    resolved_source = source or available_sites[0]
    if resolved_source not in available_sites:
        raise click.BadParameter(
            f"'{resolved_source}' is not a registered site. "
            f"Available: {', '.join(available_sites)}",
            param_hint="--source",
        )

    result = asyncio.run(
        _run_search(
            city=city,
            area=area,
            operation=operation,
            property_type=property_type,
            min_price=min_price,
            max_price=max_price,
            min_sqm=min_sqm,
            max_sqm=max_sqm,
            min_rooms=min_rooms,
            max_rooms=max_rooms,
            published_within=published_within,
            sort=sort,
            source=resolved_source,
            start_page=start_page,
            end_page=end_page,
            max_pages=max_pages,
            include_details=include_details,
            detail_limit=detail_limit,
            detail_concurrency=detail_concurrency,
            vpn_rotate_batches=vpn_rotate_batches,
            include_csv=include_csv,
            include_table=include_table,
            table_max_rows=table_max_rows,
            analyse=analyse,
            push_notion=push_notion,
        )
    )
    _write_output(result, output)


async def _run_search(
    city: str,
    area: str | None,
    operation: str,
    property_type: str,
    min_price: int | None,
    max_price: int | None,
    min_sqm: int | None,
    max_sqm: int | None,
    min_rooms: int | None,
    max_rooms: int | None,
    published_within: str | None,
    sort: str,
    source: str,
    start_page: int,
    end_page: int | None,
    max_pages: int,
    include_details: bool,
    detail_limit: int | None,
    detail_concurrency: int | None,
    vpn_rotate_batches: int | None,
    include_csv: bool,
    include_table: bool,
    table_max_rows: int,
    analyse: bool = False,
    push_notion: bool = False,
) -> str:
    """Async implementation of the search command."""
    try:
        adapter = get_adapter(source)
        all_listings: list[dict] = []
        search_urls: list[str] = []
        property_types = _parse_property_types(property_type)

        city_slug = _normalize_slug(city)
        area_slug = _normalize_slug(area) if area else None

        resolved_end = end_page if end_page is not None else start_page + max_pages - 1

        if start_page < 1 or resolved_end < start_page:
            raise click.UsageError(
                "Invalid page range: start-page must be >= 1 and end-page >= start-page."
            )

        for pt in property_types:
            for page_num in range(start_page, resolved_end + 1):
                filters = SearchFilters(
                    city=city_slug,
                    area=area_slug,
                    operation=operation,
                    property_type=pt,
                    min_price=min_price,
                    max_price=max_price,
                    min_sqm=min_sqm,
                    max_sqm=max_sqm,
                    min_rooms=min_rooms,
                    max_rooms=max_rooms,
                    published_within=published_within,
                    sort=sort,
                    page=page_num,
                )
                url = adapter.build_search_url(filters)
                search_urls.append(url)
                click.echo(f"Fetching {pt} page {page_num}: {url}", err=True)

                html = await browser.fetch_page(
                    url, wait_selector=adapter.config.search_wait_selector
                )
                page_listings = adapter.parse_search(html)

                if not page_listings:
                    click.echo(
                        f"No {pt} listings on page {page_num}, stopping.", err=True
                    )
                    break

                all_listings.extend([ls.to_dict() for ls in page_listings])
                click.echo(f"  -> {len(page_listings)} {pt} listings", err=True)

        # Deduplicate when multiple property types overlap.
        seen_urls: set[str] = set()
        deduped: list[dict] = []
        for listing in all_listings:
            listing_url = str(listing.get("url", "")).strip()
            key = listing_url or json.dumps(listing, sort_keys=True, ensure_ascii=False)
            if key not in seen_urls:
                seen_urls.add(key)
                deduped.append(listing)

        ref = SearchFilters(
            city=city_slug,
            area=area_slug,
            operation=operation,
            property_type=property_types[0],
            min_price=min_price,
            max_price=max_price,
            min_sqm=min_sqm,
            max_sqm=max_sqm,
            min_rooms=min_rooms,
            max_rooms=max_rooms,
            published_within=published_within,
            sort=sort,
            page=start_page,
        )

        detail_enriched = 0
        detail_errors: list[dict] = []
        post_date_enriched = 0
        post_date_errors: list[dict] = []

        from apt_scrape.server import DETAIL_CONCURRENCY, VPN_ROTATE_EVERY_BATCHES
        eff_concurrency = detail_concurrency if detail_concurrency is not None else DETAIL_CONCURRENCY
        eff_rotate = vpn_rotate_batches if vpn_rotate_batches is not None else VPN_ROTATE_EVERY_BATCHES

        if include_details and deduped:
            detail_enriched, detail_errors = await enrich_with_details(
                deduped, browser, adapter, detail_limit,
                concurrency=eff_concurrency,
                rotate_every_batches=eff_rotate,
            )

        post_date_enriched, post_date_errors = await enrich_post_dates(
            deduped, browser, adapter,
            concurrency=eff_concurrency,
            rotate_every_batches=eff_rotate,
        )

        # Stamp area/city onto each listing for analysis and Notion push
        for listing in deduped:
            listing["_area"] = area_slug or ""
            listing["_city"] = city_slug

        if analyse and deduped:
            from apt_scrape.analysis import analyse_listings, load_preferences
            try:
                prefs = load_preferences()
            except FileNotFoundError as e:
                click.echo(f"[warn] {e} — skipping AI analysis.", err=True)
            else:
                await analyse_listings(deduped, prefs)

        if push_notion and deduped:
            from apt_scrape.notion_push import push_listings
            await push_listings(deduped)

        return json.dumps(
            {
                "count": len(deduped),
                "source": adapter.config.display_name,
                "search_url": adapter.build_search_url(ref),
                "search_urls": search_urls,
                "city": city_slug,
                "area": area_slug,
                "property_type": property_types if len(property_types) > 1 else property_types[0],
                "start_page": start_page,
                "end_page": resolved_end,
                "details_requested": include_details,
                "details_enriched": detail_enriched,
                "detail_errors": detail_errors,
                "post_date_enriched": post_date_enriched,
                "post_date_errors": post_date_errors,
                "csv": listings_to_csv(deduped) if include_csv else "",
                "table": listings_to_markdown_table(deduped, table_max_rows)
                if include_table
                else "",
                "listings": deduped,
            },
            indent=2,
            ensure_ascii=False,
        )
    finally:
        await browser.close()


# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


@cli.command("push")
@click.argument("json_file", type=click.Path(exists=True))
@click.option("--analyse", is_flag=True, help="Score each listing with AI against preferences.txt.")
@click.option("--push-notion", "push_notion", is_flag=True, help="Push listings to Notion Apartments DB.")
def push(json_file: str, analyse: bool, push_notion: bool) -> None:
    """Post-process an existing JSON result file: re-run analysis and/or push to Notion.

    JSON_FILE is the path to a previously saved search result JSON file.
    The file is updated in-place (atomically) with any new ai_* or notion_* fields.
    """
    asyncio.run(_run_push(json_file, analyse, push_notion))


async def _run_push(json_file: str, analyse: bool, push_notion: bool) -> None:
    """Async implementation of the push command."""
    import tempfile

    path = Path(json_file)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    listings = envelope.get("listings", [])
    area_slug = envelope.get("area") or ""
    city_slug = envelope.get("city") or ""

    # Stamp area/city onto each listing
    for listing in listings:
        listing["_area"] = area_slug
        listing["_city"] = city_slug

    if analyse and listings:
        from apt_scrape.analysis import analyse_listings, load_preferences
        try:
            prefs = load_preferences()
        except FileNotFoundError as e:
            click.echo(f"[warn] {e} — skipping AI analysis.", err=True)
        else:
            await analyse_listings(listings, prefs)

    if push_notion and listings:
        from apt_scrape.notion_push import push_listings
        await push_listings(listings)

    # Atomic write back (write to .tmp then rename to avoid corruption on failure)
    envelope["listings"] = listings
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, ensure_ascii=False)
        Path(tmp_path).replace(path)
        click.echo(f"Updated {json_file}", err=True)
    except Exception:
        os.unlink(tmp_path)
        raise


# ---------------------------------------------------------------------------
# detail
# ---------------------------------------------------------------------------


@cli.command("detail")
@click.option("--url", required=True, help="Full listing URL (auto-detects site).")
@click.option("-o", "--output", default=None, type=click.Path(), help="Write output to file.")
def detail(url: str, output: str | None) -> None:
    """Fetch and display full details for a single listing URL."""
    result = asyncio.run(_run_detail(url))
    _write_output(result, output)


async def _run_detail(url: str) -> str:
    """Async implementation of the detail command."""
    try:
        adapter = adapter_for_url(url)
        if adapter is None:
            return json.dumps(
                {"error": f"No adapter matches URL: {url}"}, indent=2, ensure_ascii=False
            )

        click.echo(f"Fetching: {url}", err=True)
        html = await browser.fetch_page(url, wait_selector=adapter.config.detail_wait_selector)
        return json.dumps(
            adapter.parse_detail(html, url).to_dict(), indent=2, ensure_ascii=False
        )
    finally:
        await browser.close()


# ---------------------------------------------------------------------------
# dump
# ---------------------------------------------------------------------------


@cli.command("dump")
@click.option("--url", required=True, help="URL to fetch.")
@click.option(
    "--wait-selector",
    default=None,
    help="CSS selector to wait for before capturing HTML.",
)
@click.option("-o", "--output", default=None, type=click.Path(), help="Write output to file.")
def dump(url: str, wait_selector: str | None, output: str | None) -> None:
    """Dump raw rendered HTML for debugging selectors."""
    result = asyncio.run(_run_dump(url, wait_selector))
    _write_output(result, output)


async def _run_dump(url: str, wait_selector: str | None) -> str:
    """Async implementation of the dump command."""
    try:
        click.echo(f"Fetching: {url}", err=True)
        return await browser.fetch_page(url, wait_selector=wait_selector)
    finally:
        await browser.close()


# ---------------------------------------------------------------------------
# sites
# ---------------------------------------------------------------------------


@cli.command("sites")
def sites() -> None:
    """List all registered site adapters."""
    details = list_adapter_details()
    header = f"{'ID':<16} {'Name':<20} {'Base URL'}"
    click.echo(header)
    click.echo("-" * len(header))
    for d in details:
        click.echo(f"{d['site_id']:<16} {d['display_name']:<20} {d['base_url']}")


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR = Path(os.getenv("DATA_DIR", "data"))

try:
    from camoufox.async_api import AsyncCamoufox
except ImportError:  # pragma: no cover
    AsyncCamoufox = None  # type: ignore[assignment,misc]


@cli.command("login")
@click.option(
    "--site",
    required=True,
    help="Site ID to log into (e.g. immobiliare, casa, idealista).",
)
@click.option(
    "--identifier",
    default="default",
    show_default=True,
    help="Label to distinguish cookie files when using multiple accounts.",
)
def login(site: str, identifier: str) -> None:
    """Open a headed browser to log into a site and save session cookies.

    After the browser opens, log in manually, then return to the terminal
    and press Enter to capture cookies.
    """
    available_sites = list_adapters()
    if site not in available_sites:
        raise click.BadParameter(
            f"'{site}' is not a registered site. Available: {', '.join(available_sites)}",
            param_hint="--site",
        )
    asyncio.run(_run_login(site, identifier))


async def _run_login(site_id: str, identifier: str) -> None:
    """Async implementation of the login command."""
    from apt_scrape.cookies import cookie_path, save_cookies

    adapter = get_adapter(site_id)
    login_url = adapter.config.login_url
    if not login_url:
        click.echo(f"Error: site '{site_id}' has no login_url configured.", err=True)
        raise SystemExit(1)

    click.echo(f"Opening headed browser for {adapter.config.display_name}...", err=True)
    click.echo(f"Login URL: {login_url}", err=True)

    async with AsyncCamoufox(headless=False) as browser_instance:
        context = await browser_instance.new_context()
        page = await context.new_page()
        await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

        click.echo(
            "\nLog in to the site in the browser window.\n"
            "When you're done, come back here and press Enter to save cookies.",
            err=True,
        )
        click.pause("")

        cookies = await context.cookies()
        if not cookies:
            click.echo("Warning: no cookies captured. Login may have failed.", err=True)
        else:
            path = cookie_path(site_id, identifier, data_dir=_DEFAULT_DATA_DIR)
            save_cookies(cookies, path)
            click.echo(f"Saved {len(cookies)} cookies to {path}", err=True)

        await page.close()
        await context.close()

    click.echo("Done. Browser closed.", err=True)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
