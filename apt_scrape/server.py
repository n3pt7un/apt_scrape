"""apt_scrape.server — MCP server for scraping Italian real estate listings.

Thin server layer: defines MCP tools and delegates to site adapters.
Each site (Immobiliare.it, Casa.it, …) is a self-contained plugin in
``apt_scrape/sites/``.

Environment variables (all optional):
    NORDVPN_USER: NordVPN service username.
    NORDVPN_PASS: NordVPN service password.
    NORDVPN_SERVERS: Comma-separated SOCKS5 hostnames.
    PROXY_ROTATE_EVERY: Proactive rotation threshold in requests (default: 15).
"""

import asyncio
import json
import logging
import os
import re
import socket
import sys
import time
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apt_scrape.enrichment import enrich_post_dates, enrich_with_details
from apt_scrape.export import listings_to_csv, listings_to_markdown_table
from apt_scrape.sites import (
    SearchFilters,
    adapter_for_url,
    get_adapter,
    list_adapter_details,
    list_adapters,
)

# ---------------------------------------------------------------------------
# Logging (stderr only — stdout is the MCP stdio transport)
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("apt_scrape.server")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REQUEST_DELAY_SECONDS = 2.0
DEFAULT_MAX_PAGES = 1
MAX_PAGES_LIMIT = 10
DETAIL_CONCURRENCY = int(os.getenv("DETAIL_CONCURRENCY", "5"))
VPN_ROTATE_EVERY_BATCHES = int(os.getenv("VPN_ROTATE_EVERY_BATCHES", "3"))


# ---------------------------------------------------------------------------
# Proxy helpers
# ---------------------------------------------------------------------------


def _build_proxy_list() -> list[dict]:
    """Build NordVPN SOCKS5 proxy entries from environment variables.

    All three of ``NORDVPN_USER``, ``NORDVPN_PASS``, and ``NORDVPN_SERVERS``
    must be set for proxy rotation to activate.

    Returns:
        List of proxy dicts with ``server``, ``username``, and ``password``
        keys. Empty list when proxy configuration is absent.
    """
    user = os.getenv("NORDVPN_USER", "").strip()
    password = os.getenv("NORDVPN_PASS", "").strip()
    servers_raw = os.getenv("NORDVPN_SERVERS", "").strip()
    if not (user and password and servers_raw):
        return []
    servers = [s.strip() for s in servers_raw.split(",") if s.strip()]
    return [
        {"server": f"socks5://{s}:1080", "username": user, "password": password}
        for s in servers
    ]


# ---------------------------------------------------------------------------
# Browser Manager (Camoufox)
# ---------------------------------------------------------------------------


class BrowserManager:
    """Manage a Camoufox stealth browser instance for scraping.

    When ``NORDVPN_USER`` / ``NORDVPN_PASS`` / ``NORDVPN_SERVERS`` env vars
    are set, all traffic is routed through NordVPN SOCKS5 proxies and rotated
    both proactively (every ``PROXY_ROTATE_EVERY`` requests) and reactively
    (on DataDome / 403 block detection). When those vars are absent the
    browser runs without a proxy.

    Attributes:
        config: ``SiteConfig`` (inherited from constructor — not applicable
            here; attribute belongs to ``SiteAdapter``).
    """

    def __init__(self) -> None:
        self._browser = None
        self._camoufox_ctx = None
        self._last_request_time = 0.0
        self._proxy_list: list[dict] = _build_proxy_list()
        self._proxy_index: int = 0
        self._context = None
        self._requests_since_rotation: int = 0
        self._rotate_every: int = int(os.getenv("PROXY_ROTATE_EVERY", "15"))
        self._relay_proc = None
        self._relay_port: int = 0
        self._rotation_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()

        if self._proxy_list:
            logger.info(
                "Proxy rotation enabled: %d server(s), proactive every %d requests.",
                len(self._proxy_list),
                self._rotate_every,
            )
        else:
            logger.info("No proxy configured — running without proxy.")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_browser(self) -> None:
        """Start the Camoufox browser if not already running."""
        if self._browser is not None:
            if not self._browser.is_connected():
                logger.warning("Browser disconnected unexpectedly. Cleaning up...")
                await self.close()

        if self._browser is not None:
            return

        logger.info("Starting Camoufox browser...")
        from camoufox.async_api import AsyncCamoufox

        self._camoufox_ctx = AsyncCamoufox(headless=True)
        self._browser = await self._camoufox_ctx.__aenter__()
        logger.info("Camoufox browser started.")
        await self._ensure_context()

    @staticmethod
    def _free_port() -> int:
        """Return an available local TCP port."""
        with socket.socket() as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    async def _start_relay(self) -> None:
        """Start (or restart) a local unauthenticated SOCKS5 relay via pproxy.

        Playwright/Camoufox does not support SOCKS5 proxy authentication
        natively. pproxy listens on localhost without auth and forwards to the
        NordVPN endpoint with credentials transparently.
        """
        if self._relay_proc is not None:
            self._relay_proc.terminate()
            try:
                await asyncio.wait_for(self._relay_proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self._relay_proc.kill()
            self._relay_proc = None

        entry = self._proxy_list[self._proxy_index]
        host = entry["server"].replace("socks5://", "").split(":")[0]
        self._relay_port = self._free_port()
        self._relay_proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "pproxy",
            "-l",
            f"socks5://127.0.0.1:{self._relay_port}",
            "-r",
            f"socks5://{host}:1080#{entry['username']}:{entry['password']}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.8)
        logger.info(
            "SOCKS5 relay started: 127.0.0.1:%d -> %s:1080",
            self._relay_port,
            host,
        )

    async def _ensure_context(self) -> None:
        """Create (or recreate) a browser context, optionally via a local relay."""
        proxy_kwargs: dict = {}
        if self._proxy_list:
            await self._start_relay()
            proxy_kwargs["proxy"] = {
                "server": f"socks5://127.0.0.1:{self._relay_port}"
            }
        self._context = await self._browser.new_context(**proxy_kwargs)

    @staticmethod
    def _detect_block(html: str) -> bool:
        """Return ``True`` if the page looks like a bot-challenge or block page.

        Args:
            html: Raw HTML string to inspect.

        Returns:
            ``True`` when DataDome, an access-denied title, or an abnormally
            short HTML response is detected.
        """
        if "captcha-delivery.com" in html:
            return True
        title_match = re.search(
            r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL
        )
        if title_match:
            title = title_match.group(1).lower()
            if any(
                w in title
                for w in ("access denied", "robot check", "captcha", "blocked", "just a moment", "403")
            ):
                return True
        if len(html) < 2000 and "<html" in html.lower():
            return True
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def rotate_proxy(self) -> None:
        """Close the current context and reopen it with the next proxy.

        Thread-safe via ``_rotation_lock`` — if a rotation is already in
        progress (e.g. two parallel slots both detected a block), the second
        caller returns immediately instead of rotating twice.

        Pauses for 60 seconds when the full proxy list has been cycled through.
        """
        if not self._proxy_list:
            return
        if self._rotation_lock.locked():
            # Another coroutine is already rotating; wait for it to finish.
            async with self._rotation_lock:
                return
        async with self._rotation_lock:
            if self._context:
                try:
                    await self._context.close()
                except Exception as exc:
                    logger.debug("Error closing context during rotation: %s", exc)
                self._context = None
            self._proxy_index = (self._proxy_index + 1) % len(self._proxy_list)
            if self._proxy_index == 0:
                logger.warning(
                    "All proxies cycled — pausing 60 s before restarting rotation."
                )
                await asyncio.sleep(60)
            self._requests_since_rotation = 0
            await self._ensure_context()
            logger.info(
                "Rotated to proxy: %s", self._proxy_list[self._proxy_index]["server"]
            )

    async def _rate_limit(self) -> None:
        """Enforce the minimum delay between consecutive requests."""
        async with self._rate_limit_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < REQUEST_DELAY_SECONDS:
                await asyncio.sleep(REQUEST_DELAY_SECONDS - elapsed)
            self._last_request_time = time.monotonic()

    async def fetch_page(
        self,
        url: str,
        wait_selector: str | None = None,
        wait_until: str = "domcontentloaded",
    ) -> str:
        """Fetch *url* via the stealth browser and return raw HTML.

        Handles proactive proxy rotation (every N requests) and reactive
        rotation (on block detection).

        Args:
            url: Page URL to fetch.
            wait_selector: Optional CSS selector to wait for after page load.
            wait_until: Playwright navigation wait event — ``"domcontentloaded"``
                (default, fast), ``"load"``, or ``"networkidle"`` (waits for JS
                hydration to complete; use for sites with client-decoded content).

        Returns:
            Raw HTML string of the rendered page.

        Raises:
            RuntimeError: When the page is blocked even after proxy rotation.
        """
        await self._ensure_browser()
        await self._rate_limit()

        if self._proxy_list and self._requests_since_rotation >= self._rotate_every:
            logger.info(
                "Proactive proxy rotation after %d requests.",
                self._requests_since_rotation,
            )
            await self.rotate_proxy()

        try:
            html = await self._fetch_once(url, wait_selector, wait_until)
        except Exception as exc:
            err_str = str(exc).lower()
            if "targetclosederror" in str(type(exc)).lower() or "closed=true" in err_str or "handler is closed" in err_str:
                logger.warning("Browser connection lost on %s: %s. Reconnecting...", url, exc)
                await self.close()
                await self._ensure_browser()
                html = await self._fetch_once(url, wait_selector, wait_until)
            elif not self._proxy_list:
                raise
            else:
                logger.warning("Fetch error on %s (%s) — rotating proxy and retrying.", url, exc)
                html = None

        if self._proxy_list and (html is None or self._detect_block(html)):
            # Cycle through ALL remaining proxies before giving up
            for attempt in range(len(self._proxy_list)):
                logger.warning(
                    "Block/timeout on %s — rotating proxy (attempt %d/%d).",
                    url, attempt + 1, len(self._proxy_list),
                )
                await self.rotate_proxy()
                await asyncio.sleep(3)
                try:
                    html = await self._fetch_once(url, wait_selector, wait_until)
                except Exception as exc:
                    logger.warning("Fetch error after rotation (attempt %d): %s", attempt + 1, exc)
                    html = None
                    continue
                if not self._detect_block(html):
                    break
            else:
                logger.error("All proxies failed on %s.", url)
                raise RuntimeError(f"Blocked on {url} even after proxy rotation.")

        self._requests_since_rotation += 1
        return html

    async def fetch_page_parallel(
        self,
        url: str,
        wait_selector: str | None = None,
        stagger_secs: float = 0.0,
        wait_until: str = "domcontentloaded",
    ) -> str:
        """Fetch *url* without the per-request rate limiter, suitable for use
        inside ``asyncio.gather`` batches.

        Stagger is applied via an up-front sleep so that slots within the same
        batch are spread out slightly.  Reactive block-detection and proxy
        rotation are retained; proactive per-request rotation is skipped
        because batch-level rotation in ``enrichment`` handles it instead.

        Args:
            url: Page URL to fetch.
            wait_selector: Optional CSS selector to wait for after page load.
            stagger_secs: Seconds to sleep before starting the fetch.  Pass
                ``slot_index * STAGGER_SECONDS`` so each slot in a batch
                starts slightly after the previous one.
            wait_until: Playwright navigation wait event (default
                ``"domcontentloaded"``).  Pass ``"networkidle"`` for sites that
                require JS hydration before content is readable.

        Returns:
            Raw HTML string of the rendered page.

        Raises:
            RuntimeError: When the page is blocked even after proxy rotation.
        """
        if stagger_secs > 0:
            await asyncio.sleep(stagger_secs)
        await self._ensure_browser()

        try:
            html = await self._fetch_once(url, wait_selector, wait_until)
        except Exception as exc:
            err_str = str(exc).lower()
            if "targetclosederror" in str(type(exc)).lower() or "closed=true" in err_str or "handler is closed" in err_str:
                logger.warning("Browser connection lost on %s: %s. Reconnecting...", url, exc)
                await self.close()
                await self._ensure_browser()
                html = await self._fetch_once(url, wait_selector, wait_until)
            elif not self._proxy_list:
                raise
            else:
                logger.warning("Fetch error on %s (%s) — rotating proxy and retrying.", url, exc)
                html = None

        if self._proxy_list and (html is None or self._detect_block(html)):
            for attempt in range(len(self._proxy_list)):
                logger.warning(
                    "Block/timeout on %s (parallel) — rotating proxy (attempt %d/%d).",
                    url, attempt + 1, len(self._proxy_list),
                )
                await self.rotate_proxy()
                await asyncio.sleep(3)
                try:
                    html = await self._fetch_once(url, wait_selector, wait_until)
                except Exception as exc:
                    logger.warning("Fetch error after rotation (attempt %d): %s", attempt + 1, exc)
                    html = None
                    continue
                if not self._detect_block(html):
                    break
            else:
                logger.error("All proxies failed on %s.", url)
                raise RuntimeError(f"Blocked on {url} even after proxy rotation.")

        self._requests_since_rotation += 1
        return html

    async def _fetch_once(
        self,
        url: str,
        wait_selector: str | None,
        wait_until: str = "domcontentloaded",
    ) -> str:
        """Open *url* in a new page and return its rendered HTML.

        Args:
            url: URL to navigate to.
            wait_selector: CSS selector to wait for before capturing content.
            wait_until: Playwright ``page.goto`` wait event.  Use
                ``"networkidle"`` for JS-hydrated pages (e.g. Casa.it).

        Returns:
            Raw HTML string.

        Raises:
            Exception: Propagates any Playwright navigation error.
        """
        page = await self._context.new_page()
        try:
            logger.info("Fetching: %s", url)
            # networkidle can take noticeably longer on JS-heavy pages; allow 45 s.
            goto_timeout = 45000 if wait_until == "networkidle" else 30000
            await page.goto(url, wait_until=wait_until, timeout=goto_timeout)

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=15000)
                except Exception as exc:
                    logger.warning(
                        "Selector '%s' not found, using page as-is: %s",
                        wait_selector,
                        exc,
                    )
                    # Diagnostic: log page title and first 800 chars of HTML
                    try:
                        page_title = await page.title()
                        html_snippet = await page.evaluate("document.documentElement.outerHTML.slice(0, 800)")
                        logger.warning("DIAG page title: %r", page_title)
                        logger.warning("DIAG html snippet: %s", html_snippet)
                    except Exception as diag_exc:
                        logger.warning("DIAG failed to capture snippet: %s", diag_exc)

            await asyncio.sleep(1.5)
            return await page.content()
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)
            raise
        finally:
            await page.close()

    async def close(self) -> None:
        """Shut down the relay process, browser context, and browser."""
        if self._relay_proc is not None:
            self._relay_proc.terminate()
            try:
                await asyncio.wait_for(self._relay_proc.wait(), timeout=3)
            except asyncio.TimeoutError:
                self._relay_proc.kill()
            self._relay_proc = None
        if self._context:
            try:
                await self._context.close()
            except Exception as exc:
                logger.debug("Error closing browser context: %s", exc)
            self._context = None
        if self._browser and self._camoufox_ctx:
            try:
                await self._camoufox_ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("Error closing Camoufox: %s", exc)
            self._browser = None
            logger.info("Browser closed.")


# Module-level singleton used by both ``apt_scrape.cli`` and the MCP tools.
browser = BrowserManager()


# ---------------------------------------------------------------------------
# Tool input models
# ---------------------------------------------------------------------------

_site_ids = list_adapters()


class SearchListingsInput(BaseModel):
    """Validated input for the ``rental_search_listings`` MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    city: str = Field(
        ...,
        description="City slug (e.g. 'milano', 'bologna', 'roma', 'torino')",
        min_length=1,
        max_length=100,
    )
    area: str | None = Field(
        default=None,
        description="Optional area slug inside city (e.g. 'precotto', 'turro')",
        min_length=1,
        max_length=100,
    )
    operation: str = Field(
        default="affitto",
        description="Contract type: 'affitto' (rent) or 'vendita' (sale)",
    )
    property_type: str = Field(
        default="case",
        description=(
            "Property category: case, appartamenti, attici, "
            "case-indipendenti, loft, rustici, ville, villette"
        ),
    )
    min_price: int | None = Field(default=None, description="Minimum price in EUR", ge=0)
    max_price: int | None = Field(default=None, description="Maximum price in EUR", ge=0)
    min_sqm: int | None = Field(
        default=None, description="Minimum surface in square meters", ge=0
    )
    max_sqm: int | None = Field(
        default=None, description="Maximum surface in square meters", ge=0
    )
    min_rooms: int | None = Field(
        default=None, description="Minimum number of rooms (locali)", ge=1, le=10
    )
    max_rooms: int | None = Field(
        default=None, description="Maximum number of rooms (locali)", ge=1, le=10
    )
    published_within: str | None = Field(
        default=None,
        description="Recency filter in days: '1' (today), '3', '7', '14', '30'",
        pattern=r"^(1|3|7|14|30)$",
    )
    sort: str = Field(
        default="rilevanza",
        description="Sort order (e.g. 'rilevanza', 'piu-recenti')",
    )
    source: str = Field(
        default=_site_ids[0] if _site_ids else "immobiliare",
        description=f"Site to scrape: {', '.join(_site_ids)}",
    )
    max_pages: int = Field(
        default=DEFAULT_MAX_PAGES,
        description="Number of result pages to scrape (1-10)",
        ge=1,
        le=MAX_PAGES_LIMIT,
    )
    start_page: int = Field(
        default=1,
        description="First result page to scrape (1-based)",
        ge=1,
        le=MAX_PAGES_LIMIT,
    )
    end_page: int | None = Field(
        default=None,
        description=(
            "Last result page to scrape (inclusive, 1-10). "
            "If provided, it overrides max_pages."
        ),
        ge=1,
        le=MAX_PAGES_LIMIT,
    )
    include_details: bool = Field(
        default=False,
        description=(
            "If true, fetch each listing URL and enrich output with full detail "
            "fields (description, features, costs, etc.)"
        ),
    )
    detail_limit: int | None = Field(
        default=None,
        description=(
            "Maximum number of listing detail pages to fetch when "
            "include_details=true. Default: all listings."
        ),
        ge=1,
    )
    include_csv: bool = Field(
        default=False,
        description="If true, include CSV export in response under 'csv'",
    )
    include_table: bool = Field(
        default=False,
        description="If true, include markdown table export in response under 'table'",
    )
    table_max_rows: int = Field(
        default=20,
        description="Maximum number of rows in markdown table preview",
        ge=1,
        le=200,
    )
    detail_concurrency: int = Field(
        default=DETAIL_CONCURRENCY,
        description="Parallel detail page fetches per batch (default: DETAIL_CONCURRENCY env var or 5)",
        ge=1,
        le=20,
    )
    vpn_rotate_batches: int = Field(
        default=VPN_ROTATE_EVERY_BATCHES,
        description="Rotate VPN every N batches of detail fetches (default: VPN_ROTATE_EVERY_BATCHES env var or 3)",
        ge=1,
    )

    @field_validator("city")
    @classmethod
    def normalize_city(cls, v: str) -> str:
        """Normalize city to a lowercase hyphenated slug."""
        return v.lower().strip().replace(" ", "-")

    @field_validator("area")
    @classmethod
    def normalize_area(cls, v: str | None) -> str | None:
        """Normalize area to a lowercase hyphenated slug."""
        if v is None:
            return None
        return v.lower().strip().replace(" ", "-")

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        """Verify that *source* is a registered adapter ID."""
        available = list_adapters()
        if v not in available:
            raise ValueError(
                f"Unknown source '{v}'. Available: {', '.join(available)}"
            )
        return v


class GetListingDetailInput(BaseModel):
    """Validated input for the ``rental_get_listing_detail`` MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(
        ...,
        description="Full URL of the listing page (from search results)",
        min_length=10,
    )

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Require *url* to start with ``http``."""
        if not v.startswith("http"):
            raise ValueError("URL must start with http:// or https://")
        return v


class DumpPageInput(BaseModel):
    """Validated input for the ``rental_dump_page`` MCP tool."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    url: str = Field(..., description="URL to fetch and dump", min_length=10)
    wait_selector: str | None = Field(
        default=None,
        description="CSS selector to wait for before capturing HTML",
    )


# ---------------------------------------------------------------------------
# MCP Server & Tools
# ---------------------------------------------------------------------------

mcp = FastMCP("rental_scraper_mcp")


@mcp.tool(
    name="rental_search_listings",
    annotations={
        "title": "Search Real Estate Listings",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def search_listings(params: SearchListingsInput) -> str:
    """Search for rental or sale property listings.

    Builds a search URL from *params*, fetches result pages via a stealth
    browser (Camoufox), and parses listing cards into structured JSON.

    Args:
        params: Validated search parameters.

    Returns:
        JSON string with ``count``, ``source``, ``search_url``, and
        ``listings`` array. Each listing contains title, price, sqm, rooms,
        bathrooms, address, url, thumbnail, description_snippet,
        raw_features, and source.
    """
    adapter = get_adapter(params.source)
    all_listings: list[dict[str, Any]] = []
    pages_scraped = 0

    if params.end_page is not None:
        start_page = params.start_page
        end_page = params.end_page
    else:
        start_page = params.start_page
        end_page = params.start_page + params.max_pages - 1

    if end_page > MAX_PAGES_LIMIT:
        return _json(
            {
                "error": (
                    f"Requested end_page={end_page} exceeds "
                    f"MAX_PAGES_LIMIT={MAX_PAGES_LIMIT}"
                )
            }
        )

    if end_page < start_page:
        return _json(
            {
                "error": "Invalid page range: end_page must be >= start_page",
                "start_page": start_page,
                "end_page": end_page,
            }
        )

    for page_num in range(start_page, end_page + 1):
        filters = SearchFilters(
            city=params.city,
            area=params.area,
            operation=params.operation,
            property_type=params.property_type,
            min_price=params.min_price,
            max_price=params.max_price,
            min_sqm=params.min_sqm,
            max_sqm=params.max_sqm,
            min_rooms=params.min_rooms,
            max_rooms=params.max_rooms,
            published_within=params.published_within,
            sort=params.sort,
            page=page_num,
        )
        url = adapter.build_search_url(filters)

        try:
            html = await browser.fetch_page(
                url, wait_selector=adapter.config.search_wait_selector
            )
        except Exception as exc:
            return _json({"error": f"Failed to fetch page {page_num}: {exc}", "url": url})

        page_listings = adapter.parse_search(html)
        pages_scraped = page_num

        if not page_listings:
            logger.info("No more listings on page %d, stopping.", page_num)
            break

        all_listings.extend([ls.to_dict() for ls in page_listings])
        logger.info("Page %d: %d listings", page_num, len(page_listings))

    ref = SearchFilters(
        city=params.city,
        area=params.area,
        operation=params.operation,
        property_type=params.property_type,
        min_price=params.min_price,
        max_price=params.max_price,
        min_sqm=params.min_sqm,
        max_sqm=params.max_sqm,
        min_rooms=params.min_rooms,
        max_rooms=params.max_rooms,
        published_within=params.published_within,
        sort=params.sort,
        page=start_page,
    )

    detail_enriched = 0
    detail_errors: list[dict[str, str]] = []
    post_date_enriched = 0
    post_date_errors: list[dict[str, str]] = []

    if params.include_details and all_listings:
        detail_enriched, detail_errors = await enrich_with_details(
            all_listings, browser, adapter, params.detail_limit,
            concurrency=params.detail_concurrency,
            rotate_every_batches=params.vpn_rotate_batches,
        )

    post_date_enriched, post_date_errors = await enrich_post_dates(
        all_listings, browser, adapter,
        concurrency=params.detail_concurrency,
        rotate_every_batches=params.vpn_rotate_batches,
    )

    return _json(
        {
            "count": len(all_listings),
            "source": adapter.config.display_name,
            "search_url": adapter.build_search_url(ref),
            "city": params.city,
            "area": params.area,
            "pages_scraped": pages_scraped,
            "start_page": start_page,
            "end_page": end_page,
            "details_requested": params.include_details,
            "details_enriched": detail_enriched,
            "detail_errors": detail_errors,
            "post_date_enriched": post_date_enriched,
            "post_date_errors": post_date_errors,
            "csv": listings_to_csv(all_listings) if params.include_csv else "",
            "table": listings_to_markdown_table(all_listings, params.table_max_rows)
            if params.include_table
            else "",
            "listings": all_listings,
        }
    )


@mcp.tool(
    name="rental_get_listing_detail",
    annotations={
        "title": "Get Full Listing Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_listing_detail(params: GetListingDetailInput) -> str:
    """Fetch full details of a single property listing.

    Auto-detects the site from the URL and uses the matching adapter to
    extract title, price, full description, features, photos, energy class,
    agency info, costs, and address.

    Args:
        params: Input containing the listing ``url``.

    Returns:
        JSON string of the ``ListingDetail`` dict.
    """
    url = params.url
    adapter = adapter_for_url(url)

    if adapter is None:
        available = list_adapter_details()
        return _json(
            {"error": f"No adapter found for URL: {url}", "supported_sites": available}
        )

    try:
        html = await browser.fetch_page(
            url, wait_selector=adapter.config.detail_wait_selector
        )
    except Exception as exc:
        return _json({"error": f"Failed to fetch listing: {exc}", "url": url})

    detail = adapter.parse_detail(html, url)
    return _json(detail.to_dict())


@mcp.tool(
    name="rental_list_sites",
    annotations={
        "title": "List Supported Real Estate Sites",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def list_sites() -> str:
    """List all registered real estate site adapters.

    Returns:
        JSON array of ``{site_id, display_name, base_url}`` objects.
    """
    return _json(list_adapter_details())


@mcp.tool(
    name="rental_dump_page",
    annotations={
        "title": "Dump Raw HTML of a Page (Debug)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def dump_page(params: DumpPageInput) -> str:
    """Fetch a page and return raw HTML for debugging selectors.

    Captures HTML after JavaScript rendering via Camoufox.

    Args:
        params: Input with ``url`` and optional ``wait_selector``.

    Returns:
        Raw HTML string (not JSON).
    """
    try:
        return await browser.fetch_page(params.url, wait_selector=params.wait_selector)
    except Exception as exc:
        return _json({"error": str(exc), "url": params.url})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json(obj: Any) -> str:
    """Serialize *obj* to a compact, human-readable JSON string."""
    return json.dumps(obj, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sites = list_adapter_details()
    logger.info(
        "Starting rental_scraper_mcp with %d site(s): %s",
        len(sites),
        ", ".join(s["display_name"] for s in sites),
    )
    mcp.run()
