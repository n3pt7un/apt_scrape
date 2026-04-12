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
from apt_scrape.server import fetcher
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

                html = await fetcher.fetch_with_retry(
                    url,
                    wait_selector=adapter.config.search_wait_selector,
                    wait_timeout=adapter.config.search_wait_timeout / 1000,
                    rejection_checker=adapter.detect_rejection,
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

        # Pre-check Notion to skip enrichment for already-pushed listings
        notion_known = 0
        to_enrich = deduped
        if push_notion and deduped:
            click.echo("Checking Notion for already-pushed listings...", err=True)
            try:
                from apt_scrape.notion_push import fetch_all_notion_listings
                notion_url_map = await fetch_all_notion_listings(
                    log_fn=lambda msg: click.echo(msg, err=True),
                )
                if notion_url_map:
                    for listing in deduped:
                        url = str(listing.get("url", "")).strip()
                        page_id = notion_url_map.get(url)
                        if page_id:
                            listing["notion_skipped"] = True
                            listing["notion_page_id"] = page_id
                            notion_known += 1
                    to_enrich = [l for l in deduped if not l.get("notion_skipped")]
                    click.echo(
                        f"Notion pre-check: {notion_known} already in Notion, "
                        f"{len(to_enrich)} new to enrich",
                        err=True,
                    )
            except Exception as e:
                click.echo(f"[warn] Notion pre-check failed (continuing): {e}", err=True)

        if include_details and to_enrich:
            click.echo(f"Enriching {len(to_enrich)} listings...", err=True)
            detail_enriched, detail_errors = await enrich_with_details(
                to_enrich, fetcher, adapter, detail_limit,
                concurrency=eff_concurrency,
                rotate_every_batches=eff_rotate,
            )

        if to_enrich:
            post_date_enriched, post_date_errors = await enrich_post_dates(
                to_enrich, fetcher, adapter,
                concurrency=eff_concurrency,
                rotate_every_batches=eff_rotate,
            )

        # Stamp area/city onto each listing for analysis and Notion push
        for listing in deduped:
            listing["_area"] = area_slug or ""
            listing["_city"] = city_slug

        if analyse and to_enrich:
            from apt_scrape.analysis import analyse_listings, load_preferences
            try:
                prefs = load_preferences()
            except FileNotFoundError as e:
                click.echo(f"[warn] {e} — skipping AI analysis.", err=True)
            else:
                await analyse_listings(to_enrich, prefs)

        if push_notion and deduped:
            from apt_scrape.notion_push import push_listings
            await push_listings(deduped)

        return json.dumps(
            {
                "count": len(deduped),
                "new_listings": len(to_enrich),
                "already_known": notion_known,
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
        await fetcher.close()


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
        html = await fetcher.fetch_with_retry(
            url, wait_selector=adapter.config.detail_wait_selector,
            rejection_checker=adapter.detect_rejection,
        )
        return json.dumps(
            adapter.parse_detail(html, url).to_dict(), indent=2, ensure_ascii=False
        )
    finally:
        await fetcher.close()


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
        return await fetcher.fetch_with_retry(url, wait_selector=wait_selector)
    finally:
        await fetcher.close()


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

def _find_chrome() -> str:
    """Return the path to the system Chrome binary."""
    import platform
    import shutil

    system = platform.system()
    if system == "Darwin":
        candidates = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        ]
    elif system == "Linux":
        candidates = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"]
    else:  # Windows
        candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]

    for c in candidates:
        resolved = shutil.which(c) if not os.path.isabs(c) else (c if os.path.isfile(c) else None)
        if resolved:
            return resolved
    raise FileNotFoundError("Could not find Chrome. Install Google Chrome and try again.")


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
    """Open Chrome to log into a site and save session cookies.

    Launches your real Chrome installation with a temporary profile.
    Log in normally (Google OAuth works), then press Enter in the
    terminal to capture cookies.
    """
    available_sites = list_adapters()
    if site not in available_sites:
        raise click.BadParameter(
            f"'{site}' is not a registered site. Available: {', '.join(available_sites)}",
            param_hint="--site",
        )
    asyncio.run(_run_login(site, identifier))


async def _run_login(site_id: str, identifier: str) -> None:
    """Launch real Chrome with a temp profile, let user log in, read cookies from disk.

    No automation flags, no debug ports — Chrome runs completely clean.
    After the user closes Chrome, cookies are read from Chrome's SQLite
    cookie database in the temp profile directory.
    """
    import shutil
    import sqlite3
    import subprocess
    import tempfile

    from apt_scrape.cookies import cookie_path, save_cookies

    adapter = get_adapter(site_id)
    login_url = adapter.config.login_url
    if not login_url:
        click.echo(f"Error: site '{site_id}' has no login_url configured.", err=True)
        raise SystemExit(1)

    chrome_path = _find_chrome()
    tmp_profile = tempfile.mkdtemp(prefix="apt_scrape_login_")

    click.echo(f"Opening Chrome for {adapter.config.display_name}...", err=True)
    click.echo(f"Login URL: {login_url}", err=True)

    # Write preferences to allow popups and third-party cookies
    # so Google OAuth flows work in the fresh profile.
    default_dir = os.path.join(tmp_profile, "Default")
    os.makedirs(default_dir, exist_ok=True)
    import json as _json
    prefs = {
        "profile": {
            "default_content_setting_values": {
                "popups": 1,          # 1 = allow
                "cookies": 1,         # 1 = allow all
            },
            "cookie_controls_mode": 0,  # 0 = allow all cookies
        },
    }
    with open(os.path.join(default_dir, "Preferences"), "w") as f:
        _json.dump(prefs, f)

    proc = subprocess.Popen(
        [
            chrome_path,
            f"--user-data-dir={tmp_profile}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-popup-blocking",
            login_url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    click.echo(
        "\nLog in to the site in the Chrome window.\n"
        "When you're done, CLOSE CHROME completely, then press Enter here.",
        err=True,
    )
    click.pause("")

    # Wait for Chrome to exit (user should have closed it)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        click.echo("Chrome still running — terminating...", err=True)
        proc.terminate()
        proc.wait(timeout=5)

    # Read cookies from Chrome's SQLite database
    cookie_db = os.path.join(tmp_profile, "Default", "Cookies")
    if not os.path.exists(cookie_db):
        # Some Chrome versions use "Network" subfolder
        cookie_db = os.path.join(tmp_profile, "Default", "Network", "Cookies")

    if not os.path.exists(cookie_db):
        click.echo("Error: Chrome cookie database not found in temp profile.", err=True)
        shutil.rmtree(tmp_profile, ignore_errors=True)
        raise SystemExit(1)

    conn = sqlite3.connect(cookie_db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT name, value, host_key, path, expires_utc, "
            "is_httponly, is_secure, samesite FROM cookies"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        click.echo("Warning: no cookies found. Login may have failed.", err=True)
        shutil.rmtree(tmp_profile, ignore_errors=True)
        return

    # Chrome stores expires_utc as microseconds since 1601-01-01.
    # Convert to Unix epoch seconds. 0 means session cookie → use -1.
    _CHROME_EPOCH_OFFSET = 11644473600
    samesite_map = {0: "None", 1: "Lax", 2: "Strict"}

    pw_cookies = []
    for row in rows:
        expires_utc = row["expires_utc"]
        if expires_utc and expires_utc > 0:
            expires_unix = (expires_utc / 1_000_000) - _CHROME_EPOCH_OFFSET
        else:
            expires_unix = -1

        pw_cookies.append({
            "name": row["name"],
            "value": row["value"],
            "domain": row["host_key"],
            "path": row["path"],
            "expires": expires_unix,
            "httpOnly": bool(row["is_httponly"]),
            "secure": bool(row["is_secure"]),
            "sameSite": samesite_map.get(row["samesite"], "None"),
        })

    path = cookie_path(site_id, identifier, data_dir=_DEFAULT_DATA_DIR)
    save_cookies(pw_cookies, path)
    click.echo(f"Saved {len(pw_cookies)} cookies to {path}", err=True)

    shutil.rmtree(tmp_profile, ignore_errors=True)
    click.echo("Done. Temp profile cleaned up.", err=True)


# ---------------------------------------------------------------------------
# Proxy diagnostic
# ---------------------------------------------------------------------------


@cli.command("check-proxy")
def check_proxy() -> None:
    """Test proxy connectivity and report exit IP."""
    asyncio.run(_check_proxy())


async def _check_proxy() -> None:
    from apt_scrape.proxy import create_proxy_provider

    proxy = create_proxy_provider()
    click.echo(f"Provider: {proxy.__class__.__name__}")

    proxy_url = proxy.get_proxy_url()
    if not proxy_url:
        click.echo("No proxy configured. All traffic goes direct.", err=True)
        # Show direct IP for comparison
        import httpx
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://httpbin.org/ip")
            click.echo(f"Direct IP: {r.json()['origin']}")
        return

    # Mask credentials in display
    host_port = proxy.get_proxy_host_port()
    click.echo(f"Proxy endpoint: {host_port}")

    import httpx

    # 1) Test via raw httpx (no browser) to isolate proxy from Camoufox
    click.echo("\n--- httpx through proxy (no browser) ---")
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=15) as c:
            r = await c.get("https://httpbin.org/ip")
            click.echo(f"Exit IP (httpx): {r.json()['origin']}")
    except Exception as exc:
        click.echo(f"httpx proxy test FAILED: {exc}", err=True)

    # 2) Test via actual Camoufox browser
    click.echo("\n--- Camoufox browser ---")
    from apt_scrape.browser import Fetcher
    f = Fetcher(proxy_provider=proxy, headless=True)
    try:
        await f._ensure_browser()
        page = await f._context.new_page()
        try:
            await page.goto("https://httpbin.org/ip", timeout=20000)
            body = await page.inner_text("body")
            click.echo(f"Exit IP (browser): {body.strip()}")
        finally:
            await page.close()
    finally:
        await f.close()

    # 3) Direct IP for comparison
    click.echo("\n--- Direct connection (no proxy) ---")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://httpbin.org/ip")
            click.echo(f"Direct IP: {r.json()['origin']}")
    except Exception as exc:
        click.echo(f"Direct test failed: {exc}", err=True)

    click.echo("\nIf Exit IP != Direct IP, the proxy is working.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
