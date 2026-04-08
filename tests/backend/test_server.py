import pytest
import asyncio
from unittest.mock import MagicMock, patch
from apt_scrape.browser import Fetcher, detect_block


@pytest.mark.asyncio
async def test_fetcher_init_lazy():
    """Fetcher does not start a browser on init — _browser stays None."""
    fetcher = Fetcher()
    assert fetcher._browser is None


@pytest.mark.asyncio
async def test_close_resets_state():
    """Fetcher.close() sets _browser and _tab to None."""
    fetcher = Fetcher()
    mock_browser = MagicMock()
    mock_browser.stop = MagicMock()
    fetcher._browser = mock_browser
    fetcher._tab = MagicMock()

    await fetcher.close()

    assert fetcher._browser is None
    assert fetcher._tab is None
    mock_browser.stop.assert_called_once()


@pytest.mark.asyncio
async def test_close_is_idempotent():
    """Calling close() twice must not raise."""
    fetcher = Fetcher()
    mock_browser = MagicMock()
    mock_browser.stop = MagicMock()
    fetcher._browser = mock_browser

    await fetcher.close()
    await fetcher.close()  # second call — _browser is already None, should be a no-op

    assert fetcher._browser is None


@pytest.mark.asyncio
async def test_close_resilient_to_errors():
    """close() sets _browser to None even if browser.stop() raises."""
    fetcher = Fetcher()
    mock_browser = MagicMock()
    mock_browser.stop.side_effect = RuntimeError("simulated crash")
    fetcher._browser = mock_browser
    fetcher._tab = MagicMock()

    # Must not propagate the error
    await fetcher.close()

    assert fetcher._browser is None
    assert fetcher._tab is None


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
