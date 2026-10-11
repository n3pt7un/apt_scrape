"""apt_scrape.server — MCP server for scraping Italian real estate listings.

Thin server layer: defines MCP tools and delegates to site adapters.
Each site (Immobiliare.it, Casa.it, …) is a self-contained plugin in
``apt_scrape/sites/``.

Block detection runs on every fetch, with or without proxies: a bot-challenge
page raises ``BlockedError`` (after rotating through the proxies, when set).

Environment variables (all optional):
    NORDVPN_USER: NordVPN service username.
    NORDVPN_PASS: NordVPN service password.
    NORDVPN_SERVERS: Comma-separated SOCKS5 hostnames.
    PROXY_ROTATE_EVERY: Proactive rotation threshold in requests (default: 15).
    DETAIL_CONCURRENCY: Parallel detail fetches per batch for CLI/MCP (default: 5).
    VPN_ROTATE_EVERY_BATCHES: Rotate the proxy every N detail batches for CLI/MCP (default: 3).
    BROWSER_HEADLESS: Set to false to show the Camoufox window (default: true).
    BLOCK_ASSETS: Set to 1/true to skip image downloads (default: off; some
        anti-bot systems score clients that never load images).
"""

import asyncio
import json
import logging
import os
import random
import re
import socket
import sys
import time
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

from apt_scrape.enrichment import detail_page_budget, enrich_post_dates, enrich_with_details
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
# Backoff range (seconds) before the single retry of a transient navigation error.
TRANSIENT_RETRY_DELAY = (3.0, 6.0)
# DataDome's JS interstitial can clear itself; re-check a challenge page once after this.
CHALLENGE_RECHECK_SECONDS = 2.0


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BlockedError(RuntimeError):
    """The portal served a bot-challenge or block page instead of content.

    Subclasses ``RuntimeError`` so existing ``except Exception`` handlers still
    catch it.

    Attributes:
        url: The URL that was blocked.
        html: The block page HTML, kept for debugging tools.
    """

    def __init__(self, url: str, reason: str = "", html: str = "") -> None:
        self.url = url
        self.html = html
        msg = f"Blocked by bot protection on {url}"
        super().__init__(f"{msg} ({reason})" if reason else msg)


class FetchAborted(Exception):
    """A queued ``fetch_page_parallel`` call was called off before navigating.

    Raised when its ``should_abort`` check returns ``True`` after the stagger
    and rate-limit wait (e.g. the enrichment block breaker tripped meanwhile).
    No request was made.

    Attributes:
        url: The URL that was not fetched.
    """

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"Fetch of {url} called off before navigating")


def _is_connection_lost(exc: BaseException) -> bool:
    """Return ``True`` when *exc* means the browser connection itself died."""
    err_str = str(exc).lower()
    return (
        "targetclosederror" in str(type(exc)).lower()
        or "closed=true" in err_str
        or "handler is closed" in err_str
    )


def _is_transient_error(exc: BaseException) -> bool:
    """Return ``True`` for navigation timeouts and network errors worth one retry.

    Camoufox is Firefox, so network failures surface as ``NS_ERROR_*``;
    ``net::ERR_*`` covers Chromium-style messages.
    """
    if isinstance(exc, BlockedError):
        return False
    msg = str(exc)
    return (
        type(exc).__name__ == "TimeoutError"
        or "Timeout" in msg
        or "net::ERR_" in msg
        or "NS_ERROR_" in msg
    )


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
        # Earliest monotonic time the next request may start (shared rate limiter).
        self._next_request_time = 0.0
        self._proxy_list: list[dict] = _build_proxy_list()
        self._proxy_index: int = 0
        self._context = None
        self._requests_since_rotation: int = 0
        self._rotate_every: int = int(os.getenv("PROXY_ROTATE_EVERY", "15"))
        self._relay_proc = None
        self._relay_port: int = 0
        self._rotation_lock = asyncio.Lock()
        self._rate_limit_lock = asyncio.Lock()
        self._browser_lock = asyncio.Lock()

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

    async def _ensure_browser_unlocked(self) -> None:
        """Start the Camoufox browser if not already running. Caller must hold ``_browser_lock``."""
        if self._browser is not None:
            if not self._browser.is_connected():
                logger.warning("Browser disconnected unexpectedly. Cleaning up...")
                await self._close_unlocked()

        if self._browser is not None:
            return

        logger.info("Starting Camoufox browser...")
        from camoufox.async_api import AsyncCamoufox

        headless = os.getenv("BROWSER_HEADLESS", "true").lower() not in ("0", "false", "no")
        logger.info("Camoufox headless=%s (set BROWSER_HEADLESS=false to show window)", headless)
        # Only the HTML is parsed (photo URLs come from <img src>), so image bytes
        # are optional. Opt-in because a client that never loads images can look
        # more bot-like to DataDome.
        block_images = os.getenv("BLOCK_ASSETS", "").lower() in ("1", "true", "yes")
        if block_images:
            logger.info("BLOCK_ASSETS on — image downloads disabled.")
        self._camoufox_ctx = AsyncCamoufox(headless=headless, block_images=block_images)
        self._browser = await self._camoufox_ctx.__aenter__()
        logger.info("Camoufox browser started.")
        await self._ensure_context()

    async def _ensure_browser(self) -> None:
        """Start the Camoufox browser if not already running."""
        async with self._browser_lock:
            await self._ensure_browser_unlocked()

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
        """Create (or recreate) a browser context, optionally via a local relay.

        We explicitly advertise only ``gzip`` and ``deflate`` in
        ``Accept-Encoding`` — Brotli (``br``) is omitted intentionally.
        Some sites (e.g. Casa.it) serve Brotli-compressed responses that
        Camoufox/Firefox fails to decompress correctly in headless/automated
        mode, resulting in garbled binary content being rendered.  Dropping
        ``br`` from the accept list causes the server to fall back to gzip,
        which Firefox decodes without issue.
        """
        proxy_kwargs: dict = {}
        if self._proxy_list:
            await self._start_relay()
            proxy_kwargs["proxy"] = {
                "server": f"socks5://127.0.0.1:{self._relay_port}"
            }
        self._context = await self._browser.new_context(**proxy_kwargs)
        # Disable Brotli to avoid garbled-content issues with certain sites.
        await self._context.set_extra_http_headers(
            {"Accept-Encoding": "gzip, deflate"}
        )

    # Exact (lowercased, whitespace-collapsed) titles of known block/challenge pages.
    # Matching whole titles, never substrings: listing titles carry street numbers
    # such as "via Emilia Levante 403".
    _BLOCK_TITLES = frozenset({
        "403", "403 forbidden", "403 - forbidden", "error 403", "http 403", "forbidden",
        "access denied", "just a moment...", "just a moment", "attention required! | cloudflare",
        "robot check", "are you a robot?", "pardon our interruption",
    })

    @staticmethod
    def _detect_block(html: str, check_length: bool = True) -> bool:
        """Return ``True`` if the page looks like a bot-challenge or block page.

        Signals, strongest first:

        - DataDome: ``captcha-delivery.com`` together with its ``var dd={``
          bootstrap, a captcha ``<iframe>``, or a page too small to be a real
          listing page (a full page that merely references the domain passes).
        - Cloudflare's challenge platform on a small page.
        - A ``<title>`` that is exactly a known block title.
        - An abnormally short HTML document (only when *check_length*; skip it
          for pages checked right after navigation, before an SPA hydrates).

        Args:
            html: Raw HTML string to inspect.
            check_length: Whether to treat a tiny document as a block page.

        Returns:
            ``True`` when the HTML is a block or challenge page.
        """
        if not html:
            return False
        lower = html.lower()
        if "captcha-delivery.com" in lower and (
            re.search(r"var\s+dd\s*=\s*\{", html)
            or re.search(r"<iframe[^>]+src=[\"'][^\"']*captcha-delivery\.com", lower)
            or len(html) < 50_000
        ):
            return True
        if "/cdn-cgi/challenge-platform" in lower and len(html) < 50_000:
            return True
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = re.sub(r"\s+", " ", title_match.group(1)).strip().lower()
            if title in BrowserManager._BLOCK_TITLES:
                return True
        if check_length and len(html) < 2000 and "<html" in lower:
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

    async def _rate_limit(self, min_interval: float | None = None) -> None:
        """Space request starts at least *min_interval* seconds apart.

        Shared by ``fetch_page`` and ``fetch_page_parallel``. The lock is held
        only to reserve the next start slot, so parallel callers wait their
        turn without serialising the page loads themselves.

        Args:
            min_interval: Seconds between consecutive request starts. ``None``
                uses ``REQUEST_DELAY_SECONDS``.
        """
        interval = REQUEST_DELAY_SECONDS if min_interval is None else max(0.0, min_interval)
        async with self._rate_limit_lock:
            now = time.monotonic()
            start = max(now, self._next_request_time)
            self._next_request_time = start + interval
        delay = start - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)

    async def fetch_page(
        self,
        url: str,
        wait_selector: str | None = None,
        wait_until: str = "domcontentloaded",
        wait_selector_timeout: int = 15000,
        *,
        min_interval: float | None = None,
        raise_on_block: bool = True,
    ) -> str:
        """Fetch *url* via the stealth browser and return raw HTML.

        Handles proactive proxy rotation (every N requests), block detection
        (always, with or without proxies), reactive rotation on blocks, and one
        retry of transient navigation errors.

        Args:
            url: Page URL to fetch.
            wait_selector: Optional CSS selector to wait for after page load.
            wait_until: Playwright navigation wait event — ``"domcontentloaded"``
                (default, fast), ``"load"``, or ``"networkidle"`` (waits for JS
                hydration to complete; use for sites with client-decoded content).
            wait_selector_timeout: Milliseconds to wait for *wait_selector*.
            min_interval: Minimum seconds between request starts (default
                ``REQUEST_DELAY_SECONDS``).
            raise_on_block: When ``False`` (debug dumps), return the block
                page HTML instead of raising.

        Returns:
            Raw HTML string of the rendered page.

        Raises:
            BlockedError: When the page is a block page and no proxy (or no
                remaining proxy) gets past it.
        """
        await self._ensure_browser()
        await self._rate_limit(min_interval)

        if self._proxy_list and self._requests_since_rotation >= self._rotate_every:
            logger.info(
                "Proactive proxy rotation after %d requests.",
                self._requests_since_rotation,
            )
            await self.rotate_proxy()

        try:
            html = await self._fetch_resilient(url, wait_selector, wait_until, wait_selector_timeout)
        except BlockedError as exc:
            if raise_on_block:
                raise
            logger.warning("Returning block page for %s as requested.", url)
            html = exc.html
        self._requests_since_rotation += 1
        return html

    async def fetch_page_parallel(
        self,
        url: str,
        wait_selector: str | None = None,
        stagger_secs: float = 0.0,
        wait_until: str = "domcontentloaded",
        wait_selector_timeout: int = 15000,
        *,
        min_interval: float | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> str:
        """Fetch *url* for use inside ``asyncio.gather`` batches.

        Stagger is applied via an up-front sleep so that slots within the same
        batch are spread out slightly; the shared rate limiter then spaces the
        actual request starts. Block detection, reactive proxy rotation and
        the transient-error retry are the same as ``fetch_page``; proactive
        per-request rotation is skipped because batch-level rotation in
        ``enrichment`` handles it instead.

        Args:
            url: Page URL to fetch.
            wait_selector: Optional CSS selector to wait for after page load.
            stagger_secs: Seconds to sleep before starting the fetch.  Pass
                ``slot_index * STAGGER_SECONDS`` so each slot in a batch
                starts slightly after the previous one.
            wait_until: Playwright navigation wait event (default
                ``"domcontentloaded"``).  Pass ``"networkidle"`` for sites that
                require JS hydration before content is readable.
            wait_selector_timeout: Milliseconds to wait for *wait_selector*.
            min_interval: Minimum seconds between request starts (default
                ``REQUEST_DELAY_SECONDS``).
            should_abort: Checked once the slot's turn comes (after the stagger
                and the rate-limit wait), right before navigating: ``True``
                calls the fetch off. Slots of one batch start together, so a
                check made before the call cannot see what the earlier slots
                ran into while this one waited.

        Returns:
            Raw HTML string of the rendered page.

        Raises:
            BlockedError: When the page is a block page and no proxy (or no
                remaining proxy) gets past it.
            FetchAborted: When *should_abort* returned ``True``; nothing was fetched.
        """
        if stagger_secs > 0:
            await asyncio.sleep(stagger_secs)
        await self._ensure_browser()
        await self._rate_limit(min_interval)
        if should_abort is not None and should_abort():
            raise FetchAborted(url)

        html = await self._fetch_resilient(url, wait_selector, wait_until, wait_selector_timeout)
        self._requests_since_rotation += 1
        return html

    async def _fetch_reconnecting(
        self,
        url: str,
        wait_selector: str | None,
        wait_until: str,
        wait_selector_timeout: int,
    ) -> str:
        """Run ``_fetch_once``, restarting the browser once if its connection died."""
        try:
            return await self._fetch_once(url, wait_selector, wait_until, wait_selector_timeout)
        except Exception as exc:
            if not _is_connection_lost(exc):
                raise
            logger.warning("Browser connection lost on %s: %s. Reconnecting...", url, exc)
            async with self._browser_lock:
                # Re-check after acquiring lock — another coroutine may have
                # already reconnected while we were waiting.
                if self._browser is None or not self._browser.is_connected():
                    await self._close_unlocked()
                    await self._ensure_browser_unlocked()
            return await self._fetch_once(url, wait_selector, wait_until, wait_selector_timeout)

    async def _fetch_resilient(
        self,
        url: str,
        wait_selector: str | None,
        wait_until: str,
        wait_selector_timeout: int,
    ) -> str:
        """Fetch *url* with block detection, proxy rotation and transient retry.

        - Without proxies: a block page raises ``BlockedError`` at once (the
          same IP rarely gets through seconds later); a transient navigation
          error (timeout, ``NS_ERROR_*``/``net::ERR_*``) is retried once after
          a short backoff, then propagates.
        - With proxies: any block or error rotates through every proxy, as
          before; when they are all exhausted it raises ``BlockedError`` if a
          block was seen, otherwise the last navigation error.
        """
        args = (url, wait_selector, wait_until, wait_selector_timeout)
        blocked: BlockedError | None = None
        last_exc: Exception | None = None
        try:
            return await self._fetch_reconnecting(*args)
        except BlockedError as exc:
            if not self._proxy_list:
                raise
            logger.warning("Block page on %s — rotating proxy and retrying.", url)
            blocked = exc
        except Exception as exc:
            if not self._proxy_list:
                if not _is_transient_error(exc):
                    raise
                logger.warning("Transient error on %s (%s) — retrying once.", url, exc)
                await asyncio.sleep(random.uniform(*TRANSIENT_RETRY_DELAY))
                return await self._fetch_reconnecting(*args)
            logger.warning("Fetch error on %s (%s) — rotating proxy and retrying.", url, exc)
            last_exc = exc

        # Proxy path: cycle through ALL remaining proxies before giving up.
        for attempt in range(len(self._proxy_list)):
            logger.warning(
                "Block/timeout on %s — rotating proxy (attempt %d/%d).",
                url, attempt + 1, len(self._proxy_list),
            )
            await self.rotate_proxy()
            await asyncio.sleep(3)
            try:
                return await self._fetch_reconnecting(*args)
            except BlockedError as exc:
                blocked = exc
            except Exception as exc:
                logger.warning("Fetch error after rotation (attempt %d): %s", attempt + 1, exc)
                last_exc = exc
        logger.error("All proxies failed on %s.", url)
        if blocked is not None:
            raise BlockedError(url, "still blocked after rotating every proxy", blocked.html)
        assert last_exc is not None
        raise last_exc

    async def _fetch_once(
        self,
        url: str,
        wait_selector: str | None,
        wait_until: str = "domcontentloaded",
        wait_selector_timeout: int = 15000,
    ) -> str:
        """Open *url* in a new page and return its rendered HTML.

        Checks for a bot-challenge page right after navigation, so a blocked
        page fails in about two seconds instead of burning the selector
        timeout.

        Args:
            url: URL to navigate to.
            wait_selector: CSS selector to wait for before capturing content.
            wait_until: Playwright ``page.goto`` wait event.  Use
                ``"networkidle"`` for JS-hydrated pages (e.g. Casa.it).
            wait_selector_timeout: Milliseconds to wait for *wait_selector*.

        Returns:
            Raw HTML string.

        Raises:
            BlockedError: When the page is a block or challenge page.
            Exception: Propagates any Playwright navigation error.
        """
        page = await self._context.new_page()
        try:
            logger.info("Fetching: %s", url)
            # networkidle can take noticeably longer on JS-heavy pages; allow 45 s.
            goto_timeout = 45000 if wait_until == "networkidle" else 30000
            await page.goto(url, wait_until=wait_until, timeout=goto_timeout)

            # Fail fast on a challenge page. No length check yet: an SPA shell
            # can be tiny before it hydrates.
            if self._detect_block(await self._content_or_empty(page), check_length=False):
                await asyncio.sleep(CHALLENGE_RECHECK_SECONDS)
                html = await self._content_or_empty(page)
                if self._detect_block(html, check_length=False):
                    logger.warning("Bot challenge on %s — giving up on this page.", url)
                    raise BlockedError(url, html=html)

            if wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=wait_selector_timeout)
                except Exception as exc:
                    html = await self._content_or_empty(page)
                    if self._detect_block(html, check_length=False):
                        raise BlockedError(url, "challenge appeared while waiting", html) from exc
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
            else:
                # Nothing to wait for: give late scripts a moment to render.
                await asyncio.sleep(1.5)

            html = await page.content()
            if self._detect_block(html):
                raise BlockedError(url, html=html)
            return html
        except BlockedError:
            raise
        except Exception as exc:
            logger.error("Error fetching %s: %s", url, exc)
            raise
        finally:
            await page.close()

    @staticmethod
    async def _content_or_empty(page) -> str:
        """Return ``page.content()``, or ``""`` while the page is mid-navigation."""
        try:
            return await page.content()
        except Exception as exc:
            logger.debug("page.content() failed (page navigating?): %s", exc)
            return ""

    async def _close_unlocked(self) -> None:
        """Shut down relay, context, and browser. Caller must hold ``_browser_lock``."""
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
            self._camoufox_ctx = None
            logger.info("Browser closed.")

    async def close(self) -> None:
        """Shut down the relay process, browser context, and browser."""
        async with self._browser_lock:
            await self._close_unlocked()


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
    warnings: list[str] = []
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
                url,
                wait_selector=adapter.config.search_wait_selector,
                wait_until=adapter.config.page_load_wait,
                wait_selector_timeout=adapter.config.search_wait_timeout,
            )
        except Exception as exc:
            if not all_listings:
                return _json({"error": f"Failed to fetch page {page_num}: {exc}", "url": url})
            # Keep the pages already collected instead of discarding them.
            logger.warning("Page %d failed (%s); keeping %d listings.", page_num, exc, len(all_listings))
            warnings.append(f"Stopped at page {page_num}: {exc}")
            break

        page_listings = await asyncio.to_thread(adapter.parse_search, html)
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

    # The post-date pass skips listings the details pass already handled, and
    # detail_limit caps the detail-page fetches of both passes together.
    post_date_limit = detail_page_budget(all_listings, params.detail_limit)
    if post_date_limit != 0:
        post_date_enriched, post_date_errors = await enrich_post_dates(
            all_listings, browser, adapter,
            concurrency=params.detail_concurrency,
            rotate_every_batches=params.vpn_rotate_batches,
            limit=post_date_limit,
        )
    blocked = sum(1 for e in detail_errors + post_date_errors if e.get("kind") == "blocked")
    if blocked:
        warnings.append(f"{blocked} detail page(s) were blocked by bot protection (captcha).")

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
            "warnings": warnings,
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
            url,
            wait_selector=adapter.config.detail_wait_selector,
            wait_until=adapter.config.page_load_wait,
        )
    except Exception as exc:
        return _json({"error": f"Failed to fetch listing: {exc}", "url": url})

    detail = await asyncio.to_thread(adapter.parse_detail, html, url)
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
        # A debug dump should show a block page rather than hide it behind an error.
        return await browser.fetch_page(
            params.url, wait_selector=params.wait_selector, raise_on_block=False
        )
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
