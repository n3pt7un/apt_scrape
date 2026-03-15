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


def test_notion_push_empty_ids():
    """Returns 400 when listing_ids is empty."""
    resp = client.post("/listings/notion-push", json={"listing_ids": []})
    assert resp.status_code == 400


def test_notion_push_missing_credentials(monkeypatch):
    """Returns 503 when NOTION_API_KEY is not set."""
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_APARTMENTS_DB_ID", raising=False)
    resp = client.post("/listings/notion-push", json={"listing_ids": [1]})
    assert resp.status_code == 503
    assert "credentials" in resp.json()["detail"].lower()


def test_notion_push_success(monkeypatch):
    """Returns pushed/skipped counts; updates notion_page_id in DB."""
    cfg_id, job_a_id, job_b_id, lst_a_id, lst_b_id = _seed()

    async def fake_mark_duplicates(listings):
        return 0  # no duplicates

    async def fake_push(listings):
        for lst in listings:
            lst["notion_page_id"] = "fake-page-id-123"
            lst["notion_skipped"] = False

    monkeypatch.setenv("NOTION_API_KEY", "fake-key")
    monkeypatch.setenv("NOTION_APARTMENTS_DB_ID", "fake-db-id")
    # Patch at the import site used by the endpoint (module-level imports in listings.py)
    monkeypatch.setattr("backend.routers.listings.mark_notion_duplicates", fake_mark_duplicates)
    monkeypatch.setattr("backend.routers.listings.push_listings", fake_push)

    resp = client.post("/listings/notion-push", json={"listing_ids": [lst_a_id]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pushed"] == 1
    assert data["skipped"] == 0
    assert data["errors"] == []

    # Verify notion_page_id written back to DB
    with Session(engine) as s:
        updated = s.get(Listing, lst_a_id)
        assert updated.notion_page_id == "fake-page-id-123"


def test_notion_push_skips_duplicates(monkeypatch):
    """Skipped listings (already in Notion) get their notion_page_id backfilled."""
    cfg_id, job_a_id, job_b_id, lst_a_id, lst_b_id = _seed()

    async def fake_mark_duplicates(listings):
        for lst in listings:
            lst["notion_skipped"] = True
            lst["notion_page_id"] = "existing-page-id"
        return len(listings)

    async def fake_push(listings):
        pass  # nothing to push

    monkeypatch.setenv("NOTION_API_KEY", "fake-key")
    monkeypatch.setenv("NOTION_APARTMENTS_DB_ID", "fake-db-id")
    monkeypatch.setattr("backend.routers.listings.mark_notion_duplicates", fake_mark_duplicates)
    monkeypatch.setattr("backend.routers.listings.push_listings", fake_push)

    resp = client.post("/listings/notion-push", json={"listing_ids": [lst_b_id]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pushed"] == 0
    assert data["skipped"] == 1

    # notion_page_id backfilled for skipped listing
    with Session(engine) as s:
        updated = s.get(Listing, lst_b_id)
        assert updated.notion_page_id == "existing-page-id"
