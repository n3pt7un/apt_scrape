import json
import os
os.environ["DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from sqlmodel import Session
from backend.main import app
from backend.db import create_db_and_tables, engine, SearchConfig, Job, Listing

create_db_and_tables()
client = TestClient(app)

_seed_counter = 0


def _seed():
    """Seed one config, two jobs, and two listings (one per job). Uses a counter for unique URLs."""
    global _seed_counter
    _seed_counter += 1
    n = _seed_counter

    with Session(engine) as s:
        cfg = SearchConfig(
            name=f"T{n}", city="milano", area=None, operation="affitto",
            property_type="appartamenti", schedule_days='["mon"]', schedule_time="08:00"
        )
        s.add(cfg)
        s.commit()
        s.refresh(cfg)

        job_a = Job(config_id=cfg.id, status="done", triggered_by="manual", log="")
        job_b = Job(config_id=cfg.id, status="done", triggered_by="manual", log="")
        s.add(job_a)
        s.add(job_b)
        s.commit()
        s.refresh(job_a)
        s.refresh(job_b)

        url_a = f"https://example.com/{n}/a"
        url_b = f"https://example.com/{n}/b"
        lst_a = Listing(
            url=url_a,
            job_id=job_a.id,
            config_id=cfg.id,
            title=f"Apt {n}A",
            raw_json=json.dumps({"url": url_a, "title": f"Apt {n}A"}),
        )
        lst_b = Listing(
            url=url_b,
            job_id=job_b.id,
            config_id=cfg.id,
            title=f"Apt {n}B",
            raw_json=json.dumps({"url": url_b, "title": f"Apt {n}B"}),
        )
        s.add(lst_a)
        s.add(lst_b)
        s.commit()
        s.refresh(lst_a)
        s.refresh(lst_b)
        return cfg.id, job_a.id, job_b.id, lst_a.id, lst_b.id


def test_filter_by_job_id():
    cfg_id, job_a_id, job_b_id, lst_a_id, lst_b_id = _seed()
    resp = client.get(f"/listings?job_id={job_a_id}")
    assert resp.status_code == 200
    ids = [l["id"] for l in resp.json()]
    assert lst_a_id in ids
    assert lst_b_id not in ids
