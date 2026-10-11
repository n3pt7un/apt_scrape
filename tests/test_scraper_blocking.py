"""Block detection, fetch retries and enrichment outcomes (no network, no real browser)."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import apt_scrape.server as server_mod
from apt_scrape.enrichment import (
    BLOCK_BREAKER_THRESHOLD,
    detail_page_budget,
    enrich_post_dates,
    enrich_with_details,
)
from apt_scrape.server import BlockedError, BrowserManager
from apt_scrape.sites import get_adapter, get_adapter_with_overrides

# Shape of the DataDome interstitial logged in .logs/backend.log (job 4).
DATADOME_HTML = (
    '<html lang="en"><head><title>immobiliare.it</title><style>#cmsg{animation: A 1.5s;}</style>'
    '<meta name="viewport" content="width=device-width, initial-scale=1.0"></head>'
    '<body style="margin:0"><script data-cfasync="false">var dd={\'rt\':\'i\',\'cid\':\'AHrl==\','
    "'host':'geo.captcha-delivery.com'}</script>"
    '<script data-cfasync="false" src="https://ct.captcha-delivery.com/i.js"></script>'
    '<iframe src="https://geo.captcha-delivery.com/interstitial/?initialCid=AHrl" '
    'width="100%" height="100%"></iframe></body></html>'
)

_FILLER = "<p>" + ("Bilocale luminoso, arredato, vicino ai servizi. " * 60) + "</p>"

DETAIL_HTML = (
    "<html><head><title>Bilocale via Emilia Levante 403, Bologna - Immobiliare.it</title></head>"
    "<body><h1 class='Title_title__x'>Bilocale via Emilia Levante 403, Bologna</h1>"
    "<div class='ReadAll_readAll__y'>Bel bilocale.<br>Libero da novembre.</div>"
    "<dl class='FeaturesGrid_list__z'><dt>Piano</dt><dd>2</dd><dt>Arredato</dt><dd>Sì</dd></dl>"
    f"{_FILLER}</body></html>"
)

EMPTY_DETAIL_HTML = f"<html><head><title>Immobiliare.it</title></head><body>{_FILLER}</body></html>"


# ---------------------------------------------------------------------------
# _detect_block
# ---------------------------------------------------------------------------


def test_detect_block_datadome_interstitial():
    assert BrowserManager._detect_block(DATADOME_HTML)
    assert BrowserManager._detect_block(DATADOME_HTML, check_length=False)


def test_detect_block_street_number_403_is_not_a_block():
    assert not BrowserManager._detect_block(DETAIL_HTML)


@pytest.mark.parametrize("title", ["403 Forbidden", "Access Denied", "Just a moment...", "403"])
def test_detect_block_exact_block_titles(title):
    html = f"<html><head><title>{title}</title></head><body>{_FILLER}</body></html>"
    assert BrowserManager._detect_block(html)


def test_detect_block_full_page_merely_referencing_datadome_passes():
    html = (
        '<html><head><link rel="preconnect" href="https://geo.captcha-delivery.com">'
        "<title>Bilocale - Immobiliare.it</title></head><body>"
        + _FILLER * 25
        + "</body></html>"
    )
    assert len(html) > 50_000
    assert not BrowserManager._detect_block(html)


def test_detect_block_short_document_only_when_length_checked():
    tiny = "<html><head></head><body></body></html>"
    assert BrowserManager._detect_block(tiny)
    assert not BrowserManager._detect_block(tiny, check_length=False)


# ---------------------------------------------------------------------------
# fetch paths (fake Playwright page)
# ---------------------------------------------------------------------------


def _manager_with_page(contents, goto_side_effect=None) -> tuple[BrowserManager, MagicMock]:
    """A BrowserManager whose context hands out one fake page per call."""
    manager = BrowserManager()
    manager._proxy_list = []
    browser = MagicMock()
    browser.is_connected.return_value = True
    manager._browser = browser
    page = MagicMock()
    page.goto = AsyncMock(side_effect=goto_side_effect)
    page.content = AsyncMock(side_effect=contents)
    page.wait_for_selector = AsyncMock()
    page.close = AsyncMock()
    page.title = AsyncMock(return_value="")
    page.evaluate = AsyncMock(return_value="")
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    manager._context = context
    return manager, page


@pytest.mark.asyncio
async def test_fetch_page_parallel_raises_blocked_without_proxies(monkeypatch):
    monkeypatch.setattr(server_mod, "CHALLENGE_RECHECK_SECONDS", 0)
    manager, page = _manager_with_page(lambda: DATADOME_HTML)
    with pytest.raises(BlockedError) as info:
        await manager.fetch_page_parallel("https://www.immobiliare.it/annunci/1/", wait_selector="h1", min_interval=0)
    assert info.value.url == "https://www.immobiliare.it/annunci/1/"
    # Failed fast: the selector timeout was never waited out.
    page.wait_for_selector.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_page_returns_block_html_when_not_raising(monkeypatch):
    monkeypatch.setattr(server_mod, "CHALLENGE_RECHECK_SECONDS", 0)
    manager, _ = _manager_with_page(lambda: DATADOME_HTML)
    html = await manager.fetch_page("https://x.immobiliare.it/", min_interval=0, raise_on_block=False)
    assert "captcha-delivery" in html


@pytest.mark.asyncio
async def test_fetch_page_retries_transient_error_once(monkeypatch):
    monkeypatch.setattr(server_mod, "TRANSIENT_RETRY_DELAY", (0, 0))
    manager, page = _manager_with_page(
        lambda: DETAIL_HTML,
        goto_side_effect=[TimeoutError("page.goto: Timeout 30000ms exceeded."), None],
    )
    html = await manager.fetch_page("https://www.immobiliare.it/annunci/1/", wait_selector="h1", min_interval=0)
    assert "Emilia Levante" in html
    assert page.goto.await_count == 2


@pytest.mark.asyncio
async def test_fetch_page_does_not_retry_non_transient_error(monkeypatch):
    manager, page = _manager_with_page(lambda: DETAIL_HTML, goto_side_effect=ValueError("bad url"))
    with pytest.raises(ValueError):
        await manager.fetch_page("https://www.immobiliare.it/annunci/1/", min_interval=0)
    assert page.goto.await_count == 1


@pytest.mark.asyncio
async def test_rate_limit_reserves_spaced_slots():
    manager = BrowserManager()
    loop = asyncio.get_running_loop()
    starts: list[float] = []

    async def one():
        await manager._rate_limit(0.05)
        starts.append(loop.time())

    await asyncio.gather(one(), one(), one())
    starts.sort()
    assert starts[2] - starts[0] >= 0.09


# ---------------------------------------------------------------------------
# enrichment
# ---------------------------------------------------------------------------


def _listings(n: int) -> list[dict]:
    return [
        {"url": f"https://www.immobiliare.it/annunci/{i}/", "title": f"L{i}", "post_date": ""}
        for i in range(n)
    ]


def _fake_browser(fetch) -> MagicMock:
    browser = MagicMock()
    browser.fetch_page_parallel = AsyncMock(side_effect=fetch)
    browser.rotate_proxy = AsyncMock()
    return browser


@pytest.mark.asyncio
async def test_enrich_blocked_pages_get_status_and_no_detail_and_breaker_trips():
    listings = _listings(6)
    browser = _fake_browser(BlockedError("u"))
    enriched, errors = await enrich_with_details(
        listings, browser, get_adapter("immobiliare"), concurrency=1
    )
    assert enriched == 0
    assert browser.fetch_page_parallel.await_count == BLOCK_BREAKER_THRESHOLD
    statuses = [ls["detail_status"] for ls in listings]
    assert statuses == ["blocked"] * BLOCK_BREAKER_THRESHOLD + ["skipped"] * (6 - BLOCK_BREAKER_THRESHOLD)
    assert listings[-1]["detail_error"] == "stopped after repeated blocks"
    assert all("detail" not in ls and "detail_description" not in ls for ls in listings)
    assert {e["kind"] for e in errors} == {"blocked", "skipped"}
    assert all(set(e) == {"url", "error", "kind"} for e in errors)


@pytest.mark.asyncio
async def test_enrich_ok_empty_and_error_outcomes():
    listings = _listings(3)
    pages = {
        listings[0]["url"]: DETAIL_HTML,
        listings[1]["url"]: EMPTY_DETAIL_HTML,
    }

    async def fetch(url, **_):
        if url in pages:
            return pages[url]
        raise RuntimeError("page.goto: NS_ERROR_NET_RESET\nCall log: ...")

    enriched, errors = await enrich_with_details(
        listings, _fake_browser(fetch), get_adapter("immobiliare"), concurrency=3
    )
    ok, empty, failed = listings
    assert enriched == 1
    assert ok["detail_status"] == "ok" and "detail_error" not in ok
    assert ok["detail"]["title"].startswith("Bilocale")
    assert ok["detail_features"]["Arredato"] == "Sì"
    assert empty["detail_status"] == "empty" and "detail" not in empty
    assert failed["detail_status"] == "error"
    assert failed["detail_error"] == "page.goto: NS_ERROR_NET_RESET"
    assert sorted(e["kind"] for e in errors) == ["empty", "error"]


@pytest.mark.asyncio
async def test_enrich_uses_override_adapter_for_its_urls():
    adapter = get_adapter_with_overrides(
        "immobiliare", {"detail_wait_selector": "X", "page_load_wait": "networkidle"}
    )
    browser = _fake_browser(lambda url, **_: DETAIL_HTML)
    listings = _listings(1)
    await enrich_with_details(listings, browser, adapter)
    kwargs = browser.fetch_page_parallel.await_args.kwargs
    assert kwargs["wait_selector"] == "X"
    assert kwargs["wait_until"] == "networkidle"


@pytest.mark.asyncio
async def test_post_dates_skip_listings_handled_by_details_pass():
    listings = _listings(4)
    listings[0]["detail_status"] = "blocked"
    listings[1]["detail"] = {"title": "x"}
    listings[2]["post_date"] = "Annuncio aggiornato il 01/10/2026"
    browser = _fake_browser(lambda url, **_: EMPTY_DETAIL_HTML)
    enriched, errors = await enrich_post_dates(listings, browser, get_adapter("immobiliare"))
    assert browser.fetch_page_parallel.await_count == 1
    assert browser.fetch_page_parallel.await_args.args[0] == listings[3]["url"]
    # No date on the page: the existing value is left alone, not blanked.
    assert listings[3]["post_date"] == ""
    assert enriched == 0 and errors[0]["kind"] == "empty"


@pytest.mark.asyncio
async def test_post_dates_respect_limit_and_breaker():
    listings = _listings(6)
    browser = _fake_browser(BlockedError("u"))
    _, errors = await enrich_post_dates(listings, browser, get_adapter("immobiliare"), concurrency=1, limit=5)
    assert browser.fetch_page_parallel.await_count == BLOCK_BREAKER_THRESHOLD
    assert [e["kind"] for e in errors] == ["blocked"] * 3 + ["skipped"] * 2


def test_detail_page_budget():
    listings = [{"detail_status": "ok"}, {"detail_status": "skipped"}, {}, {}]
    assert detail_page_budget(listings, None) is None
    assert detail_page_budget(listings, 3) == 2
    assert detail_page_budget(listings, 1) == 0


# ---------------------------------------------------------------------------
# Repair round: the breaker stops the batch it trips in; blank facts are empty
# ---------------------------------------------------------------------------


class _CountingBrowser(BrowserManager):
    """A real BrowserManager (stagger, rate limiter, should_abort) whose navigations are all blocked."""

    def __init__(self) -> None:
        super().__init__()
        self._proxy_list = []
        self.navigations: list[str] = []

    async def _ensure_browser(self) -> None:
        return None

    async def _fetch_resilient(self, url, *args, **kwargs) -> str:
        self.navigations.append(url)
        await asyncio.sleep(0.005)
        raise BlockedError(url)


@pytest.mark.asyncio
async def test_breaker_calls_off_queued_slots_of_the_batch_that_trips_it(monkeypatch):
    import apt_scrape.enrichment as enrichment

    monkeypatch.setattr(enrichment, "_STAGGER_SECONDS", 0.0)
    browser = _CountingBrowser()
    listings = _listings(10)
    await enrich_with_details(listings, browser, get_adapter("immobiliare"), concurrency=10, min_interval=0.05)
    # All ten slots start together; each waits its rate-limit turn and re-checks the breaker then
    assert BLOCK_BREAKER_THRESHOLD <= len(browser.navigations) <= BLOCK_BREAKER_THRESHOLD + 1
    statuses = [ls["detail_status"] for ls in listings]
    assert statuses.count("blocked") == len(browser.navigations)
    assert statuses.count("skipped") == 10 - len(browser.navigations)
    assert all("detail" not in ls for ls in listings)


@pytest.mark.asyncio
async def test_post_date_breaker_calls_off_queued_slots(monkeypatch):
    import apt_scrape.enrichment as enrichment

    monkeypatch.setattr(enrichment, "_STAGGER_SECONDS", 0.0)
    browser = _CountingBrowser()
    _, errors = await enrich_post_dates(_listings(8), browser, get_adapter("immobiliare"), concurrency=8,
                                        min_interval=0.05)
    assert len(browser.navigations) <= BLOCK_BREAKER_THRESHOLD + 1
    assert [e["kind"] for e in errors].count("skipped") == 8 - len(browser.navigations)


@pytest.mark.asyncio
async def test_fetch_page_parallel_aborts_before_navigating():
    browser = _CountingBrowser()
    with pytest.raises(server_mod.FetchAborted):
        await browser.fetch_page_parallel("https://www.immobiliare.it/annunci/1/", min_interval=0,
                                          should_abort=lambda: True)
    assert browser.navigations == [] and browser._requests_since_rotation == 0


@pytest.mark.parametrize("detail,empty", [
    ({"title": "", "description": "", "extra_info": {"Piano": ""}}, True),   # a dd without text
    ({"title": "  ", "description": "\n", "extra_info": {}}, True),
    ({"title": None, "description": None, "extra_info": {"Piano": None, "Altro": "  "}}, True),
    ({"title": "", "description": "", "extra_info": {"Piano": "2"}}, False),
    ({"title": "Bilocale", "extra_info": {}}, False),
])
def test_empty_detail_ignores_blank_values(detail, empty):
    from apt_scrape.enrichment import _is_empty_detail

    assert _is_empty_detail(detail) is empty
