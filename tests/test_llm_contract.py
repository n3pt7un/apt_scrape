"""Listing context, scoring outcome and token accounting (contracts C3, C4).

The LLM is a fake: a real (offline) BaseChatModel produces the usage metadata,
so the token/cost figures go through the same callback path as a real call.
"""

import asyncio
import json
from datetime import date

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import apt_scrape.analysis as analysis
from apt_scrape.analysis import NotionApartmentFields, analyse_listings, format_listing_context

# Shape of the 57 listings whose detail page was a DataDome challenge (jobs 4-6)
BLANK_DETAIL_ROW = {
    "source": "Immobiliare.it",
    "url": "https://www.immobiliare.it/annunci/94514001/",
    "title": "Bilocale via del Pratello 12, Saragozza, Bologna",
    "price": "€ 880/mese",
    "sqm": "50 m²",
    "rooms": "2 locali",
    "bathrooms": "1 bagno",
    "address": "Bilocale via del Pratello 12, Saragozza, Bologna",
    "description_snippet": "Grazioso bilocale arredato, cucina abitabile, contratto 4+4, libero da dicembre",
    "raw_features": ["2 locali", "50 m²", "1 bagno", "Piano 1", "Ascensore", "Arredato", "Balcone"],
    "post_date": "",
    "detail": {"title": "", "price": "", "description": "", "address": "", "size": "", "floor": "",
               "extra_info": {}, "photos": [], "energy_class": "", "agency": "", "post_date": "",
               "costs": {}, "extra": {}},
    "detail_description": "", "detail_address": "", "detail_features": {}, "detail_costs": {},
    "detail_energy_class": "", "detail_agency": "",
    "_area": "saragozza", "_city": "bologna",
}

FULL_ROW = {
    "title": "Trilocale via Massarenti 352, Bologna",
    "url": "https://www.immobiliare.it/annunci/94514002/",
    "price": "€ 1.150/mese", "sqm": "80 m²", "rooms": "3 locali", "bathrooms": "2 bagni",
    "description_snippet": "Trilocale luminoso...",
    "raw_features": ["3 locali", "80 m²", "2 bagni", "Piano 3", "Ascensore"],
    "detail": {
        "title": "Trilocale via Massarenti 352, Bologna",
        "description": "Trilocale luminoso con doppia esposizione.\nRiscaldamento centralizzato.",
        "floor": "3, con ascensore", "size": "80 m²",
        # a nested value as some portals emit it: must render as text, not as a repr
        "extra_info": {"Contratto": "Affitto, 4+4", "Riscaldamento": {"Tipo": "Centralizzato", "Alimentazione": "metano"}},
        "costs": {"Spese condominio": "€ 90/mese", "Cauzione": "€ 2.300"},
    },
    "detail_description": "Trilocale luminoso con doppia esposizione.\nRiscaldamento centralizzato.",
    "detail_address": "Via Giuseppe Massarenti 352, Massarenti, Bologna",
    "detail_status": "ok",
}


# ---------------------------------------------------------------------------
# format_listing_context
# ---------------------------------------------------------------------------


def _assert_no_python_repr(ctx: str) -> None:
    for token in ("{'", "'}", "{}", "[]", "['", "None", "True", "False"):
        assert token not in ctx, f"Python repr fragment {token!r} in context:\n{ctx}"


def test_context_blank_detail_falls_back_to_search_card():
    ctx = format_listing_context(BLANK_DETAIL_ROW)

    assert BLANK_DETAIL_ROW["description_snippet"] in ctx
    assert "excerpt from the search results page" in ctx
    assert "Arredato" in ctx and "Balcone" in ctx and "Piano 1" in ctx
    assert "2 locali, 50 m², 1 bagno, Piano 1, Ascensore, Arredato, Balcone" in ctx  # readable list
    assert "1 bagno" in ctx and "€ 880/mese" in ctx and "50 m²" in ctx
    assert "Bilocale via del Pratello 12" in ctx
    assert "saragozza" in ctx  # the portal search area
    assert "NOT read" in ctx and "Missing (not scraped" in ctx
    _assert_no_python_repr(ctx)


def test_context_full_listing_uses_detail_and_label_lines():
    ctx = format_listing_context(FULL_ROW)

    assert "Description (portal detail page):" in ctx
    assert "doppia esposizione" in ctx
    assert "Contratto: Affitto, 4+4" in ctx
    assert "Riscaldamento: Tipo: Centralizzato; Alimentazione: metano" in ctx
    assert "Spese condominio: € 90/mese" in ctx and "Cauzione: € 2.300" in ctx
    assert "Via Giuseppe Massarenti 352" in ctx
    assert "2 bagni" in ctx and "€ 1.150/mese" in ctx
    assert "Search card features: 3 locali, 80 m², 2 bagni, Piano 3, Ascensore" in ctx
    assert "Portal detail page: read." in ctx
    assert "excerpt" not in ctx  # the full description replaces the card excerpt
    _assert_no_python_repr(ctx)


def test_context_legacy_row_without_status_uses_its_detail():
    legacy = {k: v for k, v in FULL_ROW.items() if k not in ("detail_status", "detail_description")}
    ctx = format_listing_context(legacy)
    assert "Description (portal detail page):" in ctx and "doppia esposizione" in ctx
    assert "Portal detail page: read." in ctx


@pytest.mark.parametrize("status", ["blocked", "error", "empty", "skipped"])
def test_context_failed_detail_statuses_say_why(status):
    row = {k: v for k, v in BLANK_DETAIL_ROW.items() if not k.startswith("detail")}
    row.update(detail_status=status, detail_error="short reason")
    ctx = format_listing_context(row)
    assert "Portal detail page: NOT read" in ctx
    assert BLANK_DETAIL_ROW["description_snippet"] in ctx
    _assert_no_python_repr(ctx)


def test_context_without_snippet_names_the_missing_description():
    row = {k: v for k, v in BLANK_DETAIL_ROW.items() if k != "description_snippet"}
    ctx = format_listing_context(row)
    assert "Description" not in ctx.split("Data availability:")[0]
    missing = ctx.split("Missing (not scraped")[1]
    assert "description" in missing and "costs" in missing


# ---------------------------------------------------------------------------
# analyse_listings with a fake LLM
# ---------------------------------------------------------------------------


class _UsageModel(BaseChatModel):
    """Offline chat model: returns a message carrying usage metadata, like ChatAnthropic does."""

    input_tokens: int = 1000
    output_tokens: int = 500

    @property
    def _llm_type(self) -> str:
        return "fake-usage"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = AIMessage(
            content="{}",
            response_metadata={"model_name": "claude-sonnet-5-5", "stop_reason": "end_turn"},
            usage_metadata={"input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
                            "total_tokens": self.input_tokens + self.output_tokens},
        )
        return ChatResult(generations=[ChatGeneration(message=msg)])


class _FakeLLM:
    """Stands in for ChatAnthropic. *decide(human_prompt)* returns the parsed result,
    None (no structured output), or an exception to raise from the call."""

    profile = {"structured_output": True}

    def __init__(self, decide, fallback_text="still not json"):
        self.decide = decide
        self.fallback_text = fallback_text
        self.structured_calls: list[str] = []
        self.system_prompts: list[str] = []
        self.raw_calls = 0
        self.model = _UsageModel()

    def with_structured_output(self, schema, method=None, include_raw=False):
        assert schema is NotionApartmentFields and include_raw
        outer = self

        class _Structured:
            async def ainvoke(self, messages, config=None):
                outer.system_prompts.append(messages[0]["content"])
                human = messages[1]["content"]
                outer.structured_calls.append(human)
                decision = outer.decide(human)
                if isinstance(decision, BaseException):
                    raise decision
                # the usage goes through the graph's callbacks exactly like a real call
                raw = await outer.model.ainvoke(messages, config=config)
                return {"raw": raw, "parsed": decision, "parsing_error": None if decision else ValueError("no tool call")}

        return _Structured()

    async def ainvoke(self, messages, config=None):
        self.raw_calls += 1
        return AIMessage(content=self.fallback_text, response_metadata={"stop_reason": "end_turn"})


def _fields(score=70, **kw) -> NotionApartmentFields:
    return NotionApartmentFields(title="T", ai_reason="motivo", ai_verdict="Good match", ai_score=score,
                                 notes="Da verificare: spese", **kw)


def _httpx_request():
    import httpx2  # anthropic 1.x is built on httpx2

    return httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status):
    import httpx2

    return cls("boom", response=httpx2.Response(status, request=_httpx_request()), body=None)


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a _FakeLLM (built by the returned factory) as the scoring model."""
    monkeypatch.setattr(analysis, "_semaphore", None)
    monkeypatch.setattr(analysis, "_graph_instance", None)  # the real graph, whatever ran before

    def install(decide, **kw):
        llm = _FakeLLM(decide, **kw)
        monkeypatch.setattr(analysis, "_get_llm", lambda: llm)
        return llm

    return install


def test_scoring_reports_real_tokens_and_cost_and_uses_shared_context(fake_llm):
    llm = fake_llm(lambda human: _fields(81))
    listings = [dict(BLANK_DETAIL_ROW), dict(FULL_ROW, ai_error="old failure")]
    out = asyncio.run(analyse_listings(listings, "max 1200 euro"))

    # 2 calls x (1000 in + 500 out) at claude-sonnet-5-5 ($2 / $10 per 1M tokens)
    assert out["tokens_used"] == 3000
    assert out["cost_usd"] == pytest.approx(2000 * 2 / 1e6 + 1000 * 10 / 1e6)
    assert (out["scored"], out["failed"]) == (2, 0)
    for listing in listings:
        assert listing["ai_score"] == 81 and listing["ai_verdict"] == "Good match"
        assert listing["ai_reason"] == "motivo" and listing["ai_notes"] == "Da verificare: spese"
        assert listing["notion_fields"]["ai_score"] == 81
        assert "ai_error" not in listing
    # the model saw exactly the shared listing context, and today's date
    assert sorted(llm.structured_calls) == sorted(
        f"LISTING:\n{format_listing_context(l)}" for l in (BLANK_DETAIL_ROW, FULL_ROW)
    )
    assert all(date.today().isoformat() in p and "non verificabile" in p for p in llm.system_prompts)


@pytest.mark.parametrize("make_error", [
    lambda: _status_error(__import__("anthropic").InternalServerError, 500),
    lambda: _status_error(__import__("anthropic").RateLimitError, 429),
    lambda: __import__("anthropic").APITimeoutError(request=_httpx_request()),
    lambda: __import__("anthropic").APIConnectionError(request=_httpx_request()),
], ids=["500", "429", "timeout", "connection"])
def test_api_error_fails_only_that_listing_without_a_second_call(fake_llm, make_error):
    llm = fake_llm(lambda human: make_error() if "Massarenti" in human else _fields(55))
    ok, failed = dict(BLANK_DETAIL_ROW), dict(FULL_ROW, notion_fields={"address": "keep me"})
    out = asyncio.run(analyse_listings([ok, failed], "prefs"))

    assert len(llm.structured_calls) == 2 and llm.raw_calls == 0  # no fallback call on API errors
    assert (out["scored"], out["failed"]) == (1, 1)
    assert out["tokens_used"] == 1500  # only the successful call is billed
    assert ok["ai_score"] == 55 and "ai_error" not in ok
    assert failed["ai_error"] and failed["ai_verdict"] == "Error" and failed["ai_score"] == 0
    assert failed["ai_reason"] == failed["ai_error"]
    assert failed["notion_fields"] == {"address": "keep me"}


def test_missing_structured_result_is_a_failure_for_that_listing_only(fake_llm):
    llm = fake_llm(lambda human: None if "Pratello" in human else _fields(66))
    blank, full = dict(BLANK_DETAIL_ROW), dict(FULL_ROW)
    out = asyncio.run(analyse_listings([blank, full], "prefs"))

    assert llm.raw_calls == 1  # one raw-JSON retry for the unparseable answer, then give up
    assert (out["scored"], out["failed"]) == (1, 1)
    assert blank["ai_verdict"] == "Error" and blank["ai_score"] == 0 and blank["ai_error"]
    assert full["ai_score"] == 66


def test_raw_json_fallback_rescues_a_missing_structured_result(fake_llm):
    payload = json.dumps({"title": "X", "ai_reason": "ok", "ai_verdict": "Potential", "ai_score": 48})
    fake_llm(lambda human: None, fallback_text=f"Ecco: {payload}")
    listings = [dict(BLANK_DETAIL_ROW)]
    out = asyncio.run(analyse_listings(listings, "prefs"))
    assert out["scored"] == 1 and listings[0]["ai_score"] == 48 and "ai_error" not in listings[0]


def test_whole_batch_failure_returns_zero_tokens_and_never_raises(fake_llm):
    import anthropic

    fake_llm(lambda human: _status_error(anthropic.InternalServerError, 529))
    listings = [dict(BLANK_DETAIL_ROW), dict(FULL_ROW)]
    out = asyncio.run(analyse_listings(listings, "prefs"))
    assert out["tokens_used"] == 0 and out["cost_usd"] == 0
    assert (out["scored"], out["failed"]) == (0, 2)
    assert all(l["ai_verdict"] == "Error" for l in listings)


# ---------------------------------------------------------------------------
# Listing chat shares the context
# ---------------------------------------------------------------------------


def test_chat_prompt_embeds_the_shared_listing_context(monkeypatch, tmp_path):
    from backend import listing_chat

    prefs = tmp_path / "prefs.txt"
    prefs.write_text("Arredato, max 900", encoding="utf-8")
    monkeypatch.setenv("PREFERENCES_FILE", str(prefs))
    summary = {"url": BLANK_DETAIL_ROW["url"], "ai_status": "none"}
    prompt = listing_chat.build_system_prompt(dict(BLANK_DETAIL_ROW), summary)
    assert format_listing_context(BLANK_DETAIL_ROW) in prompt
    assert "Arredato, max 900" in prompt


# ---------------------------------------------------------------------------
# Repair round: concurrency lanes and request timeouts
# ---------------------------------------------------------------------------


def test_single_listing_rescore_does_not_queue_behind_a_batch(fake_llm, monkeypatch):
    monkeypatch.setenv("ANALYSIS_CONCURRENCY", "1")
    fake_llm(lambda human: _fields(70))

    async def scenario():
        shared = analysis._llm_semaphore()
        await shared.acquire()  # a run's batch holds the only shared slot
        try:
            listing = dict(FULL_ROW)
            out = await asyncio.wait_for(analyse_listings([listing], "prefs"), timeout=5)
            assert out["scored"] == 1 and listing["ai_score"] == 70
            # batches still share the module-wide limit
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(analyse_listings([dict(FULL_ROW), dict(FULL_ROW)], "prefs"), timeout=0.2)
        finally:
            shared.release()

    asyncio.run(scenario())


def test_scoring_timeout_covers_the_output_cap_and_chat_keeps_the_idle_timeout(monkeypatch):
    from backend import listing_chat

    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake")
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    scoring = analysis._make_llm()
    # A non-streamed answer arrives whole: the timeout must cover generating max_tokens (450 s at 16k)
    assert scoring.default_request_timeout >= 3600 * analysis._MAX_OUTPUT_TOKENS / 128_000
    assert scoring.max_retries == 2
    # The chat streams, so its timeout is the gap between events
    assert listing_chat._chat_llm().default_request_timeout == analysis._REQUEST_TIMEOUT_SEC

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    monkeypatch.setenv("OPENROUTER_API_KEY", "fake")
    assert analysis._make_llm().request_timeout >= 3600 * analysis._MAX_OUTPUT_TOKENS / 128_000
