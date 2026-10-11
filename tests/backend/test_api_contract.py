# tests/backend/test_api_contract.py — API side of the scrape/enrichment audit fixes:
# detail status, scraped facts, rescore merge/failure rules, lean jobs list and stats,
# config validation, price parsing and the shared preferences file.
import json
import os
import uuid

os.environ["DB_PATH"] = ":memory:"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func
from sqlmodel import Session, select

from backend.db import Job, Listing, SearchConfig, create_db_and_tables, engine
from backend.main import app
from backend.parsing import (
    detail_status_of, parse_price, parse_sqm, scraped_bathrooms, scraped_floor, scraped_furnished,
)

create_db_and_tables()
client = TestClient(app)


def _seed_config() -> int:
    with Session(engine) as s:
        cfg = SearchConfig(name="Contract", city="bologna", schedule_days="[]", schedule_time="08:00")
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


def _seed_listing(config_id: int, job_id: int, raw: dict, **cols) -> int:
    url = f"https://example.com/contract/{uuid.uuid4().hex}"
    with Session(engine) as s:
        lst = Listing(url=url, job_id=job_id, config_id=config_id,
                      raw_json=json.dumps({"url": url, **raw}), **cols)
        s.add(lst)
        s.commit()
        s.refresh(lst)
        return lst.id


def _get(listing_id: int) -> Listing:
    with Session(engine) as s:
        return s.get(Listing, listing_id)


# Search-card only, blank legacy detail (the shape of the 57 rows hit by DataDome)
def _card_only_raw() -> dict:
    return {
        "title": "Bilocale via Saragozza 10, Bologna",
        "price": "€ 950/mese",
        "bathrooms": "1 bagno",
        "description_snippet": "Bilocale luminoso",
        "raw_features": ["2 locali", "55 m²", "1 bagno", "Piano T", "Arredato", "Balcone"],
        "detail": {"source": "Immobiliare.it", "url": "x", "title": "", "description": "",
                   "extra_info": {}, "floor": ""},
        "notion_fields": {"floor": "attico", "furnished": False, "available_from": None},
    }


# Enriched row with the portal feature table
def _enriched_raw() -> dict:
    features = {"Contratto": "Affitto", "Piano": "Piano rialzato", "Bagni": "2",
                "Arredato": "Sì", "Riscaldamento": "Autonomo", "Disponibilità": "Libero"}
    return {
        "title": "Trilocale via Massarenti 352",
        "price": "€ 1.200/mese",
        "raw_features": ["3 locali", "Piano 3", "Parzialmente Arredato"],
        "detail": {"title": "Trilocale via Massarenti 352", "description": "Ampio trilocale",
                   "floor": "rialzato", "extra_info": features},
        "detail_features": features,
        "detail_status": "ok",
    }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("€ 1.200/mese", 1200.0),
    ("1.200", 1200.0),
    ("1.200,50 €", 1200.5),
    ("1,200", 1200.0),
    ("€ 1,200", 1200.0),
    ("1,200.50 €", 1200.5),
    ("€ 850/mese", 850.0),
    ("da 900 €/mese", 900.0),
    ("€ 800 - 1.000/mese", 800.0),
    ("€ 12,50", 12.5),
    ("€ 12.50", 12.5),
    ("Prezzo su richiesta", None),
    ("", None),
])
def test_parse_price_formats(text, expected):
    assert parse_price(text) == expected


def test_parse_sqm_shares_separator_rules():
    assert parse_sqm("1.250 m²") == 1250.0
    assert parse_sqm("45,5 m²") == 45.5


def test_detail_status_stored_and_legacy():
    assert detail_status_of({"detail_status": "blocked"}) == "blocked"
    assert detail_status_of({"detail_status": "skipped"}) == "missing"
    assert detail_status_of({}) == "missing"
    assert detail_status_of({"detail": {"source": "x", "title": "", "description": ""}}) == "empty"
    assert detail_status_of({"detail": {"title": "Bilocale"}}) == "ok"
    assert detail_status_of({"detail": {"extra_info": {"Piano": "3"}}}) == "ok"


def test_scraped_floor_order_and_abbreviations():
    assert scraped_floor({"raw_features": ["Piano T"]}) == "Piano terra"
    assert scraped_floor({"raw_features": ["Piano S, R"]}) == "Seminterrato, piano rialzato"
    assert scraped_floor({"raw_features": ["Piano T, 1"]}) == "Piano terra, 1"
    assert scraped_floor({"raw_features": ["Piano 3"]}) == "3"
    # feature table, then detail.floor, then the card token
    assert scraped_floor(_enriched_raw()) == "Piano rialzato"
    assert scraped_floor({"detail": {"floor": "2"}, "raw_features": ["Piano 4"]}) == "2"
    assert scraped_floor({"raw_features": ["Balcone"]}) is None


def test_scraped_furnished_exact_tokens_only():
    assert scraped_furnished({"raw_features": ["Arredato"]}) is True
    assert scraped_furnished({"raw_features": ["Non Arredato"]}) is False
    assert scraped_furnished({"raw_features": ["Parzialmente Arredato"]}) is None
    assert scraped_furnished({"raw_features": ["Solo Cucina Arredata"]}) is None
    assert scraped_furnished({"raw_features": ["Balcone"]}) is None  # no token is not a no
    assert scraped_furnished({"detail_features": {"Arredato": "Sì"}}) is True
    assert scraped_furnished({"detail_features": {"Arredato": "No"}, "raw_features": ["Arredato"]}) is False
    assert scraped_furnished({"detail_features": {"Arredato": None}, "raw_features": ["Arredato"]}) is True


def test_scraped_bathrooms():
    assert scraped_bathrooms({"bathrooms": "1 bagno"}) == "1 bagno"
    assert scraped_bathrooms({"detail_features": {"Bagni": "2"}}) == "2 bagni"
    assert scraped_bathrooms({}) is None


# ---------------------------------------------------------------------------
# Listing summary
# ---------------------------------------------------------------------------


def test_summary_card_only_row_uses_scraped_facts():
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    lid = _seed_listing(cfg_id, job_id, _card_only_raw(), price="€ 950/mese")
    d = client.get(f"/listings/{lid}").json()

    assert d["detail_status"] == "empty" and d["detail_error"] is None
    assert d["floor"] == "Piano terra"        # card token beats the AI's guess ('attico')
    assert d["furnished"] is True             # card 'Arredato' beats the AI's False
    assert d["bathrooms"] == "1 bagno"
    assert d["facts"] == []
    assert d["description_snippet"] == "Bilocale luminoso"
    assert d["first_seen_at"] == d["scraped_at"]
    assert d["last_job_id"] == job_id and d["last_seen_at"] is not None


def test_summary_enriched_row_exposes_portal_facts():
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    lid = _seed_listing(cfg_id, job_id, _enriched_raw())
    [d] = client.get(f"/listings?config_id={cfg_id}").json()

    assert d["id"] == lid
    assert d["detail_status"] == "ok"
    assert {"label": "Riscaldamento", "value": "Autonomo"} in d["facts"]
    assert {"label": "Contratto", "value": "Affitto"} in d["facts"]
    assert d["bathrooms"] == "2 bagni"
    assert d["floor"] == "Piano rialzato"
    assert d["furnished"] is True             # feature table 'Sì' beats the partial card token
    assert d["available_from"] == "Libero"    # no AI value -> the portal's availability line


def test_summary_blocked_detail_reports_status_and_error():
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    raw = {**_card_only_raw(), "detail_status": "blocked", "detail_error": "DataDome challenge page"}
    raw.pop("detail")
    lid = _seed_listing(cfg_id, job_id, raw)
    d = client.get(f"/listings/{lid}").json()
    assert d["detail_status"] == "blocked"
    assert d["detail_error"] == "DataDome challenge page"


def test_listings_rejects_negative_limit_and_offset():
    assert client.get("/listings?limit=-1").status_code == 422
    assert client.get("/listings?limit=0").status_code == 422
    assert client.get("/listings?offset=-1").status_code == 422
    assert client.get("/listings?limit=2001").status_code == 422


# ---------------------------------------------------------------------------
# Rescore
# ---------------------------------------------------------------------------


@pytest.fixture
def ai_env(monkeypatch, tmp_path):
    prefs = tmp_path / "prefs.txt"
    prefs.write_text("Bologna, max 1100€", encoding="utf-8")
    monkeypatch.setenv("PREFERENCES_FILE", str(prefs))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return prefs


def _fake_analyse(seen: list, fail: bool = False, during=None):
    """analyse_listings double following the C4 contract (error marker + ai_error on failure)."""
    async def fake(listings, preferences):
        if during:
            during()
        for lst in listings:
            seen.append(dict(lst))
            if fail:
                lst.update(ai_error="429 rate limited", ai_verdict="Error", ai_score=0,
                           ai_reason="429 rate limited")
            else:
                lst.pop("ai_error", None)
                lst["notion_fields"] = {"ai_score": 77, "ai_verdict": "Good match", "notes": "nota"}
                lst.update(ai_score=77, ai_stars="⭐⭐⭐⭐", ai_verdict="Good match", ai_reason="motivo",
                           ai_notes="nota")
        return {"tokens_used": 0, "cost_usd": 0.0, "scored": 0 if fail else len(listings),
                "failed": len(listings) if fail else 0}
    return fake


def _scored_raw() -> dict:
    return {**_card_only_raw(), "notion_fields": {"ai_score": 64, "ai_verdict": "Good match"},
            "ai_score": 64, "ai_verdict": "Good match", "ai_reason": "valutazione buona"}


def test_failed_rescore_keeps_valid_analysis(ai_env, monkeypatch):
    monkeypatch.setattr("apt_scrape.analysis.analyse_listings", _fake_analyse([], fail=True))
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    lid = _seed_listing(cfg_id, job_id, _scored_raw(), ai_score=64, ai_verdict="Good match")
    before = _get(lid).raw_json

    resp = client.post(f"/listings/{lid}/rescore")
    assert resp.status_code == 502
    assert "429" in resp.json()["detail"]
    after = _get(lid)
    assert (after.ai_score, after.ai_verdict, after.raw_json) == (64, "Good match", before)

    # bulk: counted as an error, row still untouched
    assert client.post("/listings/rescore", json={"ids": [lid]}).json() == {"updated": 1, "errors": 1}
    assert _get(lid).raw_json == before


def test_failed_rescore_marks_unscored_row_as_error(ai_env, monkeypatch):
    monkeypatch.setattr("apt_scrape.analysis.analyse_listings", _fake_analyse([], fail=True))
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    lid = _seed_listing(cfg_id, job_id, _card_only_raw())

    resp = client.post(f"/listings/{lid}/rescore")
    assert resp.status_code == 200
    d = resp.json()
    assert d["ai_status"] == "error" and d["ai_reason"] == "429 rate limited"
    assert json.loads(_get(lid).raw_json)["ai_error"] == "429 rate limited"


def test_rescore_merges_ai_keys_into_fresh_row(ai_env, monkeypatch):
    """A run upsert landing during the LLM await must survive the rescore write-back."""
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    lid = _seed_listing(cfg_id, job_id, {**_scored_raw(), "ai_error": "old failure"},
                        ai_score=64, ai_verdict="Good match")

    def runner_upsert():
        with Session(engine) as s:
            row = s.get(Listing, lid)
            raw = json.loads(row.raw_json)
            raw.update(detail={"title": "Nuovo dettaglio", "description": "Testo"}, detail_status="ok")
            row.raw_json = json.dumps(raw)
            row.price = "€ 900/mese"
            s.add(row)
            s.commit()

    seen: list = []
    monkeypatch.setattr("apt_scrape.analysis.analyse_listings", _fake_analyse(seen, during=runner_upsert))
    resp = client.post(f"/listings/{lid}/rescore")
    assert resp.status_code == 200
    assert resp.json()["ai_score"] == 77 and resp.json()["detail_status"] == "ok"

    row = _get(lid)
    stored = json.loads(row.raw_json)
    assert row.price == "€ 900/mese"
    assert stored["detail"]["title"] == "Nuovo dettaglio"          # runner's data kept
    assert stored["ai_score"] == 77 and stored["ai_notes"] == "nota"
    assert "ai_error" not in stored                                 # success clears the old failure
    # the LLM got the stored listing (card data included), not a stripped-down copy
    assert seen[0]["description_snippet"] == "Bilocale luminoso"
    assert seen[0]["raw_features"][3] == "Piano T"


def test_rescore_whole_batch_failure_is_502_and_touches_nothing(ai_env, monkeypatch):
    async def boom(listings, preferences):
        raise RuntimeError("model init failed")
    monkeypatch.setattr("apt_scrape.analysis.analyse_listings", boom)
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id)
    lid = _seed_listing(cfg_id, job_id, _scored_raw(), ai_score=64, ai_verdict="Good match")
    before = _get(lid).raw_json
    assert client.post("/listings/rescore", json={"ids": [lid]}).status_code == 502
    assert _get(lid).raw_json == before


# ---------------------------------------------------------------------------
# Jobs list and stats
# ---------------------------------------------------------------------------


def test_jobs_list_omits_log_unless_asked():
    cfg_id = _seed_config()
    job_id = _seed_job(cfg_id, log="[10:00:00] riga\n" * 100)

    [row] = [j for j in client.get(f"/jobs?config_id={cfg_id}").json() if j["id"] == job_id]
    assert "log" not in row
    assert row["config_name"] == "Contract" and row["status"] == "done"

    [full] = [j for j in client.get(f"/jobs?config_id={cfg_id}&include_log=1").json() if j["id"] == job_id]
    assert full["log"].startswith("[10:00:00] riga")
    assert client.get(f"/jobs/{job_id}").json()["log"] == full["log"]


def test_overall_stats_counts_unique_listings():
    cfg_id = _seed_config()
    first = _seed_job(cfg_id, listing_count=2)
    _seed_job(cfg_id, listing_count=2)  # second run re-saw the same two listings
    _seed_listing(cfg_id, first, {}, price="€ 1.000/mese", area="centro")
    _seed_listing(cfg_id, first, {}, price="€ 800/mese", area="centro")

    with Session(engine) as s:
        n_listings = s.exec(select(func.count(Listing.id))).one()
        processed = sum(j.listing_count or 0 for j in s.exec(select(Job).where(Job.status == "done")).all())
    stats = client.get("/jobs/stats/overall").json()
    assert stats["total_listings"] == n_listings
    assert stats["total_processed"] == processed
    assert stats["area_distribution"]["centro"] >= 2

    per_run = client.get(f"/jobs/{first}/stats").json()
    assert per_run["avg_price_eur"] == 900.0


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("patch", [
    {"schedule_time": "08:00:00"},
    {"schedule_time": "25:00"},
    {"schedule_time": "8:00"},
    {"schedule_days": ["monday"]},
    {"detail_concurrency": 0},
    {"vpn_rotate_batches": 0},
    {"start_page": 3, "end_page": 2},
    {"start_page": 0},
])
def test_config_rejects_invalid_values(patch):
    name = f"invalid-{uuid.uuid4().hex}"
    resp = client.post("/configs", json={"name": name, "city": "bologna", **patch})
    assert resp.status_code == 422
    with Session(engine) as s:
        assert s.exec(select(SearchConfig).where(SearchConfig.name == name)).first() is None


def test_config_normalises_schedule_days():
    resp = client.post("/configs", json={"name": "days", "city": "bologna", "schedule_days": ["Mon", "mon", " wed "]})
    assert resp.status_code == 201
    cfg = resp.json()
    assert cfg["schedule_days"] == ["mon", "wed"]
    bad = client.put(f"/configs/{cfg['id']}", json={"name": "days", "city": "bologna", "end_page": 0})
    assert bad.status_code == 422
    client.delete(f"/configs/{cfg['id']}")


# ---------------------------------------------------------------------------
# Preferences file
# ---------------------------------------------------------------------------


def test_preferences_router_and_scorer_share_default_file(monkeypatch, tmp_path):
    from apt_scrape import analysis

    monkeypatch.delenv("PREFERENCES_FILE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert client.put("/preferences", json={"content": "Solo Bologna centro"}).status_code == 200
    assert analysis.load_preferences() == "Solo Bologna centro"


# --- integration (cross-owner) -----------------------------------------------


def test_summary_cleans_glued_agency_label():
    cid = _seed_config()
    jid = _seed_job(cid)
    lid = _seed_listing(cid, jid, {"detail_agency": "AgenziaBologna ImmobiliareMostra Telefono"})
    d = client.get(f"/api/listings/{lid}").json()
    assert d["agency"] == "Bologna Immobiliare"
    assert d["raw"]["detail_agency"] == "AgenziaBologna ImmobiliareMostra Telefono"  # stored as scraped


def test_run_now_refuses_a_search_already_running(monkeypatch):
    from backend import scheduler

    cid = _seed_config()
    monkeypatch.setitem(scheduler._active, cid, (4242, None))
    started = []
    monkeypatch.setattr(scheduler, "trigger_now", lambda config_id: started.append(config_id) or 1)
    resp = client.post(f"/api/configs/{cid}/run")
    assert resp.status_code == 409 and "#4242" in resp.json()["detail"]
    assert started == []
