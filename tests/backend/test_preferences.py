# tests/backend/test_preferences.py
import os, tempfile
from pathlib import Path

# Point PREFERENCES_FILE to a temp file
tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
tmp.write(b"MUST HAVE:\n- 50+ sqm\n")
tmp.flush()
os.environ["DB_PATH"] = ":memory:"
os.environ["PREFERENCES_FILE"] = tmp.name

from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_get_preferences_returns_content():
    resp = client.get("/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert "content" in data
    assert "MUST HAVE" in data["content"]
    assert "last_saved" in data


def test_put_preferences_updates_file():
    new_content = "MUST HAVE:\n- 60+ sqm\n"
    resp = client.put("/preferences", json={"content": new_content})
    assert resp.status_code == 200
    assert resp.json()["status"] == "saved"

    # Verify file was actually written
    saved = Path(os.environ["PREFERENCES_FILE"]).read_text()
    assert "60+ sqm" in saved
