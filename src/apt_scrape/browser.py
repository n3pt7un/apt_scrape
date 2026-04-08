"""apt_scrape.browser — Camoufox-based stealth browser for scraping.

Uses Camoufox (patched Firefox with anti-fingerprinting). Includes:
- Lazy browser startup
- Context recycling every N pages
- Full browser restart every M requests
- Block detection (DataDome, CAPTCHA, Cloudflare)
- Integration with ProxyProvider for proxy rotation
- Local pproxy relay for authenticated HTTP proxies (Playwright/Firefox
  does not support HTTP proxy auth natively)
- Hard timeout on every fetch via asyncio.wait_for
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import sys
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Lifecycle thresholds
_MAX_REQUESTS_BEFORE_RESTART = int(os.getenv("BROWSER_MAX_REQUESTS", "75"))
_PAGES_BEFORE_CONTEXT_RECYCLE = int(os.getenv("BROWSER_CONTEXT_RECYCLE", "15"))
_FETCH_HARD_TIMEOUT = float(os.getenv("BROWSER_FETCH_TIMEOUT", "90"))


def detect_block(html: str) -> bool:
    """Return True if the page looks like a bot-challenge or block page."""
    if not html:
        return True
    if "captcha-delivery.com" in html:
        return True
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if title_match:
        title = title_match.group(1).lower()
        if any(w in title for w in (
            "access denied", "robot check", "captcha", "blocked",
            "just a moment", "403", "forbidden",
        )):
            return True
    if len(html) < 2000 and "<html" in html.lower():
        return True
    return False


class Fetcher:
    """Camoufox-based stealth browser with lifecycle management.

    Usage:
        fetcher = Fetcher(proxy_provider=my_proxy)
        html = await fetcher.fetch("https://...", wait_selector="div.results")
        await fetcher.close()
    """

    def __init__(
        self,
        proxy_provider: Any = None,
        headless: bool | str = False,
    ) -> None:
        from apt_scrape.proxy import NoProxyProvider
        self._proxy = proxy_provider or NoProxyProvider()
        # headless=True is detected by DataDome. Use False (shows window)
        # or 'virtual' (Xvfb on Linux — appears non-headless to JS).
        self._headless = headless
        self._browser = None
        self._context = None
        self._camoufox_ctx = None
        self._relay_proc = None
        self._relay_port: int = 0
        self._total_requests = 0
        self._pages_in_session = 0
        self._lock = asyncio.Lock()

    @staticmethod
    def _free_port() -> int:
        """Return an available local TCP port."""
        with socket.socket() as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    async def _start_relay(self) -> None:
        """Start a local unauthenticated HTTP relay via pproxy.

        Playwright/Firefox does not support HTTP proxy authentication natively.
        pproxy listens on localhost without auth and forwards to the IPRoyal
        endpoint with credentials. Format: -r http://host:port#user:pass
        """
        await self._stop_relay()

        creds = self._proxy.get_proxy_credentials()
        host_port = self._proxy.get_proxy_host_port()
        if not host_port or not creds:
            return

        self._relay_port = self._free_port()
        remote = f"{host_port}#{creds[0]}:{creds[1]}"

        self._relay_proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pproxy",
            "-l", f"http://127.0.0.1:{self._relay_port}",
            "-r", remote,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(1.0)

        if self._relay_proc.returncode is not None:
            logger.error("pproxy relay failed to start (exit code %d).", self._relay_proc.returncode)
            self._relay_proc = None
            self._relay_port = 0
            return

        logger.info("HTTP relay started: 127.0.0.1:%d -> %s", self._relay_port, host_port)

    async def _stop_relay(self) -> None:
        """Stop the pproxy relay process."""
        if self._relay_proc is not None:
            try:
                self._relay_proc.terminate()
                await asyncio.wait_for(self._relay_proc.wait(), timeout=3)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._relay_proc.kill()
                except ProcessLookupError:
                    pass
            self._relay_proc = None
            self._relay_port = 0

    async def _ensure_browser(self) -> None:
        """Start Camoufox browser if not running, or restart if threshold reached."""
        if self._browser is not None and self._total_requests >= _MAX_REQUESTS_BEFORE_RESTART:
            logger.info("Restarting browser after %d requests.", self._total_requests)
            await self._close_browser()

        if self._browser is not None:
            return

        from camoufox.async_api import AsyncCamoufox

        self._camoufox_ctx = AsyncCamoufox(headless=self._headless)
        self._browser = await self._camoufox_ctx.__aenter__()

        # Proxy: start relay if needed, then pass unauthenticated proxy to context
        proxy_dict = None
        if self._proxy.get_proxy_host_port():
            await self._start_relay()
            if self._relay_port:
                proxy_dict = {"server": f"http://127.0.0.1:{self._relay_port}"}
                logger.info("Browser using proxy via relay: 127.0.0.1:%d", self._relay_port)

        ctx_kwargs: dict = {}
        if proxy_dict:
            ctx_kwargs["proxy"] = proxy_dict
        self._context = await self._browser.new_context(**ctx_kwargs)
        # Disable Brotli to avoid garbled content with certain sites
        await self._context.set_extra_http_headers(
            {"Accept-Encoding": "gzip, deflate"}
        )

        self._total_requests = 0
        self._pages_in_session = 0
        logger.info("Camoufox browser started (headless=%s).", self._headless)

    async def _close_browser(self) -> None:
        """Close the browser and clean up."""
        if self._context:
            try:
                await self._context.close()
            except Exception as exc:
                logger.debug("Error closing context: %s", exc)
            self._context = None
        if self._browser and self._camoufox_ctx:
            try:
                await self._camoufox_ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("Error closing Camoufox: %s", exc)
            self._browser = None
            self._camoufox_ctx = None
            logger.info("Browser closed.")
        await self._stop_relay()

    async def _recycle_if_needed(self) -> None:
        """Rotate proxy and restart browser periodically."""
        self._pages_in_session += 1
        if self._pages_in_session >= _PAGES_BEFORE_CONTEXT_RECYCLE:
            logger.info("Recycling browser session after %d pages.", self._pages_in_session)
            self._proxy.rotate()
            await self._close_browser()
            await self._ensure_browser()

    async def fetch(
        self,
        url: str,
        wait_selector: str | None = None,
        wait_timeout: float = 15.0,
        page_load_wait: str = "networkidle",
    ) -> str:
        """Fetch a URL and return rendered HTML.

        Args:
            url: Page URL to fetch.
            wait_selector: CSS selector to wait for after navigation.
            wait_timeout: Seconds to wait for the selector (in seconds).
            page_load_wait: Playwright wait_until event for page.goto.
                Default is "networkidle" to let DataDome JS challenges resolve.

        Returns:
            Raw HTML string.

        Raises:
            BlockDetectedError: If the page is a bot challenge.
            TimeoutError: If the fetch exceeds the hard timeout.
        """
        async with self._lock:
            return await asyncio.wait_for(
                self._fetch_inner(url, wait_selector, wait_timeout, page_load_wait),
                timeout=_FETCH_HARD_TIMEOUT,
            )

    async def _fetch_inner(
        self,
        url: str,
        wait_selector: str | None,
        wait_timeout: float,
        page_load_wait: str = "networkidle",
    ) -> str:
        """Internal fetch — browser lifecycle + page navigation."""
        from apt_scrape.retry import BlockDetectedError

        await self._ensure_browser()
        await self._recycle_if_needed()

        logger.info("Fetching: %s", url)
        goto_timeout = 45000 if page_load_wait == "networkidle" else 30000
        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until=page_load_wait, timeout=goto_timeout)

            if wait_selector:
                try:
                    await page.wait_for_selector(
                        wait_selector, timeout=int(wait_timeout * 1000)
                    )
                except Exception as exc:
                    logger.warning("Selector '%s' not found: %s", wait_selector, exc)

            # Small pause for JS hydration
            await asyncio.sleep(1.5)
            html = await page.content()
            self._total_requests += 1

            if detect_block(html):
                logger.warning("Block detected on %s", url)
                raise BlockDetectedError(f"Blocked on {url}")

            return html
        finally:
            await page.close()

    async def fetch_with_retry(
        self,
        url: str,
        wait_selector: str | None = None,
        wait_timeout: float = 15.0,
        max_attempts: int = 3,
        rejection_checker: Callable[[str], str | None] | None = None,
        page_load_wait: str = "networkidle",
    ) -> str:
        """Fetch with proxy rotation on block detection.

        On each block/error: rotate proxy, restart browser, retry.

        Args:
            rejection_checker: Optional callable(html) -> str|None. If it
                returns a non-None string, the page is treated as a site
                rejection and retried. Typically ``adapter.detect_rejection``.
            page_load_wait: Playwright wait_until event for page.goto.
        """
        from apt_scrape.retry import (
            BlockDetectedError, SiteRejectionError,
            classify_error, ErrorClass,
        )

        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                html = await self.fetch(
                    url, wait_selector, wait_timeout,
                    page_load_wait=page_load_wait,
                )
                # Check for site-level rejection (valid HTTP 200 but error content)
                if rejection_checker is not None:
                    reason = rejection_checker(html)
                    if reason:
                        raise SiteRejectionError(
                            f"Site rejected request for {url}: {reason}"
                        )
                return html
            except (
                BlockDetectedError, SiteRejectionError,
                TimeoutError, ConnectionError, OSError,
            ) as exc:
                last_exc = exc
                error_class = classify_error(exc)
                logger.warning(
                    "Fetch failed (attempt %d/%d, %s): %s",
                    attempt, max_attempts, error_class.name, exc,
                )
                if error_class == ErrorClass.PERMANENT:
                    raise
                if error_class in (ErrorClass.BLOCKED, ErrorClass.RATE_LIMITED):
                    self._proxy.rotate()
                    await self._close_browser()
                    wait_time = 3 * (2 ** (attempt - 1))  # 3, 6, 12
                    logger.info("Waiting %ds before retry...", wait_time)
                    await asyncio.sleep(wait_time)
                elif error_class == ErrorClass.TRANSIENT:
                    await self._close_browser()
                    await asyncio.sleep(2)

        raise RuntimeError(f"All {max_attempts} attempts failed for {url}") from last_exc

    async def close(self) -> None:
        """Shut down the browser."""
        async with self._lock:
            await self._close_browser()
