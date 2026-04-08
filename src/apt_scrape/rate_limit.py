"""apt_scrape.rate_limit — Per-site adaptive rate limiter with jittered delays."""

from __future__ import annotations

import asyncio
import random
import time


class RateLimiter:
    """Single-domain rate limiter with jittered delays.

    Each call to wait() ensures at least min_delay seconds have passed
    since the previous call, with a random jitter up to max_delay.
    """

    def __init__(self, min_delay: float = 2.0, max_delay: float = 4.0) -> None:
        self._min_delay = min_delay
        self._max_delay = max_delay
        self._last_request: float = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Wait until the rate limit window has passed."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            delay = random.uniform(self._min_delay, self._max_delay)
            remaining = delay - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            self._last_request = time.monotonic()


class DomainRateLimiter:
    """Multi-domain rate limiter — separate jittered delays per domain."""

    def __init__(self) -> None:
        self._limiters: dict[str, RateLimiter] = {}
        self._default = RateLimiter(min_delay=2.0, max_delay=4.0)

    def register(self, domain: str, min_delay: float = 2.0, max_delay: float = 4.0) -> None:
        """Register per-domain delay settings."""
        self._limiters[domain] = RateLimiter(min_delay=min_delay, max_delay=max_delay)

    async def wait(self, domain: str | None = None) -> None:
        """Wait for the appropriate domain's rate limit."""
        limiter = self._limiters.get(domain, self._default) if domain else self._default
        await limiter.wait()
