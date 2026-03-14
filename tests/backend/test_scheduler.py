import os, json, asyncio
os.environ["DB_PATH"] = ":memory:"

from unittest.mock import AsyncMock, patch
from sqlmodel import Session
from backend.db import create_db_and_tables, engine, SearchConfig

create_db_and_tables()


def _seed_enabled_config():
    with Session(engine) as s:
        cfg = SearchConfig(
            name="Sched", city="milano", area="bicocca", operation="affitto",
            property_type="appartamenti", schedule_days='["mon","wed"]',
            schedule_time="08:00", enabled=True,
        )
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def test_trigger_now_creates_background_task():
    enabled_id = _seed_enabled_config()
    with patch("backend.scheduler.run_config_job", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = 42
        import backend.scheduler as sched
        job_id = sched.trigger_now(enabled_id)
        assert isinstance(job_id, int)


def test_reload_config_does_not_raise_for_unknown_id():
    import backend.scheduler as sched
    sched.reload_config(99999)
