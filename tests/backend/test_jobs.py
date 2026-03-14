# tests/backend/test_jobs.py
import os
os.environ["DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from sqlmodel import Session
from backend.main import app
from backend.db import create_db_and_tables, engine, SearchConfig, Job

create_db_and_tables()
client = TestClient(app)


def _seed_config_and_job(status="done", count=5):
    with Session(engine) as s:
        cfg = SearchConfig(
            name="T", city="milano", area=None, operation="affitto",
            property_type="appartamenti", schedule_days='["mon"]', schedule_time="08:00"
        )
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        job = Job(
            config_id=cfg.id, status=status, triggered_by="manual",
            listing_count=count, log="line1\nline2\n"
        )
        s.add(job)
        s.commit()
        s.refresh(job)
        return cfg.id, job.id


def test_list_jobs():
    cfg_id, job_id = _seed_config_and_job()
    resp = client.get("/jobs")
    assert resp.status_code == 200
    ids = [j["id"] for j in resp.json()]
    assert job_id in ids


def test_get_job_detail():
    cfg_id, job_id = _seed_config_and_job()
    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "done"
    assert data["listing_count"] == 5
    assert "line1" in data["log"]


def test_filter_by_config_id():
    cfg_id, job_id = _seed_config_and_job()
    resp = client.get(f"/jobs?config_id={cfg_id}")
    assert resp.status_code == 200
    for j in resp.json():
        assert j["config_id"] == cfg_id


def test_job_not_found():
    resp = client.get("/jobs/99999")
    assert resp.status_code == 404
