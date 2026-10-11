"""API side of the audit fixes (contract C6), exercised through the HTTP layer.

Rescore runs the real analyse_listings with a fake LLM (no network), so these
tests also check that the router builds the LLM input with
analysis.format_listing_context and that a failed call never clobbers a row.
"""
import os
os.environ["DB_PATH"] = ":memory:"

import json
import uuid

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlmodel import Session

import apt_scrape.analysis as analysis
from apt_scrape.analysis import NotionApartmentFields, format_listing_context
from backend.db import Job, Listing, SearchConfig, create_db_and_tables, engine
from backend.main import app
from backend.parsing import parse_price

create_db_and_tables()
client = TestClient(app)


def _config(**kw) -> int:
    with Session(engine) as s:
        cfg = SearchConfig(**{"name": f"api-{uuid.uuid4().hex[:8]}", "city": "bologna",
                              "schedule_days": "[]", "schedule_time": "08:00", **kw})
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def _job(config_id: int, **kw) -> int:
    with Session(engine) as s:
        job = Job(config_id=config_id, triggered_by="manual", **{"status": "done", **kw})
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def _listing(raw: dict, **cols) -> int:
    cid = cols.pop("config_id", None) or _config()
    jid = cols.pop("job_id", None) or _job(cid)
    url = raw.get("url") or f"https://www.immobiliare.it/annunci/api-{uuid.uuid4().hex}/"
    with Session(engine) as s:
        row = Listing(url=url, job_id=jid, config_id=cid, raw_json=json.dumps({**raw, "url": url}), **cols)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row.id


def _row(listing_id: int) -> Listing:
    with Session(engine) as s:
        return s.get(Listing, listing_id)


# ---------------------------------------------------------------------------
# Listing summary: detail status, facts, bathrooms
# ---------------------------------------------------------------------------


def test_legacy_row_with_only_a_feature_table_reads_as_ok_with_facts():
    raw = {
        "title": "Bilocale via Saffi 20",
        "raw_features": ["2 locali", "Piano 4", "Arredato"],
        # no detail_status, no detail_features: an early scrape that read the page
        "detail": {"title": "", "description": "",
                   "extra_info": {"Bagni": "2", "Riscaldamento": "Autonomo", "Arredato": "No", "Piano": "Piano terra"}},
        "notion_fields": {"furnished": True, "floor": "4"},
    }
    d = client.get(f"/listings/{_listing(raw, title='Bilocale via Saffi 20')}").json()

    assert d["detail_status"] == "ok" and d["detail_error"] is None
    assert d["facts"] == [
        {"label": "Bagni", "value": "2"}, {"label": "Riscaldamento", "value": "Autonomo"},
        {"label": "Arredato", "value": "No"}, {"label": "Piano", "value": "Piano terra"},
    ]
    assert d["bathrooms"] == "2 bagni"
    assert d["furnished"] is False          # the portal's table beats the card token and the AI
    assert d["floor"] == "Piano terra"


def test_facts_drop_blank_and_nested_values():
    raw = {"detail_status": "ok", "detail": {"title": "T"},
           "detail_features": {"Contratto": "4+4", "Vuoto": "", "Nullo": None, "Annidato": {"a": "b"},
                               "Lista": ["x"], "  ": "senza etichetta"}}
    d = client.get(f"/listings/{_listing(raw)}").json()
    assert d["facts"] == [{"label": "Contratto", "value": "4+4"}]


@pytest.mark.parametrize("raw,status,error", [
    ({"detail_status": "ok", "detail_error": "stale", "detail": {"title": "T"}}, "ok", None),
    ({"detail_status": "error", "detail_error": "page.goto: Timeout"}, "error", "page.goto: Timeout"),
    ({"detail_status": "empty", "detail_error": "no content"}, "empty", "no content"),
    ({"detail_status": "skipped", "detail_error": "stopped after repeated blocks"}, "missing",
     "stopped after repeated blocks"),
    ({"detail": {"title": "", "description": "", "extra_info": {}}}, "empty", None),
    ({"title": "solo card"}, "missing", None),
])
def test_detail_status_derivation(raw, status, error):
    d = client.get(f"/listings/{_listing(raw)}").json()
    assert (d["detail_status"], d["detail_error"]) == (status, error)


def test_summary_keeps_legacy_fields_and_adds_run_attribution():
    cid = _config()
    first, later = _job(cid), _job(cid)
    lid = _listing({"bathrooms": "1 bagno", "description_snippet": "estratto"}, config_id=cid, job_id=first,
                   title="Monolocale", price="€ 700/mese", last_job_id=later)
    [d] = [x for x in client.get(f"/listings?config_id={cid}").json() if x["id"] == lid]
    for key in ("id", "url", "job_id", "config_id", "title", "price", "scraped_at", "ai_score", "ai_verdict",
                "ai_status", "price_eur", "features", "floor", "furnished", "available_from", "description_snippet"):
        assert key in d, key
    assert d["job_id"] == first and d["last_job_id"] == later
    assert d["first_seen_at"] == d["scraped_at"] and d["last_seen_at"]
    assert d["bathrooms"] == "1 bagno" and d["detail_status"] == "missing" and d["facts"] == []


# ---------------------------------------------------------------------------
# Jobs list and config validation
# ---------------------------------------------------------------------------


def test_jobs_list_never_ships_logs_by_default():
    cid = _config()
    jid = _job(cid, log="[08:00:00] riga di log\n" * 500)
    rows = client.get("/jobs").json()  # the SPA's polled call: no filter
    assert rows and all("log" not in j for j in rows)
    assert any(j["id"] == jid for j in rows)
    assert client.get(f"/jobs/{jid}").json()["log"].count("riga di log") == 500
    with_log = client.get("/jobs?include_log=1").json()
    assert next(j for j in with_log if j["id"] == jid)["log"].startswith("[08:00:00]")


@pytest.mark.parametrize("bad", [
    {"schedule_time": "24:00"},
    {"schedule_time": "7:30"},
    {"schedule_time": "07:60"},
    {"schedule_days": ["lun"]},
    {"detail_concurrency": 0},
    {"vpn_rotate_batches": 0},
    {"start_page": 4, "end_page": 3},
])
def test_config_update_rejects_invalid_values_and_keeps_the_row(bad):
    created = client.post("/configs", json={"name": f"valid-{uuid.uuid4().hex[:6]}", "city": "bologna",
                                           "schedule_days": ["mon"], "schedule_time": "07:30"})
    assert created.status_code == 201
    cfg = created.json()
    resp = client.put(f"/configs/{cfg['id']}", json={"name": cfg["name"], "city": "bologna", **bad})
    assert resp.status_code == 422
    after = client.get(f"/configs/{cfg['id']}").json()
    assert (after["schedule_time"], after["schedule_days"]) == ("07:30", ["mon"])
    assert (after["detail_concurrency"], after["vpn_rotate_batches"], after["end_page"]) == (5, 3, 10)


# ---------------------------------------------------------------------------
# parse_price
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("€ 1.200/mese", 1200.0),
    ("€ 1.200,00/mese", 1200.0),
    ("1.200,50", 1200.5),
    ("1,200", 1200.0),
    ("€ 850/mese", 850.0),
    ("da 900 €", 900.0),
    ("da € 1.050/mese", 1050.0),
    ("€ 750 - € 900/mese", 750.0),
    ("€ 1.250.000", 1250000.0),
    ("Prezzo su richiesta", None),
    ("Trattativa riservata", None),
    (None, None),
])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


# ---------------------------------------------------------------------------
# Rescore through the real analyse_listings with a fake LLM
# ---------------------------------------------------------------------------


class _FakeLLM:
    profile = {"structured_output": True}

    def __init__(self, outcome):
        self.outcome = outcome  # NotionApartmentFields, or an exception to raise
        self.prompts: list[str] = []
        self.raw_calls = 0

    def with_structured_output(self, schema, method=None, include_raw=False):
        outer = self

        class _Structured:
            async def ainvoke(self, messages, config=None):
                outer.prompts.append(messages[1]["content"])
                if isinstance(outer.outcome, BaseException):
                    raise outer.outcome
                return {"raw": AIMessage(content=""), "parsed": outer.outcome, "parsing_error": None}

        return _Structured()

    async def ainvoke(self, messages, config=None):
        self.raw_calls += 1
        return AIMessage(content="not json")


@pytest.fixture
def ai(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.txt"
    prefs.write_text("Bologna, arredato, max 1000", encoding="utf-8")
    monkeypatch.setenv("PREFERENCES_FILE", str(prefs))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(analysis, "_semaphore", None)
    monkeypatch.setattr(analysis, "_graph_instance", None)  # the real graph, whatever ran before

    def install(outcome):
        llm = _FakeLLM(outcome)
        monkeypatch.setattr(analysis, "_get_llm", lambda: llm)
        return llm

    return install


def _card_row(**extra) -> dict:
    return {
        "url": f"https://www.immobiliare.it/annunci/rescore-{uuid.uuid4().hex}/",
        "title": "Bilocale via Saragozza 10, Bologna", "price": "€ 950/mese", "sqm": "55 m²", "rooms": "2 locali",
        "bathrooms": "1 bagno", "description_snippet": "Bilocale luminoso e arredato, libero da subito",
        "raw_features": ["2 locali", "55 m²", "1 bagno", "Piano 2", "Arredato"],
        "detail_status": "blocked", "detail_error": "blocked by bot protection", **extra,
    }


def _seed_card_row(raw: dict, **cols) -> int:
    return _listing(raw, title=raw["title"], price=raw["price"], sqm=raw["sqm"], rooms=raw["rooms"], **cols)


def test_rescore_sends_the_shared_context_and_stores_the_result(ai):
    llm = ai(NotionApartmentFields(title="Bilocale", ai_reason="Arredato e nel budget", ai_verdict="Good match",
                                   ai_score=74, notes="Da verificare: spese"))
    raw = _card_row(ai_error="old failure")
    lid = _seed_card_row(raw)

    resp = client.post(f"/listings/{lid}/rescore")
    assert resp.status_code == 200
    assert llm.prompts == [f"LISTING:\n{format_listing_context(raw)}"]
    assert "Bilocale luminoso e arredato" in llm.prompts[0]  # card excerpt reaches the model
    d = resp.json()
    assert d["ai_score"] == 74 and d["ai_status"] == "ok" and d["ai_reason"] == "Arredato e nel budget"
    stored = json.loads(_row(lid).raw_json)
    assert stored["ai_notes"] == "Da verificare: spese" and "ai_error" not in stored
    assert stored["detail_status"] == "blocked"  # rescore touches only the AI keys


def test_rescore_api_failure_on_a_scored_row_is_502_and_changes_nothing(ai):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    llm = ai(anthropic.InternalServerError("overloaded", response=httpx2.Response(529, request=request), body=None))
    raw = _card_row(ai_score=68, ai_verdict="Good match", ai_reason="buona", notion_fields={"address": "Via Saragozza 10"})
    lid = _seed_card_row(raw, ai_score=68, ai_verdict="Good match")
    before = _row(lid)

    resp = client.post(f"/listings/{lid}/rescore")
    assert resp.status_code == 502
    assert isinstance(resp.json()["detail"], str) and resp.json()["detail"]
    assert len(llm.prompts) == 1 and llm.raw_calls == 0  # no second call after an API error
    after = _row(lid)
    assert (after.ai_score, after.ai_verdict, after.raw_json) == (68, "Good match", before.raw_json)


def test_rescore_failure_on_an_unscored_row_records_the_error(ai):
    import anthropic
    import httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    ai(anthropic.RateLimitError("slow down", response=httpx2.Response(429, request=request), body=None))
    lid = _seed_card_row(_card_row())

    resp = client.post(f"/listings/{lid}/rescore")
    assert resp.status_code == 200
    assert resp.json()["ai_status"] == "error"
    stored = json.loads(_row(lid).raw_json)
    assert "429" in stored["ai_error"] and stored["ai_verdict"] == "Error"


# ---------------------------------------------------------------------------
# Repair round: run membership, attribution flags, deleting a live run
# ---------------------------------------------------------------------------


def test_run_stats_and_run_filter_include_listings_the_run_saw_again():
    cid = _config()
    first, later = _job(cid), _job(cid)
    new_id = _listing({}, config_id=cid, job_id=later, last_job_id=later, price="€ 1.000/mese")
    known_id = _listing({}, config_id=cid, job_id=first, last_job_id=later, price="€ 600/mese")

    assert client.get(f"/jobs/{later}/stats").json()["avg_price_eur"] == 800
    assert {d["id"] for d in client.get(f"/listings?run={later}").json()} == {new_id, known_id}
    assert {d["id"] for d in client.get(f"/listings?job_id={later}").json()} == {new_id}  # first found only


def test_run_that_only_saw_known_listings_still_has_an_average_price():
    cid = _config()
    first, later = _job(cid), _job(cid)
    _listing({}, config_id=cid, job_id=first, last_job_id=later, price="€ 700/mese")
    assert client.get(f"/jobs/{later}/stats").json()["avg_price_eur"] == 700


def test_attribution_flags_mark_legacy_jobs_and_rows():
    from sqlalchemy import update
    cid = _config()
    legacy, new = _job(cid), _job(cid)
    old_row = _listing({}, config_id=cid, job_id=legacy)
    new_row = _listing({}, config_id=cid, job_id=new)
    with Session(engine) as s:  # what the migration leaves on pre-existing rows (an insert applies the default)
        s.exec(update(Job).where(Job.id == legacy).values(attribution_exact=None))
        s.exec(update(Listing).where(Listing.id == old_row).values(first_seen_exact=None))
        s.commit()

    jobs = {j["id"]: j for j in client.get(f"/jobs?config_id={cid}").json()}
    assert jobs[legacy]["attribution_exact"] is False and jobs[new]["attribution_exact"] is True
    assert client.get(f"/jobs/{legacy}").json()["attribution_exact"] is False
    assert client.get(f"/listings/{old_row}").json()["first_seen_exact"] is False
    assert client.get(f"/listings/{new_row}").json()["first_seen_exact"] is True


def test_delete_refuses_a_run_in_progress_but_not_a_stale_row():
    from backend import scheduler
    cid = _config()
    jid = _job(cid, status="running")
    scheduler._active[cid] = (jid, None)
    try:
        resp = client.delete(f"/jobs/{jid}")
        assert resp.status_code == 409 and "in corso" in resp.json()["detail"]
        assert client.get(f"/jobs/{jid}").status_code == 200
    finally:
        del scheduler._active[cid]
    # a 'running' row no task owns (a crash leftover) can still be deleted
    assert client.delete(f"/jobs/{jid}").status_code == 204


def test_successful_rescore_clears_the_pending_rescore_marker(ai):
    ai(NotionApartmentFields(title="Bilocale", ai_reason="Nel budget", ai_verdict="Good match", ai_score=70,
                             notes="ok"))
    lid = _seed_card_row(_card_row(ai_rescore_pending=True, ai_last_error="429 rate limited"),
                         ai_score=55, ai_verdict="Potential")
    assert client.post(f"/listings/{lid}/rescore").status_code == 200
    stored = json.loads(_row(lid).raw_json)
    assert _row(lid).ai_score == 70
    assert "ai_rescore_pending" not in stored and "ai_last_error" not in stored


def test_failed_rescore_keeps_the_pending_rescore_marker(ai):
    import anthropic
    import httpx2  # anthropic 1.x is built on httpx2

    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    ai(anthropic.RateLimitError("rate limited", response=httpx2.Response(429, request=request), body=None))
    lid = _seed_card_row(_card_row(ai_rescore_pending=True), ai_score=55, ai_verdict="Potential")
    assert client.post(f"/listings/{lid}/rescore").status_code == 502
    assert json.loads(_row(lid).raw_json)["ai_rescore_pending"] is True and _row(lid).ai_score == 55
