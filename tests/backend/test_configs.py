# tests/backend/test_configs.py
import os, json
os.environ["DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from backend.main import app
from backend.db import create_db_and_tables

create_db_and_tables()
client = TestClient(app)

VALID_CONFIG = {
    "name": "Milano Bicocca",
    "city": "milano",
    "area": "bicocca",
    "operation": "affitto",
    "property_type": "appartamenti",
    "min_price": 700,
    "max_price": 1000,
    "min_sqm": 55,
    "min_rooms": 2,
    "start_page": 1,
    "end_page": 10,
    "schedule_days": ["mon", "wed", "fri"],
    "schedule_time": "08:00",
    "detail_concurrency": 5,
    "vpn_rotate_batches": 3,
    "auto_analyse": True,
    "auto_notion_push": False,
    "enabled": True,
}


def test_create_and_list_config():
    resp = client.post("/configs", json=VALID_CONFIG)
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Milano Bicocca"
    assert data["id"] is not None
    # schedule_days returned as list
    assert data["schedule_days"] == ["mon", "wed", "fri"]

    list_resp = client.get("/configs")
    assert list_resp.status_code == 200
    ids = [c["id"] for c in list_resp.json()]
    assert data["id"] in ids


def test_update_config():
    resp = client.post("/configs", json=VALID_CONFIG)
    cfg_id = resp.json()["id"]

    updated = {**VALID_CONFIG, "name": "Updated Name", "max_price": 1200}
    put_resp = client.put(f"/configs/{cfg_id}", json=updated)
    assert put_resp.status_code == 200
    assert put_resp.json()["max_price"] == 1200


def test_toggle_config():
    resp = client.post("/configs", json=VALID_CONFIG)
    cfg_id = resp.json()["id"]
    assert resp.json()["enabled"] is True

    tog = client.patch(f"/configs/{cfg_id}/toggle")
    assert tog.status_code == 200
    assert tog.json()["enabled"] is False


def test_delete_config():
    resp = client.post("/configs", json=VALID_CONFIG)
    cfg_id = resp.json()["id"]

    del_resp = client.delete(f"/configs/{cfg_id}")
    assert del_resp.status_code == 204

    get_resp = client.get(f"/configs/{cfg_id}")
    assert get_resp.status_code == 404


def test_create_config_with_site_and_delays():
    payload = {**VALID_CONFIG, "site_id": "casa", "request_delay_sec": 3.0, "page_delay_sec": 1.0}
    resp = client.post("/configs", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["site_id"] == "casa"
    assert data["request_delay_sec"] == 3.0
    assert data["page_delay_sec"] == 1.0


def test_create_config_invalid_site_id_returns_422():
    payload = {**VALID_CONFIG, "site_id": "unknown_site"}
    resp = client.post("/configs", json=payload)
    assert resp.status_code == 422


def test_get_configs_sites():
    resp = client.get("/configs/sites")
    assert resp.status_code == 200
    sites = resp.json()
    assert isinstance(sites, list)
    assert "immobiliare" in sites
    assert "casa" in sites
