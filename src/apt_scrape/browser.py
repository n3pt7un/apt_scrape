"""apt_scrape.browser — nodriver-based stealth browser for scraping.

Uses nodriver (Chrome, no WebDriver flags, no automation indicators). Includes:
- Lazy browser startup
- Context recycling every N pages
- Full browser restart every M requests
- Block detection (DataDome, CAPTCHA, Cloudflare)
- Integration with ProxyProvider for proxy rotation
- Hard timeout on every fetch via asyncio.wait_for
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
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
    """Nodriver-based stealth browser with lifecycle management.

    Usage:
        fetcher = Fetcher(proxy_provider=my_proxy)
        html = await fetcher.fetch("https://...", wait_selector="div.results")
        await fetcher.close()
    """

    def __init__(
        self,
        proxy_provider: Any = None,
        headless: bool = True,
    ) -> None:
        from apt_scrape.proxy import NoProxyProvider
        self._proxy = proxy_provider or NoProxyProvider()
        self._headless = headless
        self._browser = None
        self._tab = None
        self._total_requests = 0
        self._pages_in_session = 0
        self._lock = asyncio.Lock()

    async def _ensure_browser(self) -> None:
        """Start nodriver browser if not running, or restart if threshold reached."""
        if self._browser is not None and self._total_requests >= _MAX_REQUESTS_BEFORE_RESTART:
            logger.info("Restarting browser after %d requests.", self._total_requests)
            await self._close_browser()

        if self._browser is not None:
            return

        import nodriver as uc

        browser_args = []
        proxy_url = self._proxy.get_proxy_url()
        if proxy_url:
            browser_args.append(f"--proxy-server={proxy_url}")
            logger.info("Browser using proxy: %s", proxy_url.split("@")[-1])

        # Disable brotli encoding to avoid garbled content
        browser_args.append("--disable-features=AcceptEncodingBrotli")

        self._browser = await uc.start(
            headless=self._headless,
            browser_args=browser_args,
        )
        self._total_requests = 0
        self._pages_in_session = 0
        logger.info("Nodriver browser started (headless=%s).", self._headless)

    async def _close_browser(self) -> None:
        """Close the browser and clean up."""
        if self._browser is not None:
            try:
                self._browser.stop()
            except Exception as exc:
                logger.debug("Error closing browser: %s", exc)
            self._browser = None
            self._tab = None
            logger.info("Browser closed.")

    async def _recycle_if_needed(self) -> None:
        """Rotate proxy and restart browser context periodically."""
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
        page_load_wait: str = "domcontentloaded",
    ) -> str:
        """Fetch a URL and return rendered HTML.

        Args:
            url: Page URL to fetch.
            wait_selector: CSS selector to wait for after navigation.
            wait_timeout: Seconds to wait for the selector.
            page_load_wait: Not used directly by nodriver but kept for API compat.

        Returns:
            Raw HTML string.

        Raises:
            BlockDetectedError: If the page is a bot challenge.
            TimeoutError: If the fetch exceeds the hard timeout.
        """
        async with self._lock:
            return await asyncio.wait_for(
                self._fetch_inner(url, wait_selector, wait_timeout),
                timeout=_FETCH_HARD_TIMEOUT,
            )

    async def _fetch_inner(
        self,
        url: str,
        wait_selector: str | None,
        wait_timeout: float,
    ) -> str:
        """Internal fetch — browser lifecycle + page navigation."""
        from apt_scrape.retry import BlockDetectedError

        await self._ensure_browser()
        await self._recycle_if_needed()

        logger.info("Fetching: %s", url)
        tab = await self._browser.get(url)

        if wait_selector:
            try:
                await tab.select(wait_selector, timeout=wait_timeout)
            except Exception as exc:
                logger.warning("Selector '%s' not found: %s", wait_selector, exc)

        # Small pause for JS hydration
        await tab.sleep(1.5)
        html = await tab.get_content()
        self._total_requests += 1

        if detect_block(html):
            logger.warning("Block detected on %s", url)
            raise BlockDetectedError(f"Blocked on {url}")

        return html

    async def fetch_with_retry(
        self,
        url: str,
        wait_selector: str | None = None,
        wait_timeout: float = 15.0,
        max_attempts: int = 3,
    ) -> str:
        """Fetch with proxy rotation on block detection.

        On each block/error: rotate proxy, restart browser, retry.
        """
        from apt_scrape.retry import BlockDetectedError, classify_error, ErrorClass

        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                return await self.fetch(url, wait_selector, wait_timeout)
            except (BlockDetectedError, TimeoutError, ConnectionError, OSError) as exc:
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
