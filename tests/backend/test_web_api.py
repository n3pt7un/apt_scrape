# tests/backend/test_web_api.py — endpoints and helpers added for the React SPA
import asyncio
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

os.environ["DB_PATH"] = ":memory:"

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlmodel import Session

import backend.db as db_module
from backend import geocoding, listing_chat
from backend.db import Job, Listing, SearchConfig, create_db_and_tables, engine
from backend.main import app, create_app
from backend.parsing import parse_price, parse_rooms, parse_sqm
from backend.routers import jobs as jobs_router

create_db_and_tables()
client = TestClient(app)

SUMMARY_KEYS = {
    # Listing columns (raw_json dropped)
    "id", "url", "job_id", "config_id", "title", "price", "sqm", "rooms", "area", "city",
    "ai_score", "ai_verdict", "notion_page_id", "scraped_at",
    "triage_status", "triage_note", "triage_updated_at", "seen_at", "lat", "lon", "geocode_status",
    # joined
    "config_name",
    # derived from raw_json
    "source", "thumbnail", "address", "description_snippet", "price_eur", "sqm_num", "rooms_num",
    "price_per_sqm", "ai_status", "ai_reason", "ai_notes", "energy_class", "furnished",
    "available_from", "floor", "features", "post_date",
    "bathrooms", "facts", "detail_status", "detail_error", "agency",
    # run attribution (last_seen_at / last_job_id / first_seen_exact are also Listing columns)
    "first_seen_at", "last_seen_at", "last_job_id", "first_seen_exact",
}

NOSADELLA_TITLE = "Bilocale via Nosadella 34, Saragozza dentro le Mura, Bologna"


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _seed_config(name: str = "Web", city: str = "bologna", schedule_days: str = "[]") -> int:
    with Session(engine) as s:
        cfg = SearchConfig(name=name, city=city, schedule_days=schedule_days, schedule_time="08:00")
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def _seed_job(config_id: int, **kw) -> int:
    with Session(engine) as s:
        job = Job(config_id=config_id, triggered_by="manual", **{"status": "done", **kw})
        s.add(job)
        s.commit()
        s.refresh(job)
        return job.id


def _seed_listing(config_id: int, job_id: int, raw=None, **cols) -> int:
    url = cols.pop("url", f"https://example.com/web/{uuid.uuid4().hex}")
    raw_json = raw if isinstance(raw, str) else json.dumps({"url": url, **(raw or {})})
    with Session(engine) as s:
        lst = Listing(url=url, job_id=job_id, config_id=config_id, raw_json=raw_json, **cols)
        s.add(lst)
        s.commit()
        s.refresh(lst)
        return lst.id


def _seed_basic(**cols) -> tuple[int, int, int]:
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    return cfg_id, job_id, _seed_listing(cfg_id, job_id, **cols)


def _get(listing_id: int) -> Listing:
    with Session(engine) as s:
        return s.get(Listing, listing_id)


def _rich_raw() -> dict:
    return {
        "source": "Immobiliare.it",
        "title": NOSADELLA_TITLE,
        "price": "€ 1.200/mese",
        "sqm": "70 m²",
        "rooms": "5+ locali",
        "address": NOSADELLA_TITLE,
        "thumbnail": "https://img.example.com/1.jpg",
        "description_snippet": "Luminoso bilocale in centro",
        "post_date": "2026-09-30",
        "raw_features": ["2 locali", "70 m²", "Arredato"],
        "detail": {"floor": "3", "photos": []},
        "detail_address": "",
        "detail_energy_class": "",
        "notion_fields": {
            "address": "Via Nosadella 34, Bologna, BO",
            "energy_class": "C",
            "furnished": True,
            "available_from": "2026-11-01",
            "notes": "Spese condominiali 80€",
            "floor": None,
        },
        "ai_score": 72,
        "ai_verdict": "Good match",
        "ai_reason": "Buona zona, prezzo in linea",
    }


def _parse_sse(body: str) -> list[tuple[str, object]]:
    events = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        if block.startswith(":"):
            events.append(("comment", block))
            continue
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def _async_client(application=app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_migration_adds_listing_columns_to_old_schema(tmp_path, monkeypatch):
    db_file = tmp_path / "old.db"
    con = sqlite3.connect(db_file)
    con.executescript("""
        CREATE TABLE listing (
            id INTEGER NOT NULL PRIMARY KEY, url VARCHAR NOT NULL, job_id INTEGER NOT NULL,
            config_id INTEGER NOT NULL, title VARCHAR NOT NULL, price VARCHAR NOT NULL,
            sqm VARCHAR NOT NULL, rooms VARCHAR NOT NULL, area VARCHAR NOT NULL,
            city VARCHAR NOT NULL, ai_score INTEGER, ai_verdict VARCHAR, notion_page_id VARCHAR,
            raw_json VARCHAR NOT NULL, scraped_at DATETIME NOT NULL
        );
        INSERT INTO listing VALUES (1, 'https://x/1', 1, 1, 'T', '€ 900', '50 m²', '2 locali', '',
                                    'bologna', NULL, NULL, NULL, '{}', '2026-10-01 10:00:00');
    """)
    con.close()

    old_engine = create_engine(f"sqlite:///{db_file}")
    monkeypatch.setattr(db_module, "engine", old_engine)
    db_module._migrate_listing_web_20261004()
    db_module._migrate_listing_web_20261004()  # idempotent

    with old_engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(listing)"))]
        row = conn.execute(text("SELECT title, triage_status, seen_at, lat, geocode_status FROM listing")).one()
    for col in ("triage_status", "triage_note", "triage_updated_at", "seen_at", "lat", "lon", "geocode_status"):
        assert col in cols
    assert tuple(row) == ("T", None, None, None, None)
    old_engine.dispose()


# ---------------------------------------------------------------------------
# Parsing + summary serialization
# ---------------------------------------------------------------------------


def test_parsers():
    assert parse_price("€ 1.200/mese") == 1200.0
    assert parse_price("Prezzo su richiesta") is None
    assert parse_sqm("70 m²") == 70.0
    assert parse_sqm("1.250 m²") == 1250.0
    assert parse_sqm("") is None
    assert parse_rooms("2 locali") == 2
    assert parse_rooms("1 locale") == 1
    assert parse_rooms("5+ locali") == 5
    assert parse_rooms("") is None


def test_summary_derived_fields():
    raw = _rich_raw()
    cfg_id, job_id, lid = _seed_basic(
        raw=raw, title=raw["title"], price=raw["price"], sqm=raw["sqm"], rooms=raw["rooms"],
        city="bologna", ai_score=72, ai_verdict="Good match",
    )
    resp = client.get(f"/listings?config_id={cfg_id}")
    assert resp.status_code == 200
    [d] = resp.json()
    assert set(d) == SUMMARY_KEYS
    assert d["config_name"] == "Web"
    assert d["price_eur"] == 1200.0
    assert d["sqm_num"] == 70.0
    assert d["rooms_num"] == 5
    assert d["price_per_sqm"] == 17.1
    assert d["ai_status"] == "ok"
    assert d["ai_reason"] == "Buona zona, prezzo in linea"
    assert d["ai_notes"] == "Spese condominiali 80€"
    # detail_address is empty -> AI-normalised address wins over the card address
    assert d["address"] == "Via Nosadella 34, Bologna, BO"
    assert d["energy_class"] == "C"
    assert d["furnished"] is True
    assert d["available_from"] == "2026-11-01"
    assert d["floor"] == "3"  # notion_fields.floor is null -> detail.floor
    assert d["features"] == ["2 locali", "70 m²", "Arredato"]
    assert d["source"] == "Immobiliare.it"
    assert d["thumbnail"] == "https://img.example.com/1.jpg"
    assert d["description_snippet"] == "Luminoso bilocale in centro"
    assert d["post_date"] == "2026-09-30"


def test_summary_address_fallbacks_and_ai_status():
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    detail_first = _seed_listing(cfg_id, job_id, raw={
        "detail_address": "Via Irnerio 5", "notion_fields": {"address": "X"}, "address": "Y",
    })
    raw_only = _seed_listing(cfg_id, job_id, raw={"address": "Bilocale via Roma 1, Bologna"},
                             ai_score=0, ai_verdict="Error")
    garbled = _seed_listing(cfg_id, job_id, raw="{not json", price="€ 900/mese", sqm="")
    by_id = {d["id"]: d for d in client.get(f"/listings?config_id={cfg_id}").json()}

    assert by_id[detail_first]["address"] == "Via Irnerio 5"
    assert by_id[detail_first]["ai_status"] == "none"
    assert by_id[raw_only]["address"] == "Bilocale via Roma 1, Bologna"
    assert by_id[raw_only]["ai_status"] == "error"
    g = by_id[garbled]
    assert g["address"] is None and g["source"] is None and g["features"] == []
    assert g["price_eur"] == 900.0 and g["sqm_num"] is None and g["price_per_sqm"] is None


# ---------------------------------------------------------------------------
# List filters
# ---------------------------------------------------------------------------


def test_listing_filters_triage_unseen_ai_status():
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    fav = _seed_listing(cfg_id, job_id, triage_status="preferito", ai_score=80, ai_verdict="Good")
    discarded = _seed_listing(cfg_id, job_id, triage_status="scartato", ai_score=0, ai_verdict="Error",
                              seen_at=datetime(2026, 10, 1))
    untriaged = _seed_listing(cfg_id, job_id)

    def ids(query: str) -> set[int]:
        resp = client.get(f"/listings?config_id={cfg_id}&{query}")
        assert resp.status_code == 200, resp.text
        return {d["id"] for d in resp.json()}

    assert ids("triage=preferito") == {fav}
    assert ids("triage=none") == {untriaged}
    assert ids("triage=preferito,none") == {fav, untriaged}
    assert ids("unseen=true") == {fav, untriaged}
    assert ids("unseen=false") == {discarded}
    assert ids("ai_status=ok") == {fav}
    assert ids("ai_status=error") == {discarded}
    assert ids("ai_status=none") == {untriaged}
    assert client.get("/listings?triage=bogus").status_code == 422
    assert client.get("/listings?ai_status=bogus").status_code == 422
    assert client.get("/listings?limit=2000").status_code == 200
    assert client.get("/listings?limit=2001").status_code == 422


# ---------------------------------------------------------------------------
# Detail, triage, seen
# ---------------------------------------------------------------------------


def test_get_listing_detail():
    raw = _rich_raw()
    cfg_id, job_id, lid = _seed_basic(raw=raw, title=raw["title"])
    resp = client.get(f"/listings/{lid}")
    assert resp.status_code == 200
    d = resp.json()
    assert SUMMARY_KEYS <= set(d)
    assert d["raw"]["notion_fields"]["energy_class"] == "C"
    assert d["job"]["id"] == job_id and d["job"]["status"] == "done"
    assert client.get("/listings/999999").status_code == 404


def test_triage_partial_update():
    _, _, lid = _seed_basic()
    resp = client.patch(f"/listings/{lid}/triage", json={"status": "preferito"})
    assert resp.status_code == 200
    d = resp.json()
    assert d["triage_status"] == "preferito" and d["triage_note"] is None
    assert d["triage_updated_at"] is not None

    # Note only: status untouched
    d = client.patch(f"/listings/{lid}/triage", json={"note": "  chiamare lunedì  "}).json()
    assert d["triage_status"] == "preferito" and d["triage_note"] == "chiamare lunedì"

    # Explicit null clears the status, note untouched
    d = client.patch(f"/listings/{lid}/triage", json={"status": None}).json()
    assert d["triage_status"] is None and d["triage_note"] == "chiamare lunedì"

    assert client.patch(f"/listings/{lid}/triage", json={"status": "boh"}).status_code == 422
    assert client.patch("/listings/999999/triage", json={"status": "scartato"}).status_code == 404


def test_mark_seen_single_and_bulk():
    cfg_id, job_id, lid = _seed_basic()
    first = client.post(f"/listings/{lid}/seen").json()["seen_at"]
    assert first is not None
    assert client.post(f"/listings/{lid}/seen").json()["seen_at"] == first  # only set once

    a = _seed_listing(cfg_id, job_id)
    b = _seed_listing(cfg_id, job_id)
    resp = client.post("/listings/seen", json={"ids": [a, b, lid]})
    assert resp.json() == {"updated": 2}  # lid was already seen
    assert _get(a).seen_at is not None and _get(b).seen_at is not None
    assert client.post("/listings/seen", json={"ids": []}).json() == {"updated": 0}

    c = _seed_listing(cfg_id, job_id)
    assert client.post("/listings/seen", json={"all": True}).json()["updated"] >= 1
    assert _get(c).seen_at is not None
    assert client.post("/listings/999999/seen").status_code == 404


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------


class _FakeLLM:
    def __init__(self, chunks, fail_after=None):
        self.chunks = chunks
        self.fail_after = fail_after
        self.messages = None

    async def astream(self, messages):
        self.messages = messages
        for i, content in enumerate(self.chunks):
            if self.fail_after is not None and i == self.fail_after:
                raise RuntimeError("boom")
            yield SimpleNamespace(content=content)


@pytest.fixture
def ai_env(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.txt"
    prefs.write_text("Bologna centro, max 1100€, balcone", encoding="utf-8")
    monkeypatch.setenv("PREFERENCES_FILE", str(prefs))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return prefs


def test_chat_streams_text_and_drops_thinking(ai_env, monkeypatch):
    raw = _rich_raw()
    _, _, lid = _seed_basic(raw=raw, title=raw["title"], ai_score=72, ai_verdict="Good match",
                            triage_note="già visto da fuori")
    fake = _FakeLLM([
        "Il ",
        [{"type": "thinking", "thinking": "SEGRETO"}, {"type": "text", "text": "balcone "}],
        [{"type": "text", "text": "non è indicato."}],
    ])
    monkeypatch.setattr(listing_chat, "_chat_llm", lambda: fake)

    resp = client.post(f"/listings/{lid}/chat", json={"messages": [
        {"role": "user", "content": "Ciao"},
        {"role": "assistant", "content": "Ciao! Come posso aiutarti?"},
        {"role": "user", "content": "Ha il balcone?"},
    ]})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    assert resp.text == "Il balcone non è indicato."
    assert "SEGRETO" not in resp.text

    system, *history = fake.messages
    assert system["role"] == "system"
    prompt = system["content"]
    assert "Bologna centro, max 1100€, balcone" in prompt          # preferences
    assert NOSADELLA_TITLE in prompt and "€ 1.200/mese" in prompt   # listing data
    assert "Arredato" in prompt                                      # features list
    assert "72/100" in prompt and "Buona zona, prezzo in linea" in prompt  # prior analysis
    assert "già visto da fuori" in prompt
    assert "italiano" in prompt
    assert [m["role"] for m in history] == ["user", "assistant", "user"]
    assert history[-1]["content"] == "Ha il balcone?"


def test_chat_events_stream_status_thinking_text_done(ai_env, monkeypatch):
    _, _, lid = _seed_basic()
    fake = _FakeLLM([
        [{"type": "thinking", "thinking": "Controllo il prezzo"}],
        [{"type": "thinking", "thinking": " e i criteri."}],
        [{"type": "text", "text": "Il prezzo "}],
        "è nel budget.",
    ])
    monkeypatch.setattr(listing_chat, "_chat_llm", lambda: fake)
    resp = client.post(f"/listings/{lid}/chat/events", json={"messages": [{"role": "user", "content": "?"}]})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/x-ndjson")
    events = [json.loads(line) for line in resp.text.splitlines() if line]
    assert [e["type"] for e in events] == ["status", "status", "thinking", "thinking", "status", "text", "text", "done"]
    assert [e["stage"] for e in events if e["type"] == "status"] == ["reading", "thinking", "writing"]
    assert "".join(e["delta"] for e in events if e["type"] == "thinking") == "Controllo il prezzo e i criteri."
    assert "".join(e["delta"] for e in events if e["type"] == "text") == "Il prezzo è nel budget."
    assert isinstance(events[-1]["thinking_ms"], int)


def test_chat_events_without_thinking_and_on_error(ai_env, monkeypatch):
    _, _, lid = _seed_basic()
    monkeypatch.setattr(listing_chat, "_chat_llm", lambda: _FakeLLM(["Subito.", "mai"], fail_after=1))
    resp = client.post(f"/listings/{lid}/chat/events", json={"messages": [{"role": "user", "content": "?"}]})
    events = [json.loads(line) for line in resp.text.splitlines() if line]
    assert [e["type"] for e in events] == ["status", "status", "text", "error"]
    assert events[-1]["message"] == "boom"


def test_with_thinking_summaries_only_on_adaptive_models(monkeypatch):
    from langchain_anthropic import ChatAnthropic
    sonnet = listing_chat.with_thinking_summaries(ChatAnthropic(api_key="x", model="claude-sonnet-5-5"))
    assert sonnet.thinking == {"type": "adaptive", "display": "summarized"}
    haiku = listing_chat.with_thinking_summaries(ChatAnthropic(api_key="x", model="claude-haiku-4-5-20251001"))
    assert not haiku.thinking
    deep = listing_chat.with_thinking_summaries(
        ChatAnthropic(api_key="x", model="claude-sonnet-5-5", reasoning_effort="low"), effort="high"
    )
    assert deep.reasoning_effort == "high"


def test_chat_events_rejects_unknown_effort(ai_env):
    _, _, lid = _seed_basic()
    body = {"messages": [{"role": "user", "content": "?"}], "effort": "extreme"}
    assert client.post(f"/listings/{lid}/chat/events", json=body).status_code == 422


def test_chat_without_preferences_file(ai_env, monkeypatch, tmp_path):
    monkeypatch.setenv("PREFERENCES_FILE", str(tmp_path / "missing.txt"))
    _, _, lid = _seed_basic()
    fake = _FakeLLM(["ok"])
    monkeypatch.setattr(listing_chat, "_chat_llm", lambda: fake)
    resp = client.post(f"/listings/{lid}/chat", json={"messages": [{"role": "user", "content": "?"}]})
    assert resp.text == "ok"
    assert "nessuna preferenza fornita" in fake.messages[0]["content"]


def test_chat_error_mid_stream(ai_env, monkeypatch):
    _, _, lid = _seed_basic()
    monkeypatch.setattr(listing_chat, "_chat_llm", lambda: _FakeLLM(["Parziale", "mai"], fail_after=1))
    resp = client.post(f"/listings/{lid}/chat", json={"messages": [{"role": "user", "content": "?"}]})
    assert resp.status_code == 200
    assert resp.text == "Parziale\n\n[[ERRORE]] boom"


def test_chat_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _, _, lid = _seed_basic()
    resp = client.post(f"/listings/{lid}/chat", json={"messages": [{"role": "user", "content": "?"}]})
    assert resp.status_code == 503
    assert resp.json() == {"detail": "Nessuna chiave API AI configurata"}


def test_chat_validation(ai_env):
    _, _, lid = _seed_basic()
    last_assistant = {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]}
    assert client.post(f"/listings/{lid}/chat", json=last_assistant).status_code == 422
    assert client.post(f"/listings/{lid}/chat", json={"messages": []}).status_code == 422
    bad_role = {"messages": [{"role": "system", "content": "x"}]}
    assert client.post(f"/listings/{lid}/chat", json=bad_role).status_code == 422
    ok = {"messages": [{"role": "user", "content": "x"}]}
    assert client.post("/listings/999999/chat", json=ok).status_code == 404


# ---------------------------------------------------------------------------
# Rescore
# ---------------------------------------------------------------------------


def _fake_analyse(calls: list):
    async def fake(listings, preferences):
        calls.append((len(listings), preferences))
        for lst in listings:
            failed = "fail" in lst.get("title", "")
            score, verdict = (0, "Error") if failed else (81, "Strong match")
            lst["notion_fields"] = {"ai_score": score, "ai_verdict": verdict, "ai_reason": "motivo",
                                    "notes": "nota", "energy_class": "B"}
            lst.update(ai_score=score, ai_verdict=verdict, ai_reason="motivo")
        return {"tokens_used": 1000, "cost_usd": 0.001}
    return fake


def test_rescore_single(ai_env, monkeypatch):
    calls = []
    monkeypatch.setattr("apt_scrape.analysis.analyse_listings", _fake_analyse(calls))
    _, _, lid = _seed_basic(raw={"title": "Bilocale"}, title="Bilocale", ai_score=0, ai_verdict="Error")

    resp = client.post(f"/listings/{lid}/rescore")
    assert resp.status_code == 200
    d = resp.json()
    assert d["ai_score"] == 81 and d["ai_verdict"] == "Strong match" and d["ai_status"] == "ok"
    assert d["ai_reason"] == "motivo" and d["ai_notes"] == "nota" and d["energy_class"] == "B"
    assert calls == [(1, "Bologna centro, max 1100€, balcone")]
    stored = json.loads(_get(lid).raw_json)
    assert stored["notion_fields"]["ai_verdict"] == "Strong match"
    assert client.post("/listings/999999/rescore").status_code == 404


def test_rescore_bulk_counts_errors(ai_env, monkeypatch):
    calls = []
    monkeypatch.setattr("apt_scrape.analysis.analyse_listings", _fake_analyse(calls))
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    good = _seed_listing(cfg_id, job_id, raw={"title": "ok"}, title="ok")
    bad = _seed_listing(cfg_id, job_id, raw={}, title="will fail")  # title filled from the row

    resp = client.post("/listings/rescore", json={"ids": [good, bad, 999999]})
    assert resp.json() == {"updated": 2, "errors": 1}
    assert len(calls) == 1 and calls[0][0] == 2  # one analyse_listings call for the batch
    assert _get(good).ai_score == 81
    assert _get(bad).ai_verdict == "Error"
    assert client.post("/listings/rescore", json={"ids": []}).json() == {"updated": 0, "errors": 0}


def test_rescore_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    _, _, lid = _seed_basic()
    assert client.post(f"/listings/{lid}/rescore").status_code == 503
    assert client.post("/listings/rescore", json={"ids": [lid]}).status_code == 503


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------


def test_build_queries_strips_typology_and_appends_city():
    assert geocoding.build_queries(NOSADELLA_TITLE, "bologna") == [
        "via Nosadella 34, Saragozza dentro le Mura, Bologna, Italia",
        "via Nosadella 34, Bologna, Italia",
        "Saragozza dentro le Mura, Bologna, Italia",
    ]
    assert geocoding.build_queries("Appartamento in affitto in via Roma 1", "milano") == [
        "via Roma 1, Milano, Italia",
    ]
    # Never fall back to the bare city centre
    assert geocoding.build_queries("Irnerio, Bologna", "bologna") == ["Irnerio, Bologna, Italia"]
    assert geocoding.strip_typology("Villaggio Breda 3") == "Villaggio Breda 3"
    assert geocoding.strip_typology("Casa indipendente via Po 2") == "via Po 2"
    assert geocoding.build_queries("Bilocale", "bologna") == []


async def test_geocode_background_task(monkeypatch):
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    nosadella = _seed_listing(cfg_id, job_id, raw={"address": NOSADELLA_TITLE}, title=NOSADELLA_TITLE,
                              city="bologna")
    unknown = _seed_listing(cfg_id, job_id, raw={"detail_address": "Via Inesistente 999"},
                            title="Trilocale", city="bologna")

    calls: list[str] = []
    sleeps: list[float] = []
    release = asyncio.Event()

    async def fake_geocode(query):
        calls.append(query)
        await release.wait()
        if query == "via Nosadella 34, Bologna, Italia":
            return (44.49, 11.33)
        return None

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(geocoding, "_geocode", fake_geocode)
    monkeypatch.setattr(geocoding, "_sleep", fake_sleep)

    async with _async_client() as ac:
        first = (await ac.post("/listings/geocode")).json()
        assert first["running"] is True
        task = geocoding.current_task()
        second = (await ac.post("/listings/geocode")).json()  # already running: no new task
        assert second["running"] is True and geocoding.current_task() is task

        release.set()
        await asyncio.wait_for(task, timeout=5)
        status = (await ac.get("/listings/geocode/status")).json()

    assert status["running"] is False
    assert set(status) == {"running", "pending", "done", "failed"}
    assert status["done"] >= 1 and status["failed"] >= 1

    ok = _get(nosadella)
    assert (ok.lat, ok.lon, ok.geocode_status) == (44.49, 11.33, "ok")
    failed = _get(unknown)
    assert failed.lat is None and failed.geocode_status == "failed"
    assert not any(q.lower().startswith("bilocale") for q in calls)  # typology stripped
    assert calls.index("via Nosadella 34, Bologna, Italia") == calls.index(
        "via Nosadella 34, Saragozza dentro le Mura, Bologna, Italia") + 1  # fallback after full address
    assert len(sleeps) == len(calls) - 1 and all(s >= 1.1 for s in sleeps)  # 1 req/s policy

    # A normal run leaves "failed" alone; retry_failed=true retries it
    calls.clear()
    geocoding.start()
    await geocoding.current_task()
    assert "Via Inesistente 999, Bologna, Italia" not in calls

    async def found_now(query):
        calls.append(query)
        return (45.0, 9.0)

    monkeypatch.setattr(geocoding, "_geocode", found_now)
    async with _async_client() as ac:
        await ac.post("/listings/geocode?retry_failed=true")
        await geocoding.current_task()
    retried = _get(unknown)
    assert (retried.lat, retried.geocode_status) == (45.0, "ok")


async def test_geocode_transient_errors_leave_listing_pending(monkeypatch):
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    lid = _seed_listing(cfg_id, job_id, raw={"address": "Via Zamboni 1, Bologna"}, city="bologna")

    async def offline(query):
        raise httpx.ConnectError("offline")

    async def no_sleep(seconds):
        pass

    monkeypatch.setattr(geocoding, "_geocode", offline)
    monkeypatch.setattr(geocoding, "_sleep", no_sleep)
    await geocoding.run_geocoding()
    lst = _get(lid)
    assert lst.lat is None and lst.geocode_status is None


# ---------------------------------------------------------------------------
# Jobs: config_name + SSE stream
# ---------------------------------------------------------------------------


def test_jobs_list_includes_config_name():
    cfg_id = _seed_config(name="Bologna centro")
    job_id = _seed_job(cfg_id)
    by_id = {j["id"]: j for j in client.get("/jobs").json()}
    assert by_id[job_id]["config_name"] == "Bologna centro"


def test_job_stream_finished_job_emits_log_and_end():
    cfg_id = _seed_config()
    log = "[10:00:00] line1\n[10:00:01] line2\n"
    job_id = _seed_job(cfg_id, status="done", log=log, listing_count=3, scraped_count=4,
                       finished_at=datetime(2026, 10, 4, 10, 0, 2))
    resp = client.get(f"/jobs/{job_id}/stream")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"

    events = _parse_sse(resp.text)
    assert [e for e, _ in events] == ["log", "status", "end"]
    assert events[0][1] == {"offset": len(log), "chunk": log}
    assert events[1][1]["status"] == "done" and events[1][1]["listing_count"] == 3
    assert events[2][1] == events[1][1]
    assert events[2][1]["finished_at"] == "2026-10-04T10:00:02"

    # Resume from an offset: only the tail is sent
    resumed = _parse_sse(client.get(f"/jobs/{job_id}/stream?offset={len('[10:00:00] line1')+1}").text)
    assert resumed[0] == ("log", {"offset": len(log), "chunk": "[10:00:01] line2\n"})
    assert client.get("/jobs/999999/stream").status_code == 404


async def test_job_stream_follows_running_job(monkeypatch):
    monkeypatch.setattr(jobs_router, "STREAM_POLL_SEC", 0.01)
    monkeypatch.setattr(jobs_router, "STREAM_PING_SEC", 0.0)
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id, status="running", log="a\n")

    async def progress():
        await asyncio.sleep(0.05)
        with Session(engine) as s:
            job = s.get(Job, job_id)
            job.log += "b\n"
            s.add(job)
            s.commit()
        await asyncio.sleep(0.05)
        with Session(engine) as s:
            job = s.get(Job, job_id)
            job.log += "c\n"
            job.status = "done"
            job.listing_count = 2
            job.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            s.add(job)
            s.commit()

    async with _async_client() as ac:
        updater = asyncio.create_task(progress())
        resp = await asyncio.wait_for(ac.get(f"/jobs/{job_id}/stream"), timeout=5)
        await updater

    events = _parse_sse(resp.text)
    logs = [data for name, data in events if name == "log"]
    assert "".join(d["chunk"] for d in logs) == "a\nb\nc\n"
    assert logs[-1]["offset"] == len("a\nb\nc\n")
    statuses = [data["status"] for name, data in events if name == "status"]
    assert statuses[0] == "running" and statuses[-1] == "done"
    assert ("comment", ": ping") in events
    assert events[-1][0] == "end" and events[-1][1]["listing_count"] == 2


# ---------------------------------------------------------------------------
# Configs: next_run_at / last_job / listing_count
# ---------------------------------------------------------------------------


def test_config_response_includes_run_info():
    resp = client.post("/configs", json={"name": "Run info", "city": "bologna", "schedule_days": ["mon"]})
    assert resp.status_code == 201
    created = resp.json()
    assert created["next_run_at"] is None  # scheduler not running in tests
    assert created["last_job"] is None and created["listing_count"] == 0

    cfg_id = created["id"]
    _seed_job(cfg_id, status="done", listing_count=1)
    latest = _seed_job(cfg_id, status="running")
    _seed_listing(cfg_id, latest)
    _seed_listing(cfg_id, latest)

    d = client.get(f"/configs/{cfg_id}").json()
    assert d["last_job"]["id"] == latest and d["last_job"]["status"] == "running"
    assert set(d["last_job"]) == {"id", "status", "started_at", "finished_at", "listing_count"}
    assert d["listing_count"] == 2
    listed = {c["id"]: c for c in client.get("/configs").json()}[cfg_id]
    assert listed["last_job"]["id"] == latest and listed["listing_count"] == 2
    assert "next_run_at" in listed


async def test_config_next_run_at_from_scheduler(monkeypatch):
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    import backend.scheduler as sched

    fresh = AsyncIOScheduler(timezone="UTC")
    monkeypatch.setattr(sched, "_scheduler", fresh)
    cfg_id = _seed_config(name="Scheduled", schedule_days='["mon","thu"]')
    fresh.start()
    try:
        sched.reload_config(cfg_id)
        assert sched.next_run_time(cfg_id) is not None
        assert sched.next_run_time(999999) is None
        async with _async_client() as ac:
            d = (await ac.get(f"/configs/{cfg_id}")).json()
    finally:
        fresh.shutdown(wait=False)
    next_run = datetime.fromisoformat(d["next_run_at"])
    assert next_run > datetime.now(timezone.utc)
    assert next_run.strftime("%H:%M") == "08:00"


# ---------------------------------------------------------------------------
# /api aliases, CORS, SPA serving
# ---------------------------------------------------------------------------


def test_api_prefix_aliases(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFERENCES_FILE", str(tmp_path / "prefs.txt"))
    assert client.get("/api/health").json() == {"status": "ok"}
    for path in ("/api/configs", "/api/jobs", "/api/listings", "/api/sites", "/api/preferences",
                 "/api/jobs/stats/overall", "/api/listings/geocode/status"):
        assert client.get(path).status_code == 200, path
    _, _, lid = _seed_basic()
    assert client.get(f"/api/listings/{lid}").json()["id"] == lid
    # Hidden from the OpenAPI schema, root routes still documented
    paths = client.get("/openapi.json").json()["paths"]
    assert "/configs" in paths and not any(p.startswith("/api/") for p in paths)


def test_cors_allows_vite_dev_server():
    resp = client.options("/api/listings", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "PATCH",
    })
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "http://localhost:5173"
    other = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_spa_served_from_web_dist_dir(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app-123.js").write_text("console.log('spa')", encoding="utf-8")
    (dist / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    monkeypatch.setenv("WEB_DIST_DIR", str(dist))
    spa = TestClient(create_app())

    for path in ("/", "/annunci", "/annunci/42", "/mappa?x=1"):
        resp = spa.get(path)
        assert resp.status_code == 200 and "id=root" in resp.text, path
        assert resp.headers["cache-control"] == "no-cache"
    assert spa.get("/assets/app-123.js").text == "console.log('spa')"
    assert spa.get("/favicon.svg").text == "<svg/>"
    assert spa.get("/assets/missing.js").status_code == 404
    assert "nope" not in spa.get("/..%2Fsecret.txt").text

    # API routes are never shadowed by the catch-all
    assert spa.get("/api/health").json() == {"status": "ok"}
    assert isinstance(spa.get("/configs").json(), list)
    assert isinstance(spa.get("/api/configs").json(), list)
    assert spa.get("/api/nope").status_code == 404
    assert spa.get("/listings/1/nope").status_code == 404


def test_no_spa_without_dist(monkeypatch, tmp_path):
    monkeypatch.setenv("WEB_DIST_DIR", str(tmp_path / "missing"))
    plain = TestClient(create_app())
    assert plain.get("/").status_code == 404
    assert plain.get("/health").json() == {"status": "ok"}
