"""Block detection and detail enrichment against saved pages (contracts C1, C2).

No network and no real browser: a fake Playwright page serves the fixtures in
tests/fixtures, and enrichment runs against a fake BrowserManager.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import apt_scrape.server as server_mod
from apt_scrape.enrichment import BLOCK_BREAKER_THRESHOLD, enrich_post_dates, enrich_with_details
from apt_scrape.server import BlockedError, BrowserManager
from apt_scrape.sites import get_adapter

FIXTURES = Path(__file__).parent / "fixtures"
# DataDome interstitial as immobiliare.it serves it to a flagged client
DATADOME_HTML = (FIXTURES / "datadome_interstitial.html").read_text(encoding="utf-8")
# A real-shaped listing page whose <title> carries the street number 403
DETAIL_403_HTML = (FIXTURES / "immobiliare_detail_403.html").read_text(encoding="utf-8")
# A page that loads fine but has no listing content (selector drift)
BLANK_PAGE_HTML = (
    "<html><head><title>Immobiliare.it</title></head><body><nav><ul>"
    + "".join(f"<li><a href='/x{i}'>Voce di menu {i}</a></li>" for i in range(80))
    + "</ul></nav></body></html>"
)

URL = "https://www.immobiliare.it/annunci/94514403/"


# ---------------------------------------------------------------------------
# _detect_block on the fixtures
# ---------------------------------------------------------------------------


def test_datadome_fixture_is_a_block_page():
    assert BrowserManager._detect_block(DATADOME_HTML)
    # Also right after navigation, when the short-page check is off
    assert BrowserManager._detect_block(DATADOME_HTML, check_length=False)


def test_listing_page_titled_with_403_is_not_a_block_page():
    assert "Levante 403" in DETAIL_403_HTML.split("</title>")[0]
    assert "js.datadome.co" in DETAIL_403_HTML  # the normal DataDome tag is not a challenge
    assert not BrowserManager._detect_block(DETAIL_403_HTML)
    assert not BrowserManager._detect_block(DETAIL_403_HTML, check_length=False)


@pytest.mark.parametrize("title", [
    "Trilocale viale Pietramellara 403, Bologna - Immobiliare.it",
    "403 - Bilocale in affitto, Bologna",
    "Monolocale | Rif. 403 Forbidden Street",
    "Errore 403? No: attico con terrazzo",
])
def test_titles_merely_containing_403_are_not_blocks(title):
    html = DETAIL_403_HTML.replace(
        "Bilocale in affitto in via Emilia Levante 403, Bologna - Immobiliare.it", title
    )
    assert f"<title>{title}</title>" in html
    assert not BrowserManager._detect_block(html)


# ---------------------------------------------------------------------------
# fetch paths with a fake Playwright page
# ---------------------------------------------------------------------------


def _manager(contents, *, proxies=(), goto_side_effect=None, wait_side_effect=None):
    """A BrowserManager whose context hands out one fake page.

    *contents* is the sequence of page.content() results (the last one repeats).
    """
    contents = list(contents)

    async def content():
        return contents.pop(0) if len(contents) > 1 else contents[0]

    manager = BrowserManager()
    manager._proxy_list = list(proxies)
    browser = MagicMock()
    browser.is_connected.return_value = True
    manager._browser = browser
    page = MagicMock()
    page.goto = AsyncMock(side_effect=goto_side_effect)
    page.content = AsyncMock(side_effect=content)
    page.wait_for_selector = AsyncMock(side_effect=wait_side_effect)
    page.close = AsyncMock()
    page.title = AsyncMock(return_value="")
    page.evaluate = AsyncMock(return_value="")
    context = MagicMock()
    context.new_page = AsyncMock(return_value=page)
    manager._context = context
    manager.rotate_proxy = AsyncMock()
    return manager, page


@pytest.fixture
def no_waits(monkeypatch):
    """Drop the challenge recheck, the retry backoff and the post-rotation pause."""
    real_sleep = asyncio.sleep

    async def fast_sleep(delay, *args, **kwargs):
        await real_sleep(0)

    monkeypatch.setattr(server_mod, "CHALLENGE_RECHECK_SECONDS", 0)
    monkeypatch.setattr(server_mod, "TRANSIENT_RETRY_DELAY", (0, 0))
    monkeypatch.setattr(server_mod.asyncio, "sleep", fast_sleep)


@pytest.mark.asyncio
async def test_search_page_fetch_raises_blocked_without_proxies(no_waits):
    manager, page = _manager([DATADOME_HTML])
    with pytest.raises(BlockedError) as info:
        await manager.fetch_page(URL, wait_selector="li.in-searchLayoutListItem", min_interval=0)
    assert info.value.url == URL
    assert page.goto.await_count == 1  # a block is not a transient error: no retry
    page.wait_for_selector.assert_not_awaited()  # failed fast, before the selector timeout


@pytest.mark.asyncio
async def test_listing_page_with_403_title_is_returned(no_waits):
    manager, page = _manager([DETAIL_403_HTML])
    html = await manager.fetch_page_parallel(URL, wait_selector="h1", min_interval=0)
    assert html == DETAIL_403_HTML
    page.wait_for_selector.assert_awaited_once()


@pytest.mark.asyncio
async def test_challenge_that_clears_itself_is_not_a_block(no_waits):
    manager, _ = _manager([DATADOME_HTML, DETAIL_403_HTML])
    assert await manager.fetch_page_parallel(URL, wait_selector="h1", min_interval=0) == DETAIL_403_HTML


@pytest.mark.asyncio
async def test_challenge_appearing_during_selector_wait_raises_blocked(no_waits):
    # SPA shell after goto (not a block yet), then the selector times out on the challenge
    manager, page = _manager(
        ["<html><body><div id='app'></div></body></html>", DATADOME_HTML],
        wait_side_effect=TimeoutError("Timeout 15000ms exceeded."),
    )
    with pytest.raises(BlockedError):
        await manager.fetch_page_parallel(URL, wait_selector="h1", min_interval=0)
    assert page.goto.await_count == 1


@pytest.mark.asyncio
async def test_proxies_rotate_on_block_then_raise_blocked(no_waits):
    proxies = [{"server": "socks5://a:1080"}, {"server": "socks5://b:1080"}]
    manager, page = _manager([DATADOME_HTML], proxies=proxies)
    manager._requests_since_rotation = 0
    with pytest.raises(BlockedError):
        await manager.fetch_page(URL, wait_selector="h1", min_interval=0)
    assert manager.rotate_proxy.await_count == len(proxies)
    assert page.goto.await_count == 1 + len(proxies)


@pytest.mark.asyncio
async def test_proxy_rotation_gets_past_a_block(no_waits):
    proxies = [{"server": "socks5://a:1080"}, {"server": "socks5://b:1080"}]
    # first attempt: challenge after goto and on the recheck; after rotation: the listing
    manager, _ = _manager([DATADOME_HTML, DATADOME_HTML, DETAIL_403_HTML], proxies=proxies)
    manager._requests_since_rotation = 0
    assert await manager.fetch_page(URL, wait_selector="h1", min_interval=0) == DETAIL_403_HTML
    assert manager.rotate_proxy.await_count == 1


@pytest.mark.asyncio
async def test_transient_error_is_retried_once_then_propagates(no_waits):
    manager, page = _manager(
        [DETAIL_403_HTML],
        goto_side_effect=TimeoutError("page.goto: Timeout 30000ms exceeded."),
    )
    with pytest.raises(TimeoutError):
        await manager.fetch_page(URL, wait_selector="h1", min_interval=0)
    assert page.goto.await_count == 2


# ---------------------------------------------------------------------------
# enrich_with_details with a fake browser
# ---------------------------------------------------------------------------


def _cards(n: int, prefix: str = "") -> list[dict]:
    return [
        {"url": f"https://www.immobiliare.it/annunci/{prefix}{i}/", "title": f"Card {i}",
         "price": "€ 900/mese", "post_date": ""}
        for i in range(n)
    ]


def _fake_browser(outcome) -> MagicMock:
    """fetch_page_parallel -> outcome(url): HTML, or an exception instance to raise.

    It yields to the loop first, like a real page load, so parallel slots overlap.
    """
    async def fetch(url, **kwargs):
        await asyncio.sleep(0)
        result = outcome(url)
        if isinstance(result, BaseException):
            raise result
        return result

    browser = MagicMock()
    browser.fetch_page_parallel = AsyncMock(side_effect=fetch)
    browser.rotate_proxy = AsyncMock()
    return browser


def _detail_keys(listing: dict) -> set[str]:
    return {k for k in listing if k == "detail" or k.startswith("detail_")}


@pytest.mark.asyncio
async def test_ok_page_sets_status_and_every_detail_key():
    [listing] = _cards(1)
    browser = _fake_browser(lambda url: DETAIL_403_HTML)
    enriched, errors = await enrich_with_details([listing], browser, get_adapter("immobiliare"))

    assert (enriched, errors) == (1, [])
    assert listing["detail_status"] == "ok" and "detail_error" not in listing
    assert listing["detail"]["title"] == "Bilocale via Emilia Levante 403, Bologna"
    assert listing["detail_description"].startswith("Bilocale completamente arredato")
    assert listing["detail_address"] == "Via Emilia Levante 403, San Vitale, Bologna"
    assert listing["detail_features"]["Riscaldamento"].startswith("Autonomo")
    assert listing["detail_costs"]["Spese condominio"] == "€ 60/mese"
    assert listing["detail_energy_class"] == "D"
    assert listing["detail_agency"] == "Bologna Casa Immobiliare"
    assert listing["post_date"] == "Annuncio aggiornato il 03/10/2026"
    assert listing["title"] == "Card 0" and listing["price"] == "€ 900/mese"  # card data untouched


@pytest.mark.asyncio
async def test_blocked_empty_and_undetected_challenge_never_write_detail_keys():
    listings = _cards(3)
    pages = {
        listings[0]["url"]: BlockedError(listings[0]["url"]),
        listings[1]["url"]: BLANK_PAGE_HTML,
        # Defence in depth: a challenge page that slipped past detection parses empty
        listings[2]["url"]: DATADOME_HTML,
    }
    enriched, errors = await enrich_with_details(
        listings, _fake_browser(pages.get), get_adapter("immobiliare"), concurrency=3
    )

    assert enriched == 0
    assert [l["detail_status"] for l in listings] == ["blocked", "empty", "empty"]
    for listing in listings:
        assert _detail_keys(listing) == {"detail_status", "detail_error"}
        assert isinstance(listing["detail_error"], str) and listing["detail_error"]
    assert sorted(e["kind"] for e in errors) == ["blocked", "empty", "empty"]
    assert {e["url"] for e in errors} == {l["url"] for l in listings}


@pytest.mark.asyncio
async def test_breaker_skips_the_rest_after_three_consecutive_blocks():
    listings = _cards(7)
    browser = _fake_browser(lambda url: BlockedError(url))
    enriched, errors = await enrich_with_details(listings, browser, get_adapter("immobiliare"), concurrency=1)

    assert enriched == 0
    assert browser.fetch_page_parallel.await_count == BLOCK_BREAKER_THRESHOLD == 3
    assert [l["detail_status"] for l in listings] == ["blocked"] * 3 + ["skipped"] * 4
    for listing in listings[3:]:
        assert listing["detail_error"] == "stopped after repeated blocks"
        assert _detail_keys(listing) == {"detail_status", "detail_error"}
    assert [e["kind"] for e in errors] == ["blocked"] * 3 + ["skipped"] * 4


@pytest.mark.asyncio
async def test_breaker_with_parallel_batches_stops_within_one_batch():
    listings = _cards(8)
    browser = _fake_browser(lambda url: BlockedError(url))
    await enrich_with_details(listings, browser, get_adapter("immobiliare"), concurrency=2)

    fetched = browser.fetch_page_parallel.await_count
    statuses = [l["detail_status"] for l in listings]
    # Pages already in flight when the breaker trips finish as blocked; nothing after them is fetched
    assert BLOCK_BREAKER_THRESHOLD <= fetched <= BLOCK_BREAKER_THRESHOLD + 1
    assert statuses == ["blocked"] * fetched + ["skipped"] * (8 - fetched)


@pytest.mark.asyncio
async def test_blocks_separated_by_a_real_page_do_not_trip_the_breaker():
    listings = _cards(6)
    blocked_idx = {0, 1, 3, 4}
    by_url = {l["url"]: i for i, l in enumerate(listings)}
    browser = _fake_browser(
        lambda url: BlockedError(url) if by_url[url] in blocked_idx else DETAIL_403_HTML
    )
    enriched, _ = await enrich_with_details(listings, browser, get_adapter("immobiliare"), concurrency=1)

    assert browser.fetch_page_parallel.await_count == 6
    assert enriched == 2
    assert "skipped" not in [l["detail_status"] for l in listings]


@pytest.mark.asyncio
async def test_detail_and_post_date_passes_fetch_each_page_once():
    listings = _cards(5)
    outcomes = {
        listings[0]["url"]: DETAIL_403_HTML,
        listings[1]["url"]: BlockedError(listings[1]["url"]),
        listings[2]["url"]: BLANK_PAGE_HTML,
        listings[3]["url"]: RuntimeError("page.goto: NS_ERROR_NET_RESET\nCall log: ..."),
        listings[4]["url"]: DETAIL_403_HTML,  # beyond detail_limit: only the post-date pass reads it
    }
    browser = _fake_browser(outcomes.get)
    adapter = get_adapter("immobiliare")
    await enrich_with_details(listings, browser, adapter, detail_limit=4)
    assert [l.get("detail_status") for l in listings] == ["ok", "blocked", "empty", "error", None]
    assert listings[3]["detail_error"] == "page.goto: NS_ERROR_NET_RESET"

    enriched, errors = await enrich_post_dates(listings, browser, adapter)
    fetched = [c.args[0] for c in browser.fetch_page_parallel.await_args_list]
    assert sorted(fetched) == sorted(l["url"] for l in listings)  # one fetch per listing in total
    assert (enriched, errors) == (1, [])
    assert listings[4]["post_date"] == "Annuncio aggiornato il 03/10/2026"
    assert "detail" not in listings[4]  # the post-date pass only reads the date
