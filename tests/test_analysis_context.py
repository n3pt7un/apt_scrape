"""Listing context, scoring outcome and chat tests for analysis.py / listing_chat.py (contracts C3, C4)."""
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage

# Job-4-shaped row: blocked detail page (all fields empty), card data populated
CARD_ONLY = {
    "source": "Immobiliare.it",
    "title": "Monolocale via Centotrecento 6, Irnerio, Bologna",
    "url": "https://www.immobiliare.it/annunci/94514440/",
    "price": "€ 1.000/mese",
    "sqm": "45 m²",
    "rooms": "1 locale",
    "bathrooms": "1 bagno",
    "address": "Monolocale via Centotrecento 6, Irnerio, Bologna",
    "description_snippet": "Monolocale completamente arredato, situato al secondo piano, riscaldamento autonomo",
    "post_date": "",
    "raw_features": ["1 locale", "45 m²", "1 bagno", "Piano 2", "Ascensore", "Arredato"],
    "detail": {"title": "", "price": "", "description": "", "address": "", "size": "", "floor": "",
               "extra_info": {}, "photos": [], "energy_class": "", "agency": "", "post_date": "",
               "costs": {}, "extra": {}},
    "detail_description": "", "detail_address": "", "detail_features": {}, "detail_costs": {},
    "detail_energy_class": "", "detail_agency": "", "_area": "", "_city": "bologna",
}

# Job-8-shaped row: detail page read
WITH_DETAIL = {
    "title": "Trilocale via Molise 3, Mazzini - Fossolo, Bologna",
    "price": "€ 500/mese", "sqm": "79 m²", "rooms": "3 locali", "bathrooms": "1 bagno",
    "address": "Trilocale via Molise 3, Mazzini - Fossolo, Bologna",
    "description_snippet": "",
    "raw_features": ["3 locali", "79 m²", "1 bagno", "Piano R", "No Ascensore", "Arredato"],
    "detail": {"title": "Trilocale via Molise 3, Mazzini - Fossolo, Bologna",
               "description": "Camera in appartamento condiviso. Bagno in condivisione.",
               "floor": "Piano rialzato", "size": "79 m²",
               "extra_info": {"Contratto": "Affitto, transitorio", "Riscaldamento": "Autonomo"},
               "costs": {"Spese condominio": "€ 40/mese"}},
    "detail_description": "Camera in appartamento condiviso. Bagno in condivisione.",
    "detail_address": "Via Molise, 3, Mazzini - Fossolo, Bologna",
    "detail_features": {"Contratto": "Affitto, transitorio", "Riscaldamento": "Autonomo"},
    "detail_costs": {"Spese condominio": "€ 40/mese"},
    "detail_status": "ok",
    "_area": "san-vitale-mazzini", "_city": "bologna",
}


def test_context_card_only_uses_search_card_data():
    from apt_scrape.analysis import format_listing_context

    ctx = format_listing_context(CARD_ONLY)
    assert "excerpt from the search results page" in ctx
    assert "riscaldamento autonomo" in ctx
    assert "Search card features: 1 locale, 45 m², 1 bagno, Piano 2, Ascensore, Arredato" in ctx
    assert "Bathrooms: 1 bagno" in ctx
    assert "Floor (search card): Piano 2" in ctx
    assert "Portal detail page: NOT read" in ctx
    assert "Missing (not scraped" in ctx and "costs" in ctx
    assert "{}" not in ctx and "{'" not in ctx  # never a Python dict repr
    assert "Address:" not in ctx  # card address == title: not repeated


def test_context_with_detail_renders_facts_as_label_lines():
    from apt_scrape.analysis import format_listing_context

    ctx = format_listing_context(WITH_DETAIL)
    assert "Description (portal detail page):" in ctx
    assert "  Contratto: Affitto, transitorio" in ctx
    assert "  Spese condominio: € 40/mese" in ctx
    assert "Floor: Piano rialzato" in ctx
    assert "Address: Via Molise, 3" in ctx
    assert "Portal detail page: read." in ctx
    assert "Search card features:" in ctx  # always a complement
    assert "excerpt" not in ctx


def test_context_blocked_status_and_floor_legend():
    from apt_scrape.analysis import format_listing_context

    blocked = {**CARD_ONLY, "raw_features": ["Piano T, 1"], "detail_status": "blocked",
               "detail_error": "DataDome captcha"}
    blocked.pop("detail")
    ctx = format_listing_context(blocked)
    assert "Piano T, 1 (T = piano terra)" in ctx
    assert "blocked by the portal's anti-bot protection: DataDome captcha" in ctx


def test_context_alias_kept():
    from apt_scrape.analysis import _format_listing_context, format_listing_context

    assert _format_listing_context is format_listing_context


def test_schema_reasoning_before_score():
    from apt_scrape.analysis import NotionApartmentFields

    props = list(NotionApartmentFields.model_json_schema()["properties"])
    assert props.index("ai_reason") < props.index("ai_verdict") < props.index("ai_score")
    assert props.index("notes") < props.index("ai_score")


def test_prompt_has_date_and_rubric():
    from datetime import date

    from apt_scrape.analysis import _system_prompt

    p = _system_prompt("prefs")
    assert date.today().isoformat() in p
    assert "non verificabile" in p and "must not lower the score" in p


# ---------------------------------------------------------------------------
# Node / batch behaviour with a fake LLM (no network)
# ---------------------------------------------------------------------------


def _ok_fields(**kw):
    from apt_scrape.analysis import NotionApartmentFields
    return NotionApartmentFields(title="T", ai_reason="r", ai_verdict="Good match", ai_score=70, **kw)


class FakeStructured:
    def __init__(self, outer):
        self.outer = outer

    async def ainvoke(self, messages, config=None):
        self.outer.structured_calls += 1
        item = self.outer.structured.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeLLM:
    profile = {"structured_output": True}

    def __init__(self, structured, raw=None):
        self.structured = list(structured)
        self.raw = list(raw or [])
        self.structured_calls = 0
        self.raw_calls = 0

    def with_structured_output(self, schema, method=None, include_raw=False):
        assert include_raw is True
        return FakeStructured(self)

    async def ainvoke(self, messages, config=None):
        self.raw_calls += 1
        item = self.raw.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def _msg(text="", stop="end_turn", inp=100, out=50, model="claude-sonnet-5-5"):
    return AIMessage(content=text, response_metadata={"stop_reason": stop, "model_name": model},
                     usage_metadata={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out})


def _anthropic_error(cls, status):
    import httpx2 as httpx  # anthropic 1.x is built on httpx2
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("boom", response=httpx.Response(status, request=req), body=None)


@pytest.fixture
def fresh_graph(monkeypatch):
    import apt_scrape.analysis as a
    monkeypatch.setattr(a, "_graph_instance", None)
    return a


@pytest.mark.asyncio
async def test_success_reports_real_tokens_and_cost(fresh_graph):
    a = fresh_graph
    llm = FakeLLM([{"raw": _msg(inp=1000, out=500), "parsed": _ok_fields(notes="n"), "parsing_error": None}])
    with patch.object(a, "_get_llm", return_value=llm):
        listings = [dict(CARD_ONLY, ai_error="old")]
        out = await a.analyse_listings(listings, "prefs")
    # UsageMetadataCallbackHandler only sees real chat-model runs; the fake bypasses callbacks
    assert out["scored"] == 1 and out["failed"] == 0
    assert set(out) >= {"tokens_used", "cost_usd", "scored", "failed"}
    assert listings[0]["ai_score"] == 70 and listings[0]["ai_notes"] == "n"
    assert "ai_error" not in listings[0]


@pytest.mark.asyncio
async def test_api_error_is_not_retried(fresh_graph):
    import anthropic
    a = fresh_graph
    llm = FakeLLM([_anthropic_error(anthropic.RateLimitError, 429)])
    with patch.object(a, "_get_llm", return_value=llm):
        listings = [dict(CARD_ONLY, notion_fields={"address": "keep"})]
        out = await a.analyse_listings(listings, "prefs")
    assert llm.structured_calls == 1 and llm.raw_calls == 0
    assert out == {**out, "scored": 0, "failed": 1}
    l = listings[0]
    assert l["ai_verdict"] == "Error" and l["ai_score"] == 0 and "429" in l["ai_error"]
    assert l["ai_reason"] == l["ai_error"]
    assert l["notion_fields"] == {"address": "keep"}  # earlier extraction untouched


@pytest.mark.asyncio
async def test_auth_error_stops_the_batch(fresh_graph, monkeypatch):
    import anthropic
    a = fresh_graph
    monkeypatch.setenv("ANALYSIS_CONCURRENCY", "1")
    monkeypatch.setattr(a, "_semaphore", None)
    llm = FakeLLM([_anthropic_error(anthropic.AuthenticationError, 401)])
    with patch.object(a, "_get_llm", return_value=llm):
        listings = [dict(CARD_ONLY), dict(CARD_ONLY), dict(CARD_ONLY)]
        out = await a.analyse_listings(listings, "prefs")
    assert llm.structured_calls == 1
    assert out["failed"] == 3
    assert all("401" in l["ai_error"] for l in listings)


@pytest.mark.asyncio
async def test_none_structured_result_falls_back_once_and_does_not_crash(fresh_graph):
    a = fresh_graph
    good_json = json.dumps({"title": "X", "ai_reason": "ok", "ai_verdict": "Potential", "ai_score": 45})
    llm = FakeLLM([{"raw": _msg("prose"), "parsed": None, "parsing_error": ValueError("bad")},
                   {"raw": _msg("prose"), "parsed": None, "parsing_error": None}],
                  raw=[_msg(good_json), _msg("still prose")])
    with patch.object(a, "_get_llm", return_value=llm):
        listings = [dict(CARD_ONLY), dict(WITH_DETAIL)]
        out = await a.analyse_listings(listings, "prefs")
    assert llm.raw_calls == 2
    assert out["scored"] == 1 and out["failed"] == 1
    scores = sorted(l["ai_score"] for l in listings)
    assert scores == [0, 45]


@pytest.mark.asyncio
async def test_fallback_without_score_is_a_parse_failure(fresh_graph, caplog):
    a = fresh_graph
    llm = FakeLLM([{"raw": _msg("x"), "parsed": None, "parsing_error": ValueError("bad")}],
                  raw=[_msg(json.dumps({"title": "X", "ai_reason": "r", "ai_verdict": "Skip"}))])
    with patch.object(a, "_get_llm", return_value=llm), caplog.at_level(logging.WARNING, "apt_scrape.analysis"):
        listings = [dict(CARD_ONLY)]
        await a.analyse_listings(listings, "prefs")
    assert listings[0]["ai_verdict"] == "Error"
    assert any("parse failure" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_max_tokens_stop_fails_without_retry(fresh_graph):
    a = fresh_graph
    llm = FakeLLM([{"raw": _msg("{", stop="max_tokens"), "parsed": None, "parsing_error": ValueError("cut")}])
    with patch.object(a, "_get_llm", return_value=llm):
        listings = [dict(CARD_ONLY)]
        await a.analyse_listings(listings, "prefs")
    assert llm.raw_calls == 0
    assert "truncated" in listings[0]["ai_error"]


@pytest.mark.asyncio
async def test_graph_returning_none_result_is_a_failure_not_a_crash():
    from apt_scrape.analysis import analyse_listings
    with patch("apt_scrape.analysis._get_graph") as g:
        g.return_value = AsyncMock()
        g.return_value.ainvoke.return_value = {"result": None}
        listings = [dict(CARD_ONLY), dict(WITH_DETAIL)]
        out = await analyse_listings(listings, "prefs")
    assert out["failed"] == 2 and all(l["ai_verdict"] == "Error" for l in listings)


def test_usage_cost_prices_input_and_output_separately():
    from apt_scrape.analysis import _usage_cost

    inp, out, cost = _usage_cost({"claude-sonnet-5-5": {"input_tokens": 1_000_000, "output_tokens": 100_000}})
    assert (inp, out) == (1_000_000, 100_000)
    assert cost == pytest.approx(2.0 + 1.0)
    assert _usage_cost({"claude-haiku-4-5-20251001": {"input_tokens": 1_000_000, "output_tokens": 0}})[2] == 1.0
    assert _usage_cost({"some/unknown": {"input_tokens": 10, "output_tokens": 10}}) == (10, 10, 0.0)


def test_usage_handler_collects_from_real_chat_model_runs():
    """The callback handler wiring: a real BaseChatModel run reports usage by model name."""
    import asyncio

    from langchain_core.callbacks import UsageMetadataCallbackHandler
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.outputs import ChatGeneration, ChatResult

    class M(BaseChatModel):
        @property
        def _llm_type(self):
            return "m"

        def _generate(self, messages, stop=None, run_manager=None, **kw):
            return ChatResult(generations=[ChatGeneration(message=_msg("hi", inp=7, out=3))])

    cb = UsageMetadataCallbackHandler()
    asyncio.run(M().ainvoke("x", config={"callbacks": [cb]}))
    assert cb.usage_metadata["claude-sonnet-5-5"]["input_tokens"] == 7


def test_make_llm_caps_and_timeouts(monkeypatch):
    from apt_scrape.analysis import _make_llm

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    llm = _make_llm()
    assert llm.max_tokens >= 8192
    assert llm.default_request_timeout and llm.max_retries >= 2
    assert _make_llm(max_tokens=32000).max_tokens == 32000


# ---------------------------------------------------------------------------
# Listing chat
# ---------------------------------------------------------------------------


def test_chat_prompt_uses_shared_context_without_duplicates(monkeypatch, tmp_path):
    from backend import listing_chat

    prefs = tmp_path / "p.txt"
    prefs.write_text("max 900", encoding="utf-8")
    monkeypatch.setenv("PREFERENCES_FILE", str(prefs))
    summary = {"url": CARD_ONLY["url"], "ai_status": "ok", "ai_score": 5, "ai_verdict": "Skip",
               "ai_reason": "Mancano informazioni", "features": CARD_ONLY["raw_features"]}
    prompt = listing_chat.build_system_prompt(dict(CARD_ONLY), summary)
    assert "riscaldamento autonomo" in prompt  # snippet reaches the chat
    assert prompt.count("Arredato") == 1  # one feature list only
    assert "Caratteristiche:" not in prompt and "Features: (none)" not in prompt
    assert "URL: https://www.immobiliare.it/annunci/94514440/" in prompt
    assert "senza la pagina di dettaglio" in prompt  # stale-analysis caveat


class _StreamLLM:
    def __init__(self, chunks):
        self.chunks = chunks

    async def astream(self, messages):
        for c in self.chunks:
            yield c


async def _collect(gen):
    return [json.loads(e) async for e in gen]


@pytest.mark.asyncio
async def test_chat_events_flag_truncated_answer():
    from backend import listing_chat

    llm = _StreamLLM([SimpleNamespace(content="Il prezzo", response_metadata={}),
                      SimpleNamespace(content="", response_metadata={"stop_reason": "max_tokens"})])
    events = await _collect(listing_chat.stream_events(llm, []))
    assert events[-1]["type"] == "done" and events[-1]["truncated"] is True
    assert "troncata" in "".join(e.get("delta", "") for e in events if e["type"] == "text")


@pytest.mark.asyncio
async def test_chat_events_empty_answer_at_max_tokens_is_error():
    from backend import listing_chat

    llm = _StreamLLM([SimpleNamespace(content=[{"type": "thinking", "thinking": "..."}], response_metadata={}),
                      SimpleNamespace(content="", response_metadata={"stop_reason": "max_tokens"})])
    events = await _collect(listing_chat.stream_events(llm, []))
    assert events[-1]["type"] == "error"
