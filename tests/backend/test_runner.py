import os, json
os.environ["DB_PATH"] = ":memory:"

from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel import Session
from backend.db import create_db_and_tables, engine, SearchConfig, Job

create_db_and_tables()


def _make_config():
    with Session(engine) as s:
        cfg = SearchConfig(
            name="Test", city="milano", area="bicocca", operation="affitto",
            property_type="appartamenti", min_price=700, max_price=1000,
            min_sqm=55, min_rooms=2, start_page=1, end_page=2,
            schedule_days='["mon"]', schedule_time="08:00",
            detail_concurrency=3, vpn_rotate_batches=2,
            auto_analyse=False, auto_notion_push=False,
        )
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def _make_fake_listing(url="https://example.com/1"):
    m = MagicMock()
    m.to_dict.return_value = {"url": url, "title": "Test apt", "price": "€900"}
    return m


import asyncio
import backend.runner as backend_runner_module
backend_runner_run = backend_runner_module.run_config_job


def test_run_config_job_creates_job_record():
    config_id = _make_config()
    logs = []
    fake_html = "<html></html>"
    fake_listings = [_make_fake_listing()]

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides") as mock_get_adapter,
        patch("backend.runner.enrich_with_details", new_callable=AsyncMock) as mock_enrich,
    ):
        mock_browser.fetch_page = AsyncMock(return_value=fake_html)
        mock_adapter = MagicMock()
        mock_adapter.build_search_url.return_value = "https://example.com/search"
        mock_adapter.parse_search.return_value = fake_listings
        mock_adapter.config.search_wait_selector = None
        mock_get_adapter.return_value = mock_adapter
        mock_enrich.return_value = (1, [])

        job_id = asyncio.run(backend_runner_run(config_id, logs.append))

    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.listing_count == 1
        assert job.config_id == config_id


def test_log_persists_on_mid_job_exception():
    config_id = _make_config()
    logs = []

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides") as mock_get_adapter,
        patch("backend.runner.enrich_with_details", new_callable=AsyncMock),
    ):
        mock_browser.fetch_page = AsyncMock(side_effect=asyncio.CancelledError("simulated cancel"))
        mock_adapter = MagicMock()
        mock_adapter.build_search_url.return_value = "https://example.com/search"
        mock_adapter.parse_search.return_value = []
        mock_adapter.config.search_wait_selector = None
        mock_adapter.config.page_load_wait = "domcontentloaded"
        mock_adapter.config.search_wait_timeout = 15000
        mock_get_adapter.return_value = mock_adapter

        try:
            job_id = asyncio.run(backend_runner_run(config_id, logs.append))
        except BaseException:
            # fetch the job_id from the DB — it was created before the exception
            with Session(engine) as s:
                from sqlmodel import select as sql_select
                from backend.db import Job
                jobs = s.exec(sql_select(Job).where(Job.config_id == config_id)).all()
                job_id = jobs[-1].id  # most recently created

    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job is not None
        assert job.log is not None and len(job.log) > 0
        assert "Fetching" in job.log  # pre-exception log line must be persisted


def test_log_flushes_to_db_after_interval(monkeypatch):
    """With the time-based flush, lines reach the DB before the 10-line batch fills up."""
    monkeypatch.setattr(backend_runner_module, "LOG_FLUSH_INTERVAL_SEC", 0.0)
    config_id = _make_config()
    with Session(engine) as s:  # no politeness delay needed against a fake browser
        cfg = s.get(SearchConfig, config_id)
        cfg.request_delay_sec = 0.0
        s.add(cfg)
        s.commit()
    persisted_at_fetch: list[str] = []

    async def fake_fetch(url, **kwargs):
        with Session(engine) as s:
            from sqlmodel import select as sql_select
            job = s.exec(sql_select(Job).where(Job.config_id == config_id)).all()[-1]
            persisted_at_fetch.append(job.log)
        return "<html></html>"

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides") as mock_get_adapter,
        patch("backend.runner.enrich_with_details", new_callable=AsyncMock),
    ):
        mock_browser.fetch_page = fake_fetch
        mock_adapter = MagicMock()
        mock_adapter.build_search_url.return_value = "https://example.com/search"
        mock_adapter.parse_search.return_value = [_make_fake_listing()]
        mock_adapter.config.search_wait_selector = None
        mock_get_adapter.return_value = mock_adapter

        asyncio.run(backend_runner_run(config_id, lambda msg: None))

    # Each "Fetching ... page N" line is already in the DB when that page is fetched
    assert len(persisted_at_fetch) == 2
    assert "page 1" in persisted_at_fetch[0]
    assert "page 2" in persisted_at_fetch[1]
