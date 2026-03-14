# tests/backend/test_db.py
import os
os.environ["DB_PATH"] = ":memory:"

from sqlmodel import Session, select
from backend.db import SearchConfig, Job, Listing, create_db_and_tables, engine


def test_create_tables():
    create_db_and_tables()
    # tables exist if no exception raised
    assert True


def test_search_config_defaults():
    create_db_and_tables()
    with Session(engine) as session:
        cfg = SearchConfig(
            name="Test",
            city="milano",
            area="bicocca",
            operation="affitto",
            property_type="appartamenti",
            min_price=700,
            max_price=1000,
            schedule_days='["mon"]',
            schedule_time="08:00",
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)
        assert cfg.id is not None
        assert cfg.enabled is True
        assert cfg.auto_analyse is True
        assert cfg.auto_notion_push is False
        assert cfg.detail_concurrency == 5
        assert cfg.start_page == 1
        assert cfg.end_page == 10
        assert cfg.site_id == "immobiliare"
        assert cfg.request_delay_sec == 2.0
        assert cfg.page_delay_sec == 0.0
        assert cfg.timeout_sec is None


def test_job_links_to_config():
    create_db_and_tables()
    with Session(engine) as session:
        cfg = SearchConfig(
            name="J", city="roma", area=None, operation="affitto",
            property_type="appartamenti", schedule_days='[]', schedule_time="09:00",
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)

        job = Job(config_id=cfg.id, status="pending", triggered_by="manual")
        session.add(job)
        session.commit()
        session.refresh(job)
        assert job.config_id == cfg.id
        assert job.status == "pending"


def test_listing_url_unique():
    create_db_and_tables()
    import pytest
    with Session(engine) as session:
        cfg = SearchConfig(
            name="L", city="milano", area="bicocca", operation="affitto",
            property_type="appartamenti", schedule_days='[]', schedule_time="08:00",
        )
        session.add(cfg)
        session.commit()
        session.refresh(cfg)

        job = Job(config_id=cfg.id, status="done", triggered_by="schedule")
        session.add(job)
        session.commit()
        session.refresh(job)

        from backend.db import Listing
        l1 = Listing(url="https://example.com/1", job_id=job.id, config_id=cfg.id,
                     title="Test", raw_json="{}")
        session.add(l1)
        session.commit()

        # Second listing with same URL should raise an IntegrityError
        l2 = Listing(url="https://example.com/1", job_id=job.id, config_id=cfg.id,
                     title="Duplicate", raw_json="{}")
        session.add(l2)
        with pytest.raises(Exception):  # IntegrityError (UNIQUE constraint)
            session.commit()
