"""backend.routers.preferences — Read/write preferences.txt."""

import os
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


def _prefs_path() -> Path:
    # Read env var at call time (not import time) so dotenv loading order doesn't matter
    return Path(os.getenv("PREFERENCES_FILE", "data/preferences.txt"))


@router.get("")
def get_preferences():
    path = _prefs_path()
    if not path.exists():
        return {"content": "", "last_saved": None}
    mtime = datetime.utcfromtimestamp(path.stat().st_mtime).isoformat()
    return {"content": path.read_text(encoding="utf-8"), "last_saved": mtime}


class PrefsIn(BaseModel):
    content: str


@router.put("")
def save_preferences(data: PrefsIn):
    path = _prefs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data.content, encoding="utf-8")
    return {"status": "saved"}
