import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from apt_scrape.browser import Fetcher, detect_block


@pytest.mark.asyncio
async def test_fetcher_init_lazy():
    """Fetcher does not start a browser on init — _browser stays None."""
    fetcher = Fetcher()
    assert fetcher._browser is None


@pytest.mark.asyncio
async def test_close_resets_state():
    """Fetcher.close() sets _browser to None and closes context."""
    fetcher = Fetcher()
    mock_browser = MagicMock()
    mock_ctx = MagicMock()
    mock_ctx.close = AsyncMock()
    mock_camoufox = MagicMock()
    mock_camoufox.__aexit__ = AsyncMock()
    fetcher._browser = mock_browser
    fetcher._context = mock_ctx
    fetcher._camoufox_ctx = mock_camoufox

    await fetcher.close()

    assert fetcher._browser is None
    assert fetcher._context is None


@pytest.mark.asyncio
async def test_close_is_idempotent():
    """Calling close() twice must not raise."""
    fetcher = Fetcher()
    mock_browser = MagicMock()
    mock_camoufox = MagicMock()
    mock_camoufox.__aexit__ = AsyncMock()
    fetcher._browser = mock_browser
    fetcher._camoufox_ctx = mock_camoufox

    await fetcher.close()
    await fetcher.close()  # second call — already None, should be a no-op

    assert fetcher._browser is None


@pytest.mark.asyncio
async def test_close_resilient_to_errors():
    """close() sets _browser to None even if __aexit__ raises."""
    fetcher = Fetcher()
    mock_browser = MagicMock()
    mock_camoufox = MagicMock()

    async def fail_exit(*a):
        raise RuntimeError("simulated crash")

    mock_camoufox.__aexit__ = fail_exit
    fetcher._browser = mock_browser
    fetcher._camoufox_ctx = mock_camoufox

    # Must not propagate the error
    await fetcher.close()

    assert fetcher._browser is None


@pytest.mark.parametrize("html, expected", [
    # empty string → blocked
    ("", True),
    # captcha delivery → blocked
    ('<html><body>captcha-delivery.com stuff</body></html>' + "x" * 3000, True),
    # access denied title → blocked
    ("<html><head><title>Access Denied</title></head><body>" + "x" * 3000 + "</body></html>", True),
    # cloudflare "just a moment" title → blocked
    ("<html><head><title>Just a moment...</title></head><body>" + "x" * 3000 + "</body></html>", True),
    # very short html page → blocked
    ("<html><body>hi</body></html>", True),
    # normal page with sufficient content → not blocked
    ("<html><head><title>Apartments for rent</title></head><body>" + "x" * 3000 + "</body></html>", False),
])
def test_detect_block_integration(html, expected):
    """detect_block correctly identifies bot-challenge pages."""
    assert detect_block(html) is expected
