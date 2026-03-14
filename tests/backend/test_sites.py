"""Tests for sites router."""
import os
import json
os.environ["DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from backend.main import app
from backend.db import create_db_and_tables

create_db_and_tables()
client = TestClient(app)


def test_list_sites():
    resp = client.get("/sites")
    assert resp.status_code == 200
    sites = resp.json()
    assert isinstance(sites, list)
    assert "immobiliare" in sites
    assert "casa" in sites


def test_get_site_config():
    resp = client.get("/sites/immobiliare/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["site_id"] == "immobiliare"
    assert "search_selectors" in data
    assert "listing_card" in data["search_selectors"]


def test_get_site_areas():
    resp = client.get("/sites/immobiliare/areas")
    assert resp.status_code == 200
    areas = resp.json()
    assert isinstance(areas, list)
    # When site has no overrides and no area_map in YAML, backend uses config/default_areas.txt
    assert "bicocca" in areas
    assert "centrale" in areas


def test_put_site_config():
    resp = client.put("/sites/casa/config", json={"areas": ["bicocca", "niguarda"], "search_wait_selector": "article"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"
    resp2 = client.get("/sites/casa/config")
    assert resp2.status_code == 200
    data = resp2.json()
    assert data.get("areas") == ["bicocca", "niguarda"]
    assert data.get("search_wait_selector") == "article"


def test_site_not_found():
    resp = client.get("/sites/nonexistent/config")
    assert resp.status_code == 404


def test_site_variant_save_and_list():
    """Saving overrides for immobiliare-test1 creates a variant; list_sites returns it."""
    resp = client.put("/sites/immobiliare-test1/config", json={"areas": ["bicocca", "centrale"], "search_wait_selector": "li.nd-list__item"})
    assert resp.status_code == 200
    resp2 = client.get("/sites")
    assert resp2.status_code == 200
    sites = resp2.json()
    assert "immobiliare" in sites
    assert "immobiliare-test1" in sites
    resp3 = client.get("/sites/immobiliare-test1/config")
    assert resp3.status_code == 200
    cfg = resp3.json()
    assert cfg.get("areas") == ["bicocca", "centrale"]
    assert cfg.get("search_wait_selector") == "li.nd-list__item"
    # Areas endpoint for variant
    resp4 = client.get("/sites/immobiliare-test1/areas")
    assert resp4.status_code == 200
    assert resp4.json() == ["bicocca", "centrale"]
