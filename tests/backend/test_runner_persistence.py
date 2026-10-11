"""Regression tests for incremental processing, merge-upsert and job lifecycle (contract C5)."""
import os
os.environ["DB_PATH"] = ":memory:"

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session, select

from backend.db import Job, Listing, SearchConfig, create_db_and_tables, engine, reconcile_interrupted_jobs
import backend.runner as runner
from apt_scrape.server import BlockedError

create_db_and_tables()

URL = "https://www.immobiliare.it/annunci/1/"
GOOD_DETAIL = {"title": "Bilocale Mazzini", "description": "Luminoso bilocale", "extra_info": {"Piano": "2"}}


def _config(**kw) -> int:
    with Session(engine) as s:
        opts = dict(
            name="T", city="bologna", area=None, operation="affitto",
            property_type="appartamenti", start_page=1, end_page=1,
            schedule_days="[]", schedule_time="08:00", detail_concurrency=2,
            vpn_rotate_batches=2, auto_analyse=False,
            auto_notion_push=False, request_delay_sec=0.0,
        )
        cfg = SearchConfig(**{**opts, **kw})
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def _seed_row(config_id: int, url: str, raw: dict, *, price="€ 600/mese", score=72, verdict="Strong Match",
              notion_page_id="np-1") -> tuple[int, int]:
    with Session(engine) as s:
        job = Job(config_id=config_id, status="done", triggered_by="manual")
        s.add(job)
        s.commit()
        s.refresh(job)
        first_seen = datetime(2026, 10, 1, 12, 0, 0)
        s.add(Listing(
            url=url, job_id=job.id, config_id=config_id, title="Bilocale", price=price,
            sqm="50 m²", rooms="2 locali", area="mazzini", city="bologna",
            ai_score=score, ai_verdict=verdict, notion_page_id=notion_page_id,
            raw_json=json.dumps({"url": url, "price": price, "ai_score": score, "ai_verdict": verdict,
                                 "ai_reason": "ottimo", "notion_fields": {"address": "Via Mazzini 1"}, **raw}),
            scraped_at=first_seen, last_seen_at=first_seen, last_job_id=job.id,
            triage_status="preferito",
        ))
        s.commit()
        return job.id, first_seen


def _card(url=URL, price="€ 600/mese"):
    m = MagicMock()
    m.url = url
    m.to_dict.return_value = {"url": url, "title": "Bilocale", "price": price, "sqm": "", "rooms": "2 locali",
                              "description_snippet": "card text"}
    return m


def _adapter(pages):
    a = MagicMock()
    a.build_search_url.side_effect = lambda f: f"https://example.com/search?pag={f.page}"
    a.parse_search.side_effect = pages
    a.config.search_wait_selector = None
    a.config.page_load_wait = "domcontentloaded"
    a.config.search_wait_timeout = 15000
    return a


def _run(config_id, adapter, enrich_side_effect=None, fetch=None, analyse=None):
    enrich_calls = []

    async def fake_enrich(listings, *a, **k):
        enrich_calls.append([l["url"] for l in listings])
        if enrich_side_effect:
            enrich_side_effect(listings)
        return (0, [])

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides", return_value=adapter),
        patch("backend.runner.enrich_with_details", side_effect=fake_enrich),
        patch("apt_scrape.analysis.load_preferences", return_value="prefs"),
        patch("apt_scrape.analysis.analyse_listings", new=analyse or AsyncMock(return_value={})),
    ):
        mock_browser.fetch_page = fetch or AsyncMock(return_value="<html></html>")
        job_id = asyncio.run(runner.run_config_job(config_id, lambda m: None))
    return job_id, enrich_calls


def _row(url=URL) -> Listing:
    with Session(engine) as s:
        return s.exec(select(Listing).where(Listing.url == url)).one()


def _job(job_id) -> Job:
    with Session(engine) as s:
        return s.get(Job, job_id)


def test_known_listing_with_good_detail_is_not_refetched_or_rescored():
    cid = _config(auto_analyse=True)
    url = URL + "known"
    first_job, first_seen = _seed_row(cid, url, {"detail": GOOD_DETAIL, "detail_status": "ok",
                                                 "detail_description": "Luminoso bilocale"})
    analyse = AsyncMock(return_value={"tokens_used": 0, "cost_usd": 0, "scored": 0, "failed": 0})
    job_id, calls = _run(cid, _adapter([[_card(url)]]), analyse=analyse)

    assert calls == []  # no detail fetch
    analyse.assert_not_awaited()
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert raw["detail"] == GOOD_DETAIL and raw["detail_status"] == "ok"
    assert row.ai_score == 72 and raw["ai_reason"] == "ottimo"
    assert row.job_id == first_job and row.scraped_at == first_seen       # first found: never reset
    assert row.last_job_id == job_id and row.last_seen_at > first_seen    # last seen: moves
    assert row.triage_status == "preferito" and row.notion_page_id == "np-1"
    assert "Job complete" in _job(job_id).log


def test_blocked_refetch_keeps_stored_detail_and_score():
    cid = _config(auto_analyse=False)
    url = URL + "blocked"
    _seed_row(cid, url, {"detail": GOOD_DETAIL, "detail_status": "ok"}, price="€ 600/mese")

    def blocked(listings):
        for l in listings:
            l["detail_status"] = "blocked"
            l["detail_error"] = "blocked by bot protection"

    # price changed -> refetch, which is blocked
    job_id, calls = _run(cid, _adapter([[_card(url, price="€ 550/mese")]]), enrich_side_effect=blocked)
    assert calls == [[url]]
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert raw["detail"] == GOOD_DETAIL and raw["detail_status"] == "ok" and "detail_error" not in raw
    assert row.price == "€ 550/mese"
    assert row.ai_score == 72 and raw["notion_fields"] == {"address": "Via Mazzini 1"}
    assert "1 blocked" in _job(job_id).log


def test_legacy_blank_detail_is_backfilled_and_rescored():
    cid = _config(auto_analyse=True)
    url = URL + "legacy"
    _seed_row(cid, url, {"detail": {"title": "", "description": "", "extra_info": {}}, "detail_description": ""},
              score=5, verdict="Skip")

    def ok(listings):
        for l in listings:
            l["detail"] = GOOD_DETAIL
            l["detail_status"] = "ok"
            l["detail_description"] = GOOD_DETAIL["description"]

    async def fake_analyse(listings, prefs):
        for l in listings:
            l.update(ai_score=80, ai_verdict="Strong Match", ai_reason="nuovo", notion_fields={"address": "X"})
        return {"tokens_used": 123, "cost_usd": 0.01, "scored": len(listings), "failed": 0}

    job_id, calls = _run(cid, _adapter([[_card(url)]]), enrich_side_effect=ok, analyse=AsyncMock(side_effect=fake_analyse))
    assert calls == [[url]]
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert row.ai_score == 80 and raw["ai_reason"] == "nuovo" and raw["detail_status"] == "ok"
    job = _job(job_id)
    assert job.ai_tokens_used == 123 and "1 ok" in job.log


def test_failed_scoring_never_replaces_a_valid_score():
    cid = _config(auto_analyse=True)
    url = URL + "failscore"
    _seed_row(cid, url, {"detail": {"title": "", "description": "", "extra_info": {}}})

    def ok(listings):
        for l in listings:
            l.update(detail=GOOD_DETAIL, detail_status="ok")

    async def failing(listings, prefs):
        for l in listings:
            l.update(ai_error="overloaded", ai_verdict="Error", ai_score=0, ai_reason="overloaded")
        return {"tokens_used": 0, "cost_usd": 0, "scored": 0, "failed": len(listings)}

    _run(cid, _adapter([[_card(url)]]), enrich_side_effect=ok, analyse=AsyncMock(side_effect=failing))
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert row.ai_score == 72 and row.ai_verdict == "Strong Match"
    assert raw["ai_reason"] == "ottimo" and raw["ai_last_error"] == "overloaded" and "ai_error" not in raw
    assert raw["detail"] == GOOD_DETAIL  # the new detail is still saved


def test_new_listing_failed_scoring_is_stored_as_error():
    cid = _config(auto_analyse=True)
    url = URL + "newfail"

    async def failing(listings, prefs):
        for l in listings:
            l.update(ai_error="boom", ai_verdict="Error", ai_score=0, ai_reason="boom")
        return {"scored": 0, "failed": 1}

    job_id, _ = _run(cid, _adapter([[_card(url)]]), analyse=AsyncMock(side_effect=failing))
    row = _row(url)
    assert row.ai_verdict == "Error" and row.job_id == job_id and row.last_job_id == job_id
    assert json.loads(row.raw_json)["ai_error"] == "boom"


def test_one_failed_search_page_does_not_fail_the_job():
    cid = _config(area="a1, a2")
    fetch = AsyncMock(side_effect=[BlockedError("https://x/a1"), "<html></html>"])
    job_id, _ = _run(cid, _adapter([[_card(URL + "a2")]]), fetch=fetch)
    job = _job(job_id)
    assert job.status == "done" and job.listing_count == 1
    assert "blocked by the portal" in job.log and "results are partial" in job.log


def test_job_fails_only_when_nothing_could_be_fetched():
    cid = _config(area="a1, a2")
    fetch = AsyncMock(side_effect=TimeoutError("nav timeout"))
    job_id, _ = _run(cid, _adapter([]), fetch=fetch)
    job = _job(job_id)
    assert job.status == "failed" and "No search page could be fetched" in job.log


def test_pagination_stops_on_a_short_page():
    cid = _config(end_page=5)
    pages = [[_card(URL + f"p1-{i}") for i in range(3)], [_card(URL + "p2-0")]]
    fetch = AsyncMock(return_value="<html></html>")
    job_id, _ = _run(cid, _adapter(pages), fetch=fetch)
    assert fetch.await_count == 2
    assert "last page reached" in _job(job_id).log


def test_cancelled_run_saves_partial_data_and_fails_job():
    cid = _config()
    url = URL + "cancel"

    def cancel(listings):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        _run(cid, _adapter([[_card(url)]]), enrich_side_effect=cancel)
    with Session(engine) as s:
        job = s.exec(select(Job).where(Job.config_id == cid)).all()[-1]
    assert job.status == "failed" and job.finished_at is not None and "cancelled" in job.log
    assert _row(url).job_id == job.id  # the scraped card was kept


def test_run_timeout_marks_job_failed():
    cid = _config(timeout_sec=1)

    async def slow_fetch(*a, **k):
        await asyncio.sleep(5)

    job_id, _ = _run(cid, _adapter([]), fetch=slow_fetch)
    job = _job(job_id)
    assert job.status == "failed" and "timed out after 1s" in job.log


def test_reconcile_interrupted_jobs():
    cid = _config()
    with Session(engine) as s:
        ids = []
        for status in ("pending", "running", "done"):
            j = Job(config_id=cid, status=status)
            s.add(j)
            s.commit()
            s.refresh(j)
            ids.append(j.id)
    assert reconcile_interrupted_jobs() >= 2
    assert [_job(i).status for i in ids] == ["failed", "failed", "done"]
    assert "interrupted" in _job(ids[0]).log


def test_merge_raw_rules():
    old = {"url": "u", "post_date": "2026-10-01", "detail": GOOD_DETAIL, "detail_status": "ok",
           "ai_score": 70, "ai_verdict": "Potential", "photos": ["a"]}
    new = {"url": "u", "post_date": "", "photos": [], "detail_status": "empty", "detail_error": "blank page"}
    m = runner._merge_raw(old, new, take_new_ai=False)
    assert m["detail"] == GOOD_DETAIL and m["detail_status"] == "ok" and "detail_error" not in m
    assert m["post_date"] == "2026-10-01" and m["photos"] == ["a"] and m["ai_score"] == 70
    # nothing usable stored -> this run's failure status is recorded
    m = runner._merge_raw({"detail": {"title": ""}}, new, take_new_ai=False)
    assert m["detail_status"] == "empty" and m["detail_error"] == "blank page" and "detail" not in m


def test_scheduler_guard_and_browser_lifecycle():
    import backend.scheduler as sched
    cid = _config()
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_run(config_id, log_fn, existing_job_id=None):
        started.set()
        await release.wait()
        with Session(engine) as s:
            j = s.get(Job, existing_job_id)
            j.status = "done"
            s.add(j)
            s.commit()
        return existing_job_id

    async def scenario():
        with patch("backend.scheduler.run_config_job", side_effect=fake_run), \
             patch("apt_scrape.server.browser") as mock_browser:
            mock_browser.close = AsyncMock()
            first = sched.trigger_now(cid)
            await started.wait()
            assert sched.trigger_now(cid) == first          # second request: already running
            await sched._run_job_wrapper(cid)                # scheduled run skipped too
            assert _job(first).status == "running" or _job(first).status == "pending"
            mock_browser.close.assert_not_awaited()
            release.set()
            await sched._active[cid][1]
            assert cid not in sched._active
            mock_browser.close.assert_awaited_once()
            return first

    first = asyncio.run(scenario())
    assert _job(first).status == "done"
    with Session(engine) as s:
        assert len(s.exec(select(Job).where(Job.config_id == cid)).all()) == 1


def test_scheduled_jobs_get_misfire_grace():
    import backend.scheduler as sched
    assert sched._scheduler._job_defaults["misfire_grace_time"] >= 3600
    assert sched._JOB_OPTIONS["coalesce"] is True


# ---------------------------------------------------------------------------
# Repair round: partial saves, search cadence and breaker, pending rescores
# ---------------------------------------------------------------------------


def _latest_job(config_id: int) -> Job:
    with Session(engine) as s:
        return s.exec(select(Job).where(Job.config_id == config_id)).all()[-1]


def _set_config(config_id: int, **kw) -> None:
    with Session(engine) as s:
        cfg = s.get(SearchConfig, config_id)
        for k, v in kw.items():
            setattr(cfg, k, v)
        s.add(cfg)
        s.commit()


def test_cancel_during_search_keeps_the_cards_already_scraped():
    cid = _config(end_page=3, area="centro")
    urls = [URL + f"search-cancel-{i}" for i in range(2)]
    fetch = AsyncMock(side_effect=["<html></html>", asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        _run(cid, _adapter([[_card(u) for u in urls]]), fetch=fetch)
    job = _latest_job(cid)
    assert job.status == "failed" and job.listing_count == 2
    for u in urls:
        row = _row(u)
        raw = json.loads(row.raw_json)
        assert row.job_id == job.id and row.last_job_id == job.id
        assert row.area == "centro" and raw["_area"] == "centro" and "_search_area" not in raw


def test_timeout_during_search_keeps_the_cards_already_scraped():
    cid = _config(end_page=3, timeout_sec=1)
    urls = [URL + f"search-timeout-{i}" for i in range(2)]
    calls = 0

    async def fetch(*a, **k):
        nonlocal calls
        calls += 1
        if calls > 1:
            await asyncio.sleep(5)
        return "<html></html>"

    job_id, _ = _run(cid, _adapter([[_card(u) for u in urls]]), fetch=fetch)
    job = _job(job_id)
    assert job.status == "failed" and "timed out after 1s" in job.log and job.listing_count == 2
    assert all(_row(u).job_id == job_id for u in urls)


def test_repeated_search_blocks_stop_the_remaining_searches():
    cid = _config(area="a1, a2, a3", property_type="appartamenti,case")  # 6 searches
    fetch = AsyncMock(side_effect=BlockedError("https://x"))
    job_id, _ = _run(cid, _adapter([]), fetch=fetch)
    assert fetch.await_count == runner.SEARCH_BLOCK_LIMIT
    job = _job(job_id)
    assert job.status == "failed" and "No search page could be fetched" in job.log
    assert "searches in a row blocked" in job.log


def test_a_fetched_search_resets_the_block_count():
    cid = _config(area="a1, a2, a3, a4, a5")
    fetch = AsyncMock(side_effect=[BlockedError("https://x/a1"), "<html></html>",
                                   BlockedError("https://x/a3"), BlockedError("https://x/a4")])
    job_id, _ = _run(cid, _adapter([[_card(URL + "reset-a2")]]), fetch=fetch)
    assert fetch.await_count == 4  # a5 is skipped after a3 and a4 were blocked in a row
    job = _job(job_id)
    assert job.status == "done" and job.listing_count == 1 and "results are partial" in job.log


def test_search_pages_pause_after_the_previous_page_loaded():
    cid = _config(end_page=3, request_delay_sec=0.2)
    starts: list[float] = []

    async def fetch(*a, **k):
        starts.append(asyncio.get_running_loop().time())
        return "<html></html>"

    pages = [[_card(URL + f"cadence-{p}-{i}") for i in range(2)] for p in range(3)]
    _run(cid, _adapter(pages), fetch=fetch)
    assert len(starts) == 3
    assert all(b - a >= 0.19 for a, b in zip(starts, starts[1:]))


def test_job_deleted_mid_run_finishes_quietly(caplog):
    import logging
    cid = _config()
    url = URL + "deleted-job"

    def delete_job(listings):
        with Session(engine) as s:
            s.delete(s.get(Job, _latest_job(cid).id))
            s.commit()

    with caplog.at_level(logging.WARNING, logger="backend.runner"):
        job_id, _ = _run(cid, _adapter([[_card(url)]]), enrich_side_effect=delete_job)
    assert _job(job_id) is None
    assert "deleted while running" in caplog.text and f"Job {job_id} failed" not in caplog.text
    assert _row(url).job_id == job_id


def _read_ok(listings):
    for l in listings:
        l.update(detail=GOOD_DETAIL, detail_status="ok", detail_description=GOOD_DETAIL["description"])


def _read_ok_then_cancel(listings):
    _read_ok(listings)
    raise asyncio.CancelledError()


async def _llm_429(listings, prefs):
    for l in listings:
        l.update(ai_error="429 rate limited", ai_verdict="Error", ai_score=0, ai_reason="429 rate limited")
    return {"scored": 0, "failed": len(listings)}


async def _llm_crash(listings, prefs):
    raise RuntimeError("analysis step crashed")


async def _llm_ok(listings, prefs):
    for l in listings:
        l.update(ai_score=81, ai_verdict="Strong Match", ai_reason="rivalutato", notion_fields={"address": "Y"})
    return {"scored": len(listings), "failed": 0}


BLANK_LEGACY = {"detail": {"title": "", "description": "", "extra_info": {}}}


@pytest.mark.parametrize("seed,run1_price,run1", [
    # a blank legacy row is read in run 1, but the LLM is rate limited
    (dict(raw=BLANK_LEGACY, price="€ 900/mese"), "€ 900/mese", dict(enrich=_read_ok, analyse=_llm_429)),
    # the price drops and the LLM fails: the score was built for the old price
    (dict(raw={"detail": GOOD_DETAIL, "detail_status": "ok"}, price="€ 900/mese"), "€ 650/mese",
     dict(enrich=_read_ok, analyse=_llm_429)),
    # run 1 has auto_analyse off (turned on before run 2)
    (dict(raw=BLANK_LEGACY, price="€ 900/mese"), "€ 900/mese", dict(enrich=_read_ok, auto_analyse=False)),
    # the whole analysis step raises
    (dict(raw=BLANK_LEGACY, price="€ 900/mese"), "€ 900/mese", dict(enrich=_read_ok, analyse=_llm_crash)),
    # the run is cancelled right after the detail page was read (partial save)
    (dict(raw=BLANK_LEGACY, price="€ 900/mese"), "€ 900/mese", dict(enrich=_read_ok_then_cancel, cancel=True)),
], ids=["llm-fails", "price-change-llm-fails", "auto-analyse-off", "analysis-crashes", "cancel-after-read"])
def test_a_rescore_the_run_could_not_finish_is_retried_next_run(seed, run1_price, run1):
    cid = _config(auto_analyse=run1.get("auto_analyse", True))
    url = URL + f"pending-{uuid4_hex()}"
    _seed_row(cid, url, seed["raw"], price=seed["price"], score=64, verdict="Potential")

    analyse1 = AsyncMock(side_effect=run1.get("analyse", _llm_ok))
    args = (cid, _adapter([[_card(url, price=run1_price)]]))
    if run1.get("cancel"):
        with pytest.raises(asyncio.CancelledError):
            _run(*args, enrich_side_effect=run1["enrich"], analyse=analyse1)
    else:
        _run(*args, enrich_side_effect=run1["enrich"], analyse=analyse1)
    row = _row(url)
    raw = json.loads(row.raw_json)
    assert row.ai_score == 64 and raw["detail_status"] == "ok" and raw["ai_rescore_pending"] is True

    _set_config(cid, auto_analyse=True)
    analyse2 = AsyncMock(side_effect=_llm_ok)
    _, calls = _run(cid, _adapter([[_card(url, price=run1_price)]]), analyse=analyse2)
    assert calls == []  # the stored detail is reused
    analyse2.assert_awaited_once()
    assert [l["url"] for l in analyse2.await_args.args[0]] == [url]
    row = _row(url)
    assert row.ai_score == 81 and "ai_rescore_pending" not in json.loads(row.raw_json)

    analyse3 = AsyncMock(side_effect=_llm_ok)
    _run(cid, _adapter([[_card(url, price=run1_price)]]), analyse=analyse3)
    analyse3.assert_not_awaited()


def test_unchanged_listing_with_valid_score_is_never_flagged():
    cid = _config(auto_analyse=False)
    url = URL + "pending-none"
    _seed_row(cid, url, {"detail": GOOD_DETAIL, "detail_status": "ok"}, price="€ 900/mese")
    _run(cid, _adapter([[_card(url, price="€ 900/mese")]]))
    assert "ai_rescore_pending" not in json.loads(_row(url).raw_json)


def uuid4_hex() -> str:
    import uuid
    return uuid.uuid4().hex[:10]
