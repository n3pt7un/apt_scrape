"""Runner + real enrichment + merge-upsert, end to end without network (contracts C2, C5).

Unlike test_runner_persistence.py, enrich_with_details is NOT mocked: a fake
browser serves the saved detail page or raises BlockedError, and the real
Immobiliare parser reads it. Also covers the listing-table migration and the
SQLite journal mode on a file database (in a subprocess, as backend.db binds
its engine at import).
"""
import os
os.environ["DB_PATH"] = ":memory:"

import asyncio
import json
import sqlite3
import subprocess
import sys
import textwrap
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, select

import backend.runner as runner
from apt_scrape.server import BlockedError
from apt_scrape.sites import get_adapter_with_overrides
from backend.db import Job, Listing, SearchConfig, create_db_and_tables, engine
from backend.parsing import detail_status_of
from backend.routers.listings import listing_summary

create_db_and_tables()

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
DETAIL_HTML = (FIXTURES / "immobiliare_detail_403.html").read_text(encoding="utf-8")
FIRST_SEEN = datetime(2026, 10, 2, 9, 30, 0)

GOOD_LEGACY_DETAIL = {"title": "Bilocale via Mascarella 7", "description": "Bilocale ristrutturato, arredato.",
                      "extra_info": {"Arredato": "Sì"}, "photos": ["https://pwm.im-cdn.it/a/r.jpg"]}
BLANK_LEGACY_DETAIL = {"source": "Immobiliare.it", "title": "", "price": "", "description": "", "address": "",
                       "extra_info": {}, "photos": [], "costs": {}}


def _url(tag: str) -> str:
    return f"https://www.immobiliare.it/annunci/flow-{tag}/"


def _config(**kw) -> int:
    with Session(engine) as s:
        cfg = SearchConfig(**{
            "name": "Flow", "city": "bologna", "operation": "affitto", "property_type": "appartamenti",
            "start_page": 1, "end_page": 1, "schedule_days": "[]", "schedule_time": "08:00",
            "detail_concurrency": 1, "vpn_rotate_batches": 3, "auto_analyse": True,
            "auto_notion_push": False, "request_delay_sec": 0.0, **kw,
        })
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def _seed(config_id: int, url: str, raw: dict, *, score=64, verdict="Good match", price="€ 900/mese") -> int:
    """A row stored by an earlier run (job_id/scraped_at = when it was first found)."""
    with Session(engine) as s:
        job = Job(config_id=config_id, status="done", triggered_by="manual")
        s.add(job)
        s.commit()
        s.refresh(job)
        stored = {"url": url, "title": "Bilocale", "price": price, "ai_score": score, "ai_verdict": verdict,
                  "ai_reason": "valutazione precedente", "notion_fields": {"address": "Via Mascarella 7"}, **raw}
        s.add(Listing(url=url, job_id=job.id, config_id=config_id, title="Bilocale", price=price,
                      ai_score=score, ai_verdict=verdict, raw_json=json.dumps(stored),
                      scraped_at=FIRST_SEEN, last_seen_at=FIRST_SEEN, last_job_id=job.id,
                      triage_status="preferito", lat=44.5, lon=11.3, geocode_status="ok"))
        s.commit()
        return job.id


class _Card:
    def __init__(self, url: str, price: str = "€ 900/mese"):
        self.url = url
        self._data = {"url": url, "title": "Bilocale", "price": price, "sqm": "50 m²", "rooms": "2 locali",
                      "bathrooms": "1 bagno", "description_snippet": "Bilocale arredato vicino al centro",
                      "raw_features": ["2 locali", "Arredato"], "post_date": ""}

    def to_dict(self) -> dict:
        return dict(self._data)


def _run(config_id: int, cards: list[_Card], detail, analyse=None):
    """Run the job. *detail(url)* is the detail page HTML or an exception instance to raise."""
    adapter = get_adapter_with_overrides("immobiliare", {"page_load_wait": "domcontentloaded"})
    adapter.build_search_url = lambda filters: f"https://www.immobiliare.it/search/?pag={filters.page}"
    adapter.parse_search = lambda html: list(cards)

    async def fetch_detail(url, **kwargs):
        await asyncio.sleep(0)
        result = detail(url)
        if isinstance(result, BaseException):
            raise result
        return result

    analyse = analyse or AsyncMock(return_value={"tokens_used": 0, "cost_usd": 0.0, "scored": 0, "failed": 0})
    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides", return_value=adapter),
        patch("apt_scrape.analysis.load_preferences", return_value="prefs"),
        patch("apt_scrape.analysis.analyse_listings", new=analyse),
    ):
        mock_browser.fetch_page = AsyncMock(return_value="<html>search page</html>")
        mock_browser.fetch_page_parallel = AsyncMock(side_effect=fetch_detail)
        mock_browser.rotate_proxy = AsyncMock()
        job_id = asyncio.run(runner.run_config_job(config_id, lambda m: None))
        return job_id, mock_browser.fetch_page_parallel, analyse


def _row(url: str) -> Listing:
    with Session(engine) as s:
        return s.exec(select(Listing).where(Listing.url == url)).one()


def _job(job_id: int) -> Job:
    with Session(engine) as s:
        return s.get(Job, job_id)


def test_legacy_row_with_readable_detail_is_reused_not_refetched_or_rescored():
    cid = _config()
    url = _url("legacy-good")
    first_job = _seed(cid, url, {"detail": GOOD_LEGACY_DETAIL, "detail_description": GOOD_LEGACY_DETAIL["description"]})

    job_id, fetch, analyse = _run(cid, [_Card(url)], detail=lambda u: BlockedError(u))

    fetch.assert_not_awaited()
    analyse.assert_not_awaited()
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert raw["detail"] == GOOD_LEGACY_DETAIL and raw["detail_status"] == "ok"
    assert row.ai_score == 64 and raw["ai_reason"] == "valutazione precedente"
    assert (row.job_id, row.scraped_at) == (first_job, FIRST_SEEN)
    assert row.last_job_id == job_id and row.last_seen_at > FIRST_SEEN
    assert (row.triage_status, row.lat, row.geocode_status) == ("preferito", 44.5, "ok")


def test_blocked_unscored_rerun_never_clobbers_an_enriched_scored_row():
    cid = _config(auto_analyse=False)
    url = _url("enriched-price-change")
    first_job = _seed(cid, url, {"detail": GOOD_LEGACY_DETAIL, "detail_status": "ok",
                                 "detail_description": GOOD_LEGACY_DETAIL["description"],
                                 "detail_features": {"Arredato": "Sì"}, "post_date": "Annuncio aggiornato il 01/10/2026"})

    # the price dropped: the page is refetched, and the refetch is blocked
    job_id, fetch, _ = _run(cid, [_Card(url, price="€ 850/mese")], detail=lambda u: BlockedError(u))

    assert fetch.await_count == 1
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert raw["detail"] == GOOD_LEGACY_DETAIL and raw["detail_status"] == "ok" and "detail_error" not in raw
    assert raw["detail_features"] == {"Arredato": "Sì"} and raw["post_date"] == "Annuncio aggiornato il 01/10/2026"
    assert (row.ai_score, row.ai_verdict) == (64, "Good match")
    assert raw["ai_reason"] == "valutazione precedente" and raw["notion_fields"] == {"address": "Via Mascarella 7"}
    assert row.price == "€ 850/mese" and raw["price"] == "€ 850/mese"  # fresh card data still lands
    assert (row.job_id, row.scraped_at) == (first_job, FIRST_SEEN)
    assert row.last_job_id == job_id and row.last_seen_at > FIRST_SEEN


def test_blocked_backfill_of_a_blank_legacy_row_keeps_its_score():
    cid = _config()
    url = _url("legacy-blank-blocked")
    first_job = _seed(cid, url, {"detail": BLANK_LEGACY_DETAIL, "detail_description": ""})

    job_id, fetch, analyse = _run(cid, [_Card(url)], detail=lambda u: BlockedError(u))

    assert [c.args[0] for c in fetch.await_args_list] == [url]  # picked for backfill
    analyse.assert_not_awaited()  # valid score, page not read: nothing new to score
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert row.ai_score == 64 and row.ai_verdict == "Good match"
    assert raw["ai_reason"] == "valutazione precedente" and raw["notion_fields"] == {"address": "Via Mascarella 7"}
    assert raw["detail_status"] == "blocked" and raw["detail_error"]
    assert (row.job_id, row.scraped_at, row.last_job_id) == (first_job, FIRST_SEEN, job_id)

    summary = listing_summary(row)
    assert summary["detail_status"] == "blocked" and summary["detail_error"]
    log = _job(job_id).log
    assert "0 ok, 1 blocked" in log
    assert "[warn] Most detail pages were blocked" in log


def test_successful_backfill_stores_the_detail_and_rescores():
    cid = _config()
    url = _url("legacy-blank-ok")
    first_job = _seed(cid, url, {"detail": BLANK_LEGACY_DETAIL}, score=5, verdict="Skip")
    seen = []

    async def fake_analyse(listings, prefs):
        for listing in listings:
            seen.append(dict(listing))
            listing.update(ai_score=82, ai_verdict="Strong match", ai_reason="ora con i dati del portale",
                           notion_fields={"address": "Via Emilia Levante 403"})
        return {"tokens_used": 1500, "cost_usd": 0.007, "scored": len(listings), "failed": 0}

    job_id, _, _ = _run(cid, [_Card(url)], detail=lambda u: DETAIL_HTML,
                        analyse=AsyncMock(side_effect=fake_analyse))

    assert [l["url"] for l in seen] == [url]
    assert seen[0]["detail_status"] == "ok" and seen[0]["detail_description"].startswith("Bilocale completamente")
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert raw["detail"]["title"] == "Bilocale via Emilia Levante 403, Bologna"
    assert raw["detail_features"]["Arredato"] == "Sì" and raw["detail_status"] == "ok"
    assert row.ai_score == 82 and raw["ai_reason"] == "ora con i dati del portale"
    assert row.job_id == first_job and row.last_job_id == job_id
    job = _job(job_id)
    assert job.ai_tokens_used == 1500 and "1 ok, 0 blocked" in job.log


def test_failed_rescore_after_backfill_keeps_the_previous_score_but_saves_the_detail():
    cid = _config()
    url = _url("legacy-blank-scorefail")
    _seed(cid, url, {"detail": BLANK_LEGACY_DETAIL})

    async def failing(listings, prefs):
        for listing in listings:
            listing.update(ai_error="InternalServerError 529: overloaded", ai_verdict="Error", ai_score=0,
                           ai_reason="InternalServerError 529: overloaded")
        return {"tokens_used": 0, "cost_usd": 0.0, "scored": 0, "failed": len(listings)}

    job_id, _, _ = _run(cid, [_Card(url)], detail=lambda u: DETAIL_HTML, analyse=AsyncMock(side_effect=failing))

    row = _row(url)
    raw = json.loads(row.raw_json)
    assert (row.ai_score, row.ai_verdict) == (64, "Good match")
    assert raw["ai_reason"] == "valutazione precedente" and "ai_error" not in raw
    assert raw["detail_status"] == "ok" and raw["detail"]["title"].startswith("Bilocale via Emilia")
    assert "[warn] AI scoring failed for 1 listing(s)" in _job(job_id).log


def test_new_listings_behind_a_block_trip_the_breaker_and_are_stored_without_detail():
    cid = _config(auto_analyse=False)
    urls = [_url(f"new-blocked-{i}") for i in range(5)]

    job_id, fetch, _ = _run(cid, [_Card(u) for u in urls], detail=lambda u: BlockedError(u))

    assert fetch.await_count == 3
    statuses = [json.loads(_row(u).raw_json)["detail_status"] for u in urls]
    assert statuses == ["blocked"] * 3 + ["skipped"] * 2
    for u in urls:
        row = _row(u)
        raw = json.loads(row.raw_json)
        assert "detail" not in raw and raw["description_snippet"]  # card data kept for the UI and the LLM
        assert row.job_id == job_id == row.last_job_id
    assert [listing_summary(_row(u))["detail_status"] for u in urls[2:4]] == ["blocked", "missing"]
    job = _job(job_id)
    assert job.status == "done" and job.listing_count == 5
    assert "0 ok, 3 blocked, 0 error, 0 empty, 2 skipped" in job.log


def test_new_listing_behind_a_block_is_scored_on_its_search_card(monkeypatch):
    """End to end with the real analyse_listings: the 57-listings scenario must give the LLM the card data."""
    import apt_scrape.analysis as analysis
    from langchain_core.messages import AIMessage

    prompts: list[str] = []

    class _LLM:
        profile = {"structured_output": True}

        def with_structured_output(self, schema, method=None, include_raw=False):
            class _S:
                async def ainvoke(self, messages, config=None):
                    prompts.append(messages[1]["content"])
                    parsed = analysis.NotionApartmentFields(
                        title="Bilocale", ai_reason="Arredato; spese non verificabili", ai_verdict="Potential",
                        ai_score=52, notes="Da verificare: spese")
                    return {"raw": AIMessage(content=""), "parsed": parsed, "parsing_error": None}
            return _S()

    monkeypatch.setattr(analysis, "_get_llm", lambda: _LLM())
    monkeypatch.setattr(analysis, "_graph_instance", None)
    monkeypatch.setattr(analysis, "_semaphore", None)
    cid = _config()
    url = _url("new-blocked-scored")

    job_id, _, _ = _run(cid, [_Card(url)], detail=lambda u: BlockedError(u), analyse=analysis.analyse_listings)

    [prompt] = prompts
    assert "Bilocale arredato vicino al centro" in prompt  # the card excerpt
    assert "excerpt from the search results page" in prompt
    assert "Search card features: 2 locali, Arredato" in prompt and "1 bagno" in prompt
    assert "NOT read (blocked by the portal's anti-bot protection" in prompt
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert (row.ai_score, row.ai_verdict) == (52, "Potential")
    assert raw["detail_status"] == "blocked" and raw["ai_notes"] == "Da verificare: spese"
    assert "Analysis complete: 1 scored, 0 failed" in _job(job_id).log


def test_stored_error_score_is_retried_without_refetching_the_page():
    cid = _config()
    url = _url("error-score")
    _seed(cid, url, {"detail": GOOD_LEGACY_DETAIL, "detail_status": "ok", "ai_error": "timeout"},
          score=0, verdict="Error")
    seen = []

    async def fake_analyse(listings, prefs):
        for listing in listings:
            seen.append(dict(listing))
            listing.pop("ai_error", None)
            listing.update(ai_score=58, ai_verdict="Potential", ai_reason="riprovato")
        return {"tokens_used": 900, "cost_usd": 0.004, "scored": len(listings), "failed": 0}

    _, fetch, _ = _run(cid, [_Card(url)], detail=lambda u: BlockedError(u), analyse=AsyncMock(side_effect=fake_analyse))

    fetch.assert_not_awaited()
    assert [l["url"] for l in seen] == [url] and seen[0]["detail"] == GOOD_LEGACY_DETAIL
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert (row.ai_score, row.ai_verdict) == (58, "Potential")
    assert "ai_error" not in raw and raw["ai_reason"] == "riprovato"


def test_two_runs_first_found_stays_last_seen_moves():
    cid = _config(auto_analyse=False)
    url = _url("two-runs")

    first, _, _ = _run(cid, [_Card(url)], detail=lambda u: DETAIL_HTML)
    row1 = _row(url)
    assert (row1.job_id, row1.last_job_id) == (first, first)
    assert row1.last_seen_at >= row1.scraped_at  # checkpoint insert, then the final upsert

    second, fetch, _ = _run(cid, [_Card(url)], detail=lambda u: DETAIL_HTML)
    fetch.assert_not_awaited()  # read in the first run, same price: reused
    row2 = _row(url)
    assert (row2.job_id, row2.scraped_at) == (first, row1.scraped_at)
    assert row2.last_job_id == second and row2.last_seen_at > row1.last_seen_at
    assert json.loads(row2.raw_json)["detail"] == json.loads(row1.raw_json)["detail"]
    d = listing_summary(row2)
    assert (d["job_id"], d["last_job_id"], d["first_seen_at"]) == (first, second, row1.scraped_at)


@pytest.mark.parametrize("raw", [
    {"detail": GOOD_LEGACY_DETAIL},
    {"detail": {"title": "", "description": "", "extra_info": {"Arredato": "Sì"}}},
    {"detail": BLANK_LEGACY_DETAIL},
    {"detail": {"title": "", "description": "", "extra_info": {"Piano": ""}}},  # dd without text
    {"detail": {"title": " ", "description": "\n", "extra_info": {}}},
    {"detail_status": "ok", "detail": GOOD_LEGACY_DETAIL},
    {"detail_status": "blocked"},
    {"title": "card only"},
], ids=["good", "facts-only", "blank", "blank-facts", "whitespace", "ok", "blocked", "no-detail"])
def test_runner_retries_exactly_the_details_the_api_reports_as_unread(raw):
    # The certificate tells the user an unread page is retried on the next run (C7):
    # the runner's backfill rule must agree with the API's detail_status (C6).
    assert runner._has_ok_detail(raw) == (detail_status_of(raw) == "ok")


# ---------------------------------------------------------------------------
# File database: migration backfill and journal mode
# ---------------------------------------------------------------------------

_OLD_LISTING_TABLE = """
CREATE TABLE listing (
    id INTEGER PRIMARY KEY, url VARCHAR NOT NULL UNIQUE, job_id INTEGER NOT NULL, config_id INTEGER NOT NULL,
    title VARCHAR, price VARCHAR, sqm VARCHAR, rooms VARCHAR, area VARCHAR, city VARCHAR,
    ai_score INTEGER, ai_verdict VARCHAR, notion_page_id VARCHAR, raw_json VARCHAR,
    scraped_at DATETIME NOT NULL
)
"""


def test_file_database_migrates_listing_columns_and_uses_wal(tmp_path):
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as conn:
        conn.execute(_OLD_LISTING_TABLE)
        conn.execute(
            "INSERT INTO listing (url, job_id, config_id, title, price, raw_json, scraped_at) "
            "VALUES ('https://example.com/old', 7, 1, 'Vecchio', '€ 800/mese', '{}', '2026-10-01 08:00:00')"
        )
    script = textwrap.dedent("""
        import json
        from sqlalchemy import text
        from backend.db import create_db_and_tables, engine
        create_db_and_tables()
        create_db_and_tables()  # idempotent
        with engine.connect() as conn:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(listing)"))]
            row = conn.execute(text("SELECT last_seen_at, last_job_id, scraped_at, job_id FROM listing")).one()
            mode = conn.execute(text("PRAGMA journal_mode")).scalar()
        print(json.dumps({"cols": cols, "row": [str(v) for v in row], "mode": mode}))
    """)
    env = {k: v for k, v in os.environ.items() if k != "SQLITE_JOURNAL_MODE"}
    env["DB_PATH"] = str(db)
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])

    assert {"last_seen_at", "last_job_id", "triage_status", "geocode_status"} <= set(out["cols"])
    last_seen_at, last_job_id, scraped_at, job_id = out["row"]
    assert last_seen_at == scraped_at and last_job_id == job_id == "7"
    assert out["mode"].lower() == "wal"


_OLD_JOB_TABLE = """
CREATE TABLE job (
    id INTEGER PRIMARY KEY, config_id INTEGER NOT NULL, status VARCHAR NOT NULL, triggered_by VARCHAR NOT NULL,
    started_at DATETIME NOT NULL, finished_at DATETIME, listing_count INTEGER, log VARCHAR NOT NULL
)
"""


def test_migration_marks_existing_rows_and_jobs_as_legacy_attribution(tmp_path):
    """The old upsert rewrote job_id/scraped_at: only rows and jobs created after the migration are exact."""
    db = tmp_path / "app.db"
    with sqlite3.connect(db) as conn:
        conn.execute(_OLD_LISTING_TABLE)
        conn.execute(_OLD_JOB_TABLE)
        conn.execute("INSERT INTO job (id, config_id, status, triggered_by, started_at, log) "
                     "VALUES (7, 1, 'done', 'manual', '2026-10-01 08:00:00', '')")
        conn.execute(
            "INSERT INTO listing (url, job_id, config_id, title, price, raw_json, scraped_at) "
            "VALUES ('https://example.com/old', 7, 1, 'Vecchio', '€ 800/mese', '{}', '2026-10-01 08:00:00')"
        )
    script = textwrap.dedent("""
        import json
        from sqlalchemy import text
        from sqlmodel import Session
        from backend.db import Job, Listing, create_db_and_tables, engine
        create_db_and_tables()
        create_db_and_tables()  # idempotent
        with Session(engine) as s:
            job = Job(config_id=1, status="done", triggered_by="manual")
            s.add(job)
            s.commit()
            s.refresh(job)
            s.add(Listing(url="https://example.com/new", job_id=job.id, config_id=1))
            s.commit()
        with engine.connect() as conn:
            jobs = [list(r) for r in conn.execute(text("SELECT id, attribution_exact FROM job ORDER BY id"))]
            rows = [list(r) for r in conn.execute(text("SELECT url, first_seen_exact FROM listing ORDER BY id"))]
        print(json.dumps({"jobs": jobs, "rows": rows}))
    """)
    env = {k: v for k, v in os.environ.items() if k != "SQLITE_JOURNAL_MODE"}
    env["DB_PATH"] = str(db)
    proc = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["jobs"] == [[7, None], [8, 1]]
    assert out["rows"] == [["https://example.com/old", None], ["https://example.com/new", 1]]
