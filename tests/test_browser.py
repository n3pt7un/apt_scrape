import pytest
from apt_scrape.browser import Fetcher, detect_block


def test_detect_block_captcha():
    html = '<html><head><title>Blocked</title></head><body><script src="captcha-delivery.com/js"></script></body></html>'
    assert detect_block(html) is True


def test_detect_block_datadome():
    html = '<html><head><title>Access Denied</title></head><body>Blocked</body></html>'
    assert detect_block(html) is True


def test_detect_block_short_page():
    html = '<html><head><title>OK</title></head><body>x</body></html>'
    assert detect_block(html) is True  # < 2000 chars


def test_detect_block_normal_page():
    html = '<html><head><title>Apartments</title></head><body>' + 'x' * 3000 + '</body></html>'
    assert detect_block(html) is False


def test_detect_block_cloudflare():
    html = '<html><head><title>Just a moment...</title></head><body>' + 'x' * 3000 + '</body></html>'
    assert detect_block(html) is True


def test_detect_block_403_title():
    html = '<html><head><title>403 Forbidden</title></head><body>' + 'x' * 3000 + '</body></html>'
    assert detect_block(html) is True


@pytest.mark.asyncio
async def test_fetcher_creates_without_crash():
    """Fetcher can be instantiated (browser not started until first use)."""
    fetcher = Fetcher(headless=True)
    assert fetcher._browser is None
    # Don't actually start — that requires a real Chrome install
