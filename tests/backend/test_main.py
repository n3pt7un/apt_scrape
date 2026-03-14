# tests/backend/test_main.py
import os
os.environ["DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
