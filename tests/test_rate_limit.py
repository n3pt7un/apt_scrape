import asyncio
import time
import pytest
from apt_scrape.rate_limit import RateLimiter


@pytest.mark.asyncio
async def test_rate_limiter_enforces_minimum_delay():
    limiter = RateLimiter(min_delay=0.1, max_delay=0.1)
    t0 = time.monotonic()
    await limiter.wait()
    await limiter.wait()
    elapsed = time.monotonic() - t0
    assert elapsed >= 0.1


@pytest.mark.asyncio
async def test_rate_limiter_jitter_within_bounds():
    limiter = RateLimiter(min_delay=0.05, max_delay=0.15)
    delays = []
    for _ in range(10):
        t0 = time.monotonic()
        await limiter.wait()
        delays.append(time.monotonic() - t0)
    # Skip first (no wait needed)
    actual_delays = delays[1:]
    for d in actual_delays:
        assert d >= 0.04  # small tolerance


@pytest.mark.asyncio
async def test_rate_limiter_per_domain():
    from apt_scrape.rate_limit import DomainRateLimiter

    limiter = DomainRateLimiter()
    limiter.register("immobiliare.it", min_delay=0.1, max_delay=0.1)
    limiter.register("casa.it", min_delay=0.05, max_delay=0.05)

    t0 = time.monotonic()
    await limiter.wait("immobiliare.it")
    await limiter.wait("immobiliare.it")
    elapsed_imm = time.monotonic() - t0

    t1 = time.monotonic()
    await limiter.wait("casa.it")
    await limiter.wait("casa.it")
    elapsed_casa = time.monotonic() - t1

    assert elapsed_imm >= 0.1
    assert elapsed_casa >= 0.05
