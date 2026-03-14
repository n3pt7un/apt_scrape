# Streamlit + Docker Platform Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Streamlit frontend + FastAPI backend deployable as two Docker containers with scheduled apartment scraping, job monitoring, and editable LLM preferences — all backed by SQLite.

**Architecture:** FastAPI backend (port 8000) embeds APScheduler and imports `apt_scrape` directly via editable install from the mounted repo root; a `BrowserManager` singleton is kept alive across job runs (managed by FastAPI lifespan). Streamlit frontend (port 8501) calls the backend over HTTP using `httpx`. Both share `./data/` bind mount (SQLite + preferences.txt). The existing `apt_scrape/` package is **never modified**.

**Tech Stack:** FastAPI 0.115, APScheduler 3.10, SQLModel 0.0.21, uvicorn, Streamlit 1.42, httpx, Docker Compose v2, Python 3.12, camoufox (already in apt_scrape deps)

**Spec:** `docs/superpowers/specs/2026-03-14-streamlit-docker-frontend-design.md`

---

## Parallelism Map

Tasks within the same wave have no shared file dependencies and can be dispatched to parallel agents simultaneously.

```
Wave 1 ──► Task 1: Scaffolding
             │
Wave 2 ──────┼──► Task 2: db.py (SQLModel schema)
             └──► Task 3: main.py (FastAPI app + lifespan)
                         │
Wave 3 ──────────────────┼──► Task 4: configs router
                         ├──► Task 5: preferences router
                         └──► Task 6: jobs router
                                     │
Wave 4 ──────────────────────────────┼──► Task 7: runner.py (job pipeline)
                                     ├──► Task 9: Streamlit Configs page
                                     ├──► Task 10: Streamlit Monitor page
                                     └──► Task 11: Streamlit Preferences page
                                                   │
                                     Task 8: scheduler.py (depends on runner.py)
                                                   │
Wave 5 ──────────────────────────────────────────►Task 12: Integration test
```

---

## Chunk 1: Infrastructure + DB Schema

### Task 1: Project Scaffolding

**Files:**
- Create: `backend/Dockerfile`
- Create: `backend/requirements.txt`
- Create: `frontend/Dockerfile`
- Create: `frontend/requirements.txt`
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `data/.gitkeep`
- Modify: `.gitignore`

- [ ] **Step 1: Create `backend/requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.32.1
apscheduler==3.10.4
sqlmodel==0.0.21
aiofiles==24.1.0
python-dotenv==1.0.1
httpx==0.28.1
```

- [ ] **Step 2: Create `backend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Install the apt_scrape package (editable) from repo root (mounted as /workspace)
COPY requirements.txt /tmp/apt_requirements.txt
RUN pip install --no-cache-dir -r /tmp/apt_requirements.txt

# Install camoufox browser binary
RUN pip install camoufox && python -m camoufox fetch

# Install backend dependencies
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

ENV PYTHONPATH=/workspace
ENV DB_PATH=/data/app.db
ENV PREFERENCES_FILE=/data/preferences.txt

WORKDIR /workspace
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Create `frontend/requirements.txt`**

```
streamlit==1.42.0
httpx==0.28.1
```

- [ ] **Step 4: Create `frontend/Dockerfile`**

```dockerfile
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

COPY frontend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY frontend/ /app/

ENV BACKEND_URL=http://backend:8000

WORKDIR /app
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

- [ ] **Step 5: Create `docker-compose.yml`**

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    volumes:
      - .:/workspace          # repo root → apt_scrape importable via PYTHONPATH
      - ./data:/data          # SQLite + preferences.txt
    env_file: .env
    environment:
      - PYTHONPATH=/workspace
      - DB_PATH=/data/app.db
      - PREFERENCES_FILE=/data/preferences.txt
    ports:
      - "8000:8000"
    restart: unless-stopped

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    ports:
      - "8501:8501"
    environment:
      - BACKEND_URL=http://backend:8000
    depends_on:
      - backend
    restart: unless-stopped
```

- [ ] **Step 6: Create `.env.example`**

```bash
# LLM / Analysis
OPENROUTER_API_KEY=
OPENROUTER_MODEL=google/gemini-2.0-flash-lite

# Notion (required if auto_notion_push enabled)
NOTION_API_KEY=
NOTION_APARTMENTS_DB_ID=
NOTION_AREAS_DB_ID=
NOTION_AGENCIES_DB_ID=

# Optional NordVPN proxy
# NORDVPN_USER=
# NORDVPN_PASS=
# NORDVPN_SERVERS=
```

- [ ] **Step 7: Create `data/.gitkeep` and update `.gitignore`**

```bash
mkdir -p data && touch data/.gitkeep
```

Append to `.gitignore` (use `>>` to avoid clobbering existing entries):
```bash
cat >> .gitignore << 'EOF'
data/app.db
data/preferences.txt
data/results/
.env
.superpowers/
EOF
```

- [ ] **Step 8: Create stub `backend/__init__.py` and `backend/routers/__init__.py`**

```bash
mkdir -p backend/routers
touch backend/__init__.py backend/routers/__init__.py
```

- [ ] **Step 9: Commit scaffolding**

```bash
git add backend/ frontend/ docker-compose.yml .env.example data/.gitkeep .gitignore
git commit -m "feat: add Docker + project scaffolding for streamlit platform"
```

---

### Task 2: SQLite Schema (`backend/db.py`)

**Files:**
- Create: `backend/db.py`
- Create: `tests/backend/__init__.py`
- Create: `tests/backend/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test — expect ImportError (backend/db.py doesn't exist yet)**

```bash
cd /path/to/apt_scrape && python -m pytest tests/backend/test_db.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'backend'`

- [ ] **Step 3: Create `backend/db.py`**

```python
"""backend.db — SQLModel table definitions and DB engine setup."""

import json
import os
from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine, select

DB_PATH = os.getenv("DB_PATH", "data/app.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


class SearchConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    city: str
    area: Optional[str] = None
    operation: str = "affitto"
    property_type: str = "appartamenti"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_sqm: Optional[int] = None
    min_rooms: Optional[int] = None
    start_page: int = 1
    end_page: int = 10
    schedule_days: str = '[]'       # JSON array: ["mon","wed","fri"]
    schedule_time: str = "08:00"    # HH:MM 24h UTC
    detail_concurrency: int = 5
    vpn_rotate_batches: int = 3
    auto_analyse: bool = True
    auto_notion_push: bool = False
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    config_id: int = Field(foreign_key="searchconfig.id")
    status: str = "pending"         # pending / running / done / failed
    triggered_by: str = "schedule"  # schedule / manual
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    listing_count: Optional[int] = None
    log: str = ""


class Listing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(unique=True, index=True)
    job_id: int = Field(foreign_key="job.id")
    config_id: int = Field(foreign_key="searchconfig.id")
    title: str = ""
    price: str = ""
    sqm: str = ""
    rooms: str = ""
    area: str = ""
    city: str = ""
    ai_score: Optional[int] = None
    ai_verdict: Optional[str] = None
    notion_page_id: Optional[str] = None
    raw_json: str = "{}"
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


def create_db_and_tables() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yield a DB session per request."""
    with Session(engine) as session:
        yield session
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
python -m pytest tests/backend/test_db.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/db.py tests/backend/
git commit -m "feat(backend): add SQLModel schema for search_configs, jobs, listings"
```

---

## Chunk 2: Backend API Core

> **Parallel signal:** Tasks 3 (main.py) runs first. Tasks 4, 5, 6 are independent of each other and can run in parallel once Task 3 is done.

### Task 3: FastAPI App Entry (`backend/main.py`)

**Files:**
- Create: `backend/main.py`
- Create: `tests/backend/test_main.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
python -m pytest tests/backend/test_main.py -v 2>&1 | head -20
```

- [ ] **Step 3: Create `backend/main.py`**

```python
"""backend.main — FastAPI application entry point."""

import contextlib
import logging

from fastapi import FastAPI

from backend.db import create_db_and_tables
from backend.routers import configs, jobs, preferences

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables, start scheduler. Shutdown: stop scheduler."""
    create_db_and_tables()
    from backend.scheduler import start_scheduler, stop_scheduler
    await start_scheduler()
    yield
    await stop_scheduler()
    # Close browser singleton on shutdown
    try:
        from apt_scrape.server import browser
        await browser.close()
    except Exception:
        pass


app = FastAPI(title="apt_scrape backend", lifespan=lifespan)

app.include_router(configs.router, prefix="/configs", tags=["configs"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(preferences.router, prefix="/preferences", tags=["preferences"])


@app.get("/health")
async def health():
    return {"status": "ok"}
```

- [ ] **Step 4: Create stub routers so app imports don't fail**

```python
# backend/routers/configs.py
from fastapi import APIRouter
router = APIRouter()

# backend/routers/jobs.py
from fastapi import APIRouter
router = APIRouter()

# backend/routers/preferences.py
from fastapi import APIRouter
router = APIRouter()
```

Also create stub `backend/scheduler.py`:
```python
# backend/scheduler.py
async def start_scheduler(): pass
async def stop_scheduler(): pass
def reload_config(config_id: int): pass
def trigger_now(config_id: int) -> int: return config_id
```

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/backend/test_main.py -v
```

Expected: 1 test PASS

- [ ] **Step 6: Commit**

```bash
git add backend/main.py backend/scheduler.py backend/routers/
git commit -m "feat(backend): FastAPI app entry with lifespan and stub routers"
```

---

### Task 4: Configs Router (`backend/routers/configs.py`)

> **Parallel-safe after Task 3.** No shared files with Tasks 5 or 6.

**Files:**
- Modify: `backend/routers/configs.py`
- Create: `tests/backend/test_configs.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests — expect 404/422 (stubs return nothing)**

```bash
python -m pytest tests/backend/test_configs.py -v 2>&1 | head -40
```

- [ ] **Step 3: Implement `backend/routers/configs.py`**

```python
"""backend.routers.configs — CRUD for search_configs."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.db import SearchConfig, get_session
from backend import scheduler

router = APIRouter()


class ConfigIn(BaseModel):
    name: str
    city: str
    area: Optional[str] = None
    operation: str = "affitto"
    property_type: str = "appartamenti"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_sqm: Optional[int] = None
    min_rooms: Optional[int] = None
    start_page: int = 1
    end_page: int = 10
    schedule_days: list[str] = []
    schedule_time: str = "08:00"
    detail_concurrency: int = 5
    vpn_rotate_batches: int = 3
    auto_analyse: bool = True
    auto_notion_push: bool = False
    enabled: bool = True


def _to_response(cfg: SearchConfig) -> dict:
    d = cfg.model_dump()
    d["schedule_days"] = json.loads(cfg.schedule_days or "[]")
    return d


@router.get("")
def list_configs(session: Session = Depends(get_session)):
    return [_to_response(c) for c in session.exec(select(SearchConfig)).all()]


@router.post("", status_code=201)
def create_config(data: ConfigIn, session: Session = Depends(get_session)):
    cfg = SearchConfig(**{**data.model_dump(), "schedule_days": json.dumps(data.schedule_days)})
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    scheduler.reload_config(cfg.id)
    return _to_response(cfg)


@router.get("/{config_id}")
def get_config(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    return _to_response(cfg)


@router.put("/{config_id}")
def update_config(config_id: int, data: ConfigIn, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    for k, v in data.model_dump().items():
        if k == "schedule_days":
            setattr(cfg, k, json.dumps(v))
        else:
            setattr(cfg, k, v)
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    scheduler.reload_config(cfg.id)
    return _to_response(cfg)


@router.delete("/{config_id}", status_code=204)
def delete_config(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    session.delete(cfg)
    session.commit()
    scheduler.reload_config(config_id)
    return Response(status_code=204)


@router.patch("/{config_id}/toggle")
def toggle_config(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    cfg.enabled = not cfg.enabled
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    scheduler.reload_config(cfg.id)
    return _to_response(cfg)


@router.post("/{config_id}/run")
def run_config_now(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    job_id = scheduler.trigger_now(config_id)
    return {"job_id": job_id}
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backend/test_configs.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/configs.py tests/backend/test_configs.py
git commit -m "feat(backend): configs CRUD router with scheduler hooks"
```

---

### Task 5: Preferences Router (`backend/routers/preferences.py`)

> **Parallel-safe after Task 3.** No shared files with Tasks 4 or 6.

**Files:**
- Modify: `backend/routers/preferences.py`
- Create: `tests/backend/test_preferences.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests — expect failures (stub router)**

```bash
python -m pytest tests/backend/test_preferences.py -v
```

- [ ] **Step 3: Implement `backend/routers/preferences.py`**

```python
"""backend.routers.preferences — Read/write preferences.txt."""

import os
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backend/test_preferences.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/routers/preferences.py tests/backend/test_preferences.py
git commit -m "feat(backend): preferences router for reading/writing preferences.txt"
```

---

### Task 6: Jobs Router (`backend/routers/jobs.py`)

> **Parallel-safe after Task 3.** No shared files with Tasks 4 or 5.

**Files:**
- Modify: `backend/routers/jobs.py`
- Create: `tests/backend/test_jobs.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests — expect failures**

```bash
python -m pytest tests/backend/test_jobs.py -v
```

- [ ] **Step 3: Implement `backend/routers/jobs.py`**

```python
"""backend.routers.jobs — Job status and log retrieval."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from backend.db import Job, get_session

router = APIRouter()


@router.get("")
def list_jobs(config_id: Optional[int] = None, session: Session = Depends(get_session)):
    stmt = select(Job).order_by(Job.started_at.desc()).limit(50)
    if config_id is not None:
        stmt = stmt.where(Job.config_id == config_id)
    jobs = session.exec(stmt).all()
    return [j.model_dump() for j in jobs]


@router.get("/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.model_dump()
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backend/test_jobs.py -v
```

Expected: 4 tests PASS

- [ ] **Step 5: Run all backend tests together**

```bash
python -m pytest tests/backend/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/routers/jobs.py tests/backend/test_jobs.py
git commit -m "feat(backend): jobs router with listing and detail endpoints"
```

---

## Chunk 3: Job Runner + Scheduler

### Task 7: Job Runner (`backend/runner.py`)

**Files:**
- Create: `backend/runner.py`
- Create: `tests/backend/test_runner.py`

> The runner replicates `apt_scrape/cli.py`'s `_run_search()` core loop but **never calls `browser.close()`** — the browser stays alive across job runs, managed by FastAPI lifespan.

- [ ] **Step 1: Write failing tests (using mocks for apt_scrape calls)**

```python
# tests/backend/test_runner.py
import os, json
os.environ["DB_PATH"] = ":memory:"

from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel import Session
from backend.db import create_db_and_tables, engine, SearchConfig, Job

create_db_and_tables()


def _make_config():
    with Session(engine) as s:
        cfg = SearchConfig(
            name="Test", city="milano", area="bicocca", operation="affitto",
            property_type="appartamenti", min_price=700, max_price=1000,
            min_sqm=55, min_rooms=2, start_page=1, end_page=2,
            schedule_days='["mon"]', schedule_time="08:00",
            detail_concurrency=3, vpn_rotate_batches=2,
            auto_analyse=False, auto_notion_push=False,
        )
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def _make_fake_listing(url="https://example.com/1"):
    m = MagicMock()
    m.to_dict.return_value = {"url": url, "title": "Test apt", "price": "€900"}
    return m


import asyncio


def test_run_config_job_creates_job_record():
    config_id = _make_config()
    logs = []

    fake_html = "<html></html>"
    fake_listings = [_make_fake_listing()]

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter") as mock_get_adapter,
        patch("backend.runner.enrich_with_details", new_callable=AsyncMock) as mock_enrich,
        patch("backend.runner.enrich_post_dates", new_callable=AsyncMock) as mock_post_dates,
    ):
        mock_browser.fetch_page = AsyncMock(return_value=fake_html)
        mock_adapter = MagicMock()
        mock_adapter.build_search_url.return_value = "https://example.com/search"
        mock_adapter.parse_search.return_value = fake_listings
        mock_adapter.config.search_wait_selector = None
        mock_get_adapter.return_value = mock_adapter
        mock_enrich.return_value = (1, [])
        mock_post_dates.return_value = (0, [])

        job_id = asyncio.run(
            backend_runner_run(config_id, logs.append)
        )

    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.listing_count == 1
        assert job.config_id == config_id


# Import after mocks are set up
import backend.runner as backend_runner_module
backend_runner_run = backend_runner_module.run_config_job
```

- [ ] **Step 2: Run test — expect ImportError**

```bash
python -m pytest tests/backend/test_runner.py -v 2>&1 | head -20
```

- [ ] **Step 3: Implement `backend/runner.py`**

```python
"""backend.runner — Core job execution pipeline.

Replicates the core of apt_scrape.cli._run_search() without using the CLI
wrapper, so the browser singleton is NOT closed between job runs.

Pipeline order (matches spec):
  scrape → enrich → post_dates → stamp → analyse → notion_push → upsert
"""

import json
import logging
import os
from datetime import datetime
from typing import Callable

from sqlmodel import Session

from apt_scrape.enrichment import enrich_post_dates, enrich_with_details
from apt_scrape.server import browser
from apt_scrape.sites import SearchFilters, get_adapter, list_adapters

logger = logging.getLogger(__name__)

PREFERENCES_FILE = os.getenv("PREFERENCES_FILE", "data/preferences.txt")


def _normalize_slug(value: str) -> str:
    return value.lower().replace(" ", "-")


def _parse_property_types(raw: str) -> list[str]:
    types = [p.strip() for p in raw.split(",") if p.strip()]
    return types or ["appartamenti"]


async def run_config_job(
    config_id: int,
    log_fn: Callable[[str], None],
    existing_job_id: int | None = None,
) -> int:
    """Execute a scraping job for the given config. Returns job_id.

    If `existing_job_id` is provided (from `trigger_now`), reuses that job
    record (already created as "pending"). Otherwise creates a new one.
    Does NOT close the browser — caller manages browser lifecycle.

    NOTE: `from apt_scrape.server import browser` works because `server.py`
    defines a module-level `browser = BrowserManager()` singleton (same
    instance cli.py imports). Verify this exists at the bottom of server.py
    before running; if absent, add `browser = BrowserManager()` there.
    """
    from backend.db import Job, Listing, SearchConfig, engine

    # --- 1. Create or update job record ---
    with Session(engine) as session:
        cfg = session.get(SearchConfig, config_id)
        if not cfg:
            raise ValueError(f"SearchConfig {config_id} not found")

        if existing_job_id is not None:
            job = session.get(Job, existing_job_id)
            job.status = "running"
            session.add(job)
            session.commit()
            job_id = existing_job_id
        else:
            job = Job(config_id=config_id, status="running", triggered_by="schedule")
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id

    def _log(msg: str) -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        log_fn(line)
        with Session(engine) as s:
            j = s.get(Job, job_id)
            if j:
                j.log = (j.log or "") + line + "\n"
                s.add(j)
                s.commit()

    try:
        with Session(engine) as session:
            cfg = session.get(SearchConfig, config_id)
            # MVP: always uses the first registered adapter (Immobiliare.it).
            # SearchConfig has no site field. Multi-site selection is a future extension.
            source = list_adapters()[0]
            adapter = get_adapter(source)
            city_slug = _normalize_slug(cfg.city)
            area_slug = _normalize_slug(cfg.area) if cfg.area else None
            property_types = _parse_property_types(cfg.property_type)

        # --- 2. Scrape search pages ---
        all_listings: list[dict] = []
        for pt in property_types:
            for page_num in range(cfg.start_page, cfg.end_page + 1):
                filters = SearchFilters(
                    city=city_slug,
                    area=area_slug,
                    operation=cfg.operation,
                    property_type=pt,
                    min_price=cfg.min_price,
                    max_price=cfg.max_price,
                    min_sqm=cfg.min_sqm,
                    min_rooms=cfg.min_rooms,
                    page=page_num,
                )
                url = adapter.build_search_url(filters)
                _log(f"Fetching {pt} page {page_num}: {url}")
                html = await browser.fetch_page(url, wait_selector=adapter.config.search_wait_selector)
                page_listings = adapter.parse_search(html)
                if not page_listings:
                    _log(f"No listings on page {page_num}, stopping.")
                    break
                all_listings.extend([ls.to_dict() for ls in page_listings])
                _log(f"  -> {len(page_listings)} listings")

        # Deduplicate by URL
        seen: set[str] = set()
        deduped: list[dict] = []
        for listing in all_listings:
            key = str(listing.get("url", "")).strip()
            if key and key not in seen:
                seen.add(key)
                deduped.append(listing)

        _log(f"Total unique listings: {len(deduped)}")

        # --- 3. Enrich details ---
        _log(f"Enriching details (concurrency={cfg.detail_concurrency})...")
        await enrich_with_details(
            deduped, browser, adapter, None,
            concurrency=cfg.detail_concurrency,
            rotate_every_batches=cfg.vpn_rotate_batches,
        )

        # --- 4. Enrich post dates ---
        await enrich_post_dates(deduped, browser, adapter,
                                concurrency=cfg.detail_concurrency,
                                rotate_every_batches=cfg.vpn_rotate_batches)

        # --- 5. Stamp area/city ---
        for listing in deduped:
            listing["_area"] = area_slug or ""
            listing["_city"] = city_slug

        # --- 6. AI Analysis ---
        if cfg.auto_analyse and deduped:
            _log("Running AI analysis...")
            from apt_scrape.analysis import analyse_listings, load_preferences
            try:
                prefs = load_preferences()
                await analyse_listings(deduped, prefs)
                _log("Analysis complete.")
            except FileNotFoundError:
                _log("[warn] preferences.txt not found — skipping analysis.")

        # --- 7. Notion Push ---
        if cfg.auto_notion_push and deduped:
            _log("Pushing to Notion...")
            from apt_scrape.notion_push import push_listings
            await push_listings(deduped)
            _log("Notion push complete.")

        # --- 8. Upsert listings to DB ---
        _log("Upserting listings to DB...")
        with Session(engine) as session:
            for listing in deduped:
                url = str(listing.get("url", "")).strip()
                if not url:
                    continue
                existing = session.exec(
                    __import__("sqlmodel").select(Listing).where(Listing.url == url)
                ).first()
                row_data = dict(
                    url=url,
                    job_id=job_id,
                    config_id=config_id,
                    title=listing.get("title", ""),
                    price=listing.get("price", ""),
                    sqm=listing.get("sqm", ""),
                    rooms=listing.get("rooms", ""),
                    area=area_slug or "",
                    city=city_slug,
                    ai_score=listing.get("ai_score"),
                    ai_verdict=listing.get("ai_verdict"),
                    notion_page_id=listing.get("notion_page_id"),
                    raw_json=json.dumps(listing, ensure_ascii=False),
                    scraped_at=datetime.utcnow(),
                )
                if existing:
                    for k, v in row_data.items():
                        setattr(existing, k, v)
                    session.add(existing)
                else:
                    session.add(Listing(**row_data))
            session.commit()

        # --- 9. Mark job done ---
        with Session(engine) as session:
            job = session.get(Job, job_id)
            job.status = "done"
            job.finished_at = datetime.utcnow()
            job.listing_count = len(deduped)
            session.add(job)
            session.commit()

        _log(f"Job complete. {len(deduped)} listings processed.")
        return job_id

    except Exception as exc:
        logger.exception("Job %d failed", job_id)
        _log(f"[ERROR] {exc}")
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job:
                job.status = "failed"
                job.finished_at = datetime.utcnow()
                session.add(job)
                session.commit()
        return job_id
```

- [ ] **Step 4: Fix the `__import__("sqlmodel")` antipattern** — replace inline import in upsert loop:

Add `from sqlmodel import select as sql_select` at the top of the file, then change the upsert lookup to use `sql_select`.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/backend/test_runner.py -v
```

Expected: 1 test PASS

- [ ] **Step 6: Commit**

```bash
git add backend/runner.py tests/backend/test_runner.py
git commit -m "feat(backend): job runner pipeline (scrape → enrich → analyse → push → upsert)"
```

---

### Task 8: Scheduler (`backend/scheduler.py`)

> Depends on Task 7 (runner.py). Can run in parallel with Streamlit page tasks (Tasks 9–11).

**Files:**
- Modify: `backend/scheduler.py`
- Create: `tests/backend/test_scheduler.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/backend/test_scheduler.py
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


def _seed_disabled_config():
    with Session(engine) as s:
        cfg = SearchConfig(
            name="Off", city="roma", area=None, operation="affitto",
            property_type="appartamenti", schedule_days='["tue"]',
            schedule_time="09:00", enabled=False,
        )
        s.add(cfg)
        s.commit()
        s.refresh(cfg)
        return cfg.id


def test_trigger_now_creates_background_task():
    enabled_id = _seed_enabled_config()

    with patch("backend.scheduler.run_config_job", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = 42  # fake job_id

        import backend.scheduler as sched
        job_id = sched.trigger_now(enabled_id)
        # trigger_now should return an int (job created or pending)
        assert isinstance(job_id, int)


def test_reload_config_does_not_raise_for_unknown_id():
    import backend.scheduler as sched
    # Should not raise even if config doesn't exist yet
    sched.reload_config(99999)
```

- [ ] **Step 2: Run tests — expect failures**

```bash
python -m pytest tests/backend/test_scheduler.py -v 2>&1 | head -30
```

- [ ] **Step 3: Implement `backend/scheduler.py`**

```python
"""backend.scheduler — APScheduler setup and job management."""

import asyncio
import json
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from backend.db import Job, SearchConfig, engine
from backend.runner import run_config_job

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")

# Maps day abbreviations to APScheduler day_of_week format
DAY_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
}


def _make_job_id(config_id: int) -> str:
    return f"config_{config_id}"


def _build_trigger(schedule_days: list[str], schedule_time: str) -> CronTrigger:
    """Build a CronTrigger from day list and HH:MM time string (UTC)."""
    days_str = ",".join(DAY_MAP.get(d, d) for d in schedule_days) or "*"
    hour, minute = schedule_time.split(":")
    return CronTrigger(day_of_week=days_str, hour=int(hour), minute=int(minute), timezone="UTC")


async def _run_job_wrapper(config_id: int) -> None:
    """Wrapper called by APScheduler — runs in the event loop."""
    logs = []
    try:
        await run_config_job(config_id, logs.append)
    except Exception:
        logger.exception("Unhandled error in job for config %d", config_id)


async def start_scheduler() -> None:
    """Load all enabled configs and start APScheduler."""
    with Session(engine) as session:
        configs = session.exec(select(SearchConfig).where(SearchConfig.enabled == True)).all()

    for cfg in configs:
        days = json.loads(cfg.schedule_days or "[]")
        if not days:
            continue
        trigger = _build_trigger(days, cfg.schedule_time)
        _scheduler.add_job(
            _run_job_wrapper,
            trigger=trigger,
            args=[cfg.id],
            id=_make_job_id(cfg.id),
            replace_existing=True,
            coalesce=True,
            max_instances=1,
        )
        logger.info("Scheduled config %d (%s) at %s on %s", cfg.id, cfg.name, cfg.schedule_time, days)

    _scheduler.start()
    logger.info("Scheduler started with %d jobs.", len(_scheduler.get_jobs()))


async def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


def reload_config(config_id: int) -> None:
    """Re-read a single config from DB and update its APScheduler job."""
    if not _scheduler.running:
        return
    job_id = _make_job_id(config_id)
    # Remove existing job (ignore if not found)
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = session.get(SearchConfig, config_id)

    if cfg is None or not cfg.enabled:
        return  # Deleted or disabled — job removed above, done.

    days = json.loads(cfg.schedule_days or "[]")
    if not days:
        return

    trigger = _build_trigger(days, cfg.schedule_time)
    _scheduler.add_job(
        _run_job_wrapper,
        trigger=trigger,
        args=[cfg.id],
        id=job_id,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Reloaded schedule for config %d", config_id)


def trigger_now(config_id: int) -> int:
    """Trigger an immediate run of a config. Returns the real job_id.

    Creates a Job record synchronously (in the calling thread) so the job_id
    is available immediately for the API response. Then fires the async pipeline
    as a background task.
    """
    from datetime import datetime
    from backend.db import Job, engine
    from sqlmodel import Session

    # Create the job record synchronously so we can return a real job_id
    with Session(engine) as session:
        job = Job(config_id=config_id, status="pending", triggered_by="manual")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    async def _run():
        from backend.runner import run_config_job
        await run_config_job(config_id, lambda msg: None, existing_job_id=job_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())

    return job_id
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/backend/test_scheduler.py -v
```

Expected: 2 tests PASS

- [ ] **Step 5: Run full backend test suite**

```bash
python -m pytest tests/backend/ -v
```

Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/scheduler.py tests/backend/test_scheduler.py
git commit -m "feat(backend): APScheduler with CronTrigger per search config"
```

---

## Chunk 4: Streamlit Frontend

> **Parallel signal:** Tasks 9, 10, 11 have no shared files and can be dispatched to parallel agents. They depend on the backend API being complete (Chunks 2–3), but the Streamlit pages can be built against the API contract defined in the spec without the backend running.

### Task 9: App Entry + Search Configs Page (`frontend/app.py` + `frontend/pages/1_Search_Configs.py`)

**Files:**
- Create: `frontend/app.py`
- Create: `frontend/pages/1_Search_Configs.py`
- Create: `frontend/api.py`  ← shared HTTP client (used by all pages)

- [ ] **Step 1: Create `frontend/api.py` — thin HTTP wrapper around backend**

```python
"""frontend.api — HTTP client for the apt_scrape backend."""

import os
import httpx

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def get(path: str, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.get(path, **kwargs)
        resp.raise_for_status()
        return resp.json()


def post(path: str, json=None, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.post(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()


def put(path: str, json=None, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.put(path, json=json, **kwargs)
        resp.raise_for_status()
        return resp.json()


def patch(path: str, **kwargs) -> dict:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.patch(path, **kwargs)
        resp.raise_for_status()
        return resp.json()


def delete(path: str, **kwargs) -> None:
    with httpx.Client(base_url=BACKEND_URL, timeout=30) as client:
        resp = client.delete(path, **kwargs)
        resp.raise_for_status()
```

- [ ] **Step 2: Create `frontend/app.py`**

```python
"""frontend.app — Streamlit multi-page app entry point."""
import streamlit as st

st.set_page_config(
    page_title="apt_scrape",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏠 apt_scrape")
st.write("Use the sidebar to navigate between pages.")
```

- [ ] **Step 3: Create `frontend/pages/1_Search_Configs.py`**

```python
"""Streamlit page: Search Configurations."""
import json
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Search Configs", page_icon="⚙️", layout="wide")
st.title("⚙️ Search Configurations")

# --- Load configs ---
try:
    configs = api.get("/configs")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

# --- Config table ---
if configs:
    for cfg in configs:
        days = cfg.get("schedule_days", [])
        schedule_str = f"{', '.join(d.capitalize() for d in days)} at {cfg.get('schedule_time','')}"
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            with col1:
                st.markdown(f"**{cfg['name']}** — {cfg.get('city','')} / {cfg.get('area','')}")
                st.caption(f"{cfg.get('operation','')} · {cfg.get('min_price','')}–{cfg.get('max_price','')}€ · {schedule_str}")
            with col2:
                status = "🟢 enabled" if cfg["enabled"] else "⚫ disabled"
                st.write(status)
                if cfg.get("auto_analyse"):
                    st.caption("🤖 AI on")
                if cfg.get("auto_notion_push"):
                    st.caption("📝 Notion auto")
            with col3:
                if st.button("▶ Run now", key=f"run_{cfg['id']}"):
                    try:
                        result = api.post(f"/configs/{cfg['id']}/run")
                        st.success(f"Job started!")
                        st.switch_page("pages/2_Monitor.py")
                    except Exception as e:
                        st.error(str(e))
                if st.button("⏸ Toggle", key=f"tog_{cfg['id']}"):
                    try:
                        api.patch(f"/configs/{cfg['id']}/toggle")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with col4:
                if st.button("🗑 Delete", key=f"del_{cfg['id']}"):
                    try:
                        api.delete(f"/configs/{cfg['id']}")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
else:
    st.info("No search configs yet. Create one below.")

st.divider()

# --- New / Edit Config Form ---
st.subheader("New Search Config")

with st.form("new_config"):
    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Config name", placeholder="Milano · Bicocca")
        city = st.text_input("City slug", value="milano")
        area = st.text_input("Area slug (optional)", placeholder="bicocca")
        operation = st.selectbox("Operation", ["affitto", "vendita"])
        property_type = st.text_input("Property types (comma-separated)", value="appartamenti,attici")
    with c2:
        min_price, max_price = st.slider("Price range (€)", 0, 5000, (700, 1200), step=50)
        min_sqm = st.number_input("Min sqm", min_value=0, value=50, step=5)
        min_rooms = st.selectbox("Min rooms", [1, 2, 3, 4, 5], index=1)
        start_page = st.number_input("Start page", min_value=1, value=1)
        end_page = st.number_input("End page", min_value=1, value=10)

    st.markdown("**Schedule**")
    sc1, sc2 = st.columns(2)
    with sc1:
        schedule_days = st.multiselect(
            "Days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            default=["mon", "wed", "fri"]
        )
    with sc2:
        schedule_time = st.time_input("Time (UTC)", value=None)

    st.markdown("**Rate limits & toggles**")
    rl1, rl2, rl3, rl4 = st.columns(4)
    with rl1:
        detail_concurrency = st.slider("Detail concurrency", 1, 10, 5)
    with rl2:
        vpn_rotate_batches = st.slider("VPN rotate batches", 1, 10, 3)
    with rl3:
        auto_analyse = st.toggle("AI analysis", value=True)
    with rl4:
        auto_notion_push = st.toggle("Notion auto-push", value=False)

    submitted = st.form_submit_button("Save Config")
    if submitted:
        time_str = schedule_time.strftime("%H:%M") if schedule_time else "08:00"
        payload = {
            "name": name, "city": city, "area": area or None,
            "operation": operation, "property_type": property_type,
            "min_price": min_price, "max_price": max_price,
            "min_sqm": min_sqm, "min_rooms": min_rooms,
            "start_page": start_page, "end_page": end_page,
            "schedule_days": schedule_days,
            "schedule_time": time_str,
            "detail_concurrency": detail_concurrency,
            "vpn_rotate_batches": vpn_rotate_batches,
            "auto_analyse": auto_analyse,
            "auto_notion_push": auto_notion_push,
            "enabled": True,
        }
        try:
            api.post("/configs", json=payload)
            st.success("Config saved!")
            st.rerun()
        except Exception as e:
            st.error(str(e))
```

- [ ] **Step 4: Manually verify (no unit tests for Streamlit pages)**

Start backend locally:
```bash
DB_PATH=data/app.db PREFERENCES_FILE=data/preferences.txt uvicorn backend.main:app --reload
```

In a second terminal:
```bash
BACKEND_URL=http://localhost:8000 streamlit run frontend/app.py
```

Open http://localhost:8501 → navigate to Search Configs → create a config → verify it appears in the list.

- [ ] **Step 5: Commit**

```bash
git add frontend/
git commit -m "feat(frontend): Streamlit app entry, api client, Search Configs page"
```

---

### Task 10: Monitor Page (`frontend/pages/2_Monitor.py`)

> **Parallel-safe with Task 9 and Task 11.**

**Files:**
- Create: `frontend/pages/2_Monitor.py`

- [ ] **Step 1: Create `frontend/pages/2_Monitor.py`**

```python
"""Streamlit page: Job Monitor."""
import time
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Monitor", page_icon="📡", layout="wide")
st.title("📡 Job Monitor")

STATUS_COLORS = {
    "running": "🟡",
    "done": "🟢",
    "failed": "🔴",
    "pending": "⚪",
}

# Auto-refresh placeholder
refresh_placeholder = st.empty()

def render():
    try:
        jobs = api.get("/jobs")
    except Exception as e:
        st.error(f"Cannot reach backend: {e}")
        return

    running = [j for j in jobs if j["status"] == "running"]
    recent = [j for j in jobs if j["status"] != "running"]

    if running:
        st.subheader("Active Jobs")
        for job in running:
            with st.container(border=True):
                st.markdown(f"{STATUS_COLORS['running']} **Job #{job['id']}** — config {job['config_id']} — `running`")
                st.caption(f"Started: {job.get('started_at', '—')}")
                # Show last 10 log lines
                log_lines = (job.get("log") or "").strip().split("\n")
                st.code("\n".join(log_lines[-10:]), language=None)
    else:
        st.info("No jobs currently running.")

    st.subheader("Recent Jobs")
    if recent:
        for job in recent:
            icon = STATUS_COLORS.get(job["status"], "⚪")
            with st.expander(
                f"{icon} Job #{job['id']} — config {job['config_id']} — `{job['status']}` — {job.get('listing_count', 0)} listings — {job.get('finished_at', '')}",
                expanded=False,
            ):
                try:
                    detail = api.get(f"/jobs/{job['id']}")
                    st.code(detail.get("log", "(no log)"), language=None)
                except Exception as e:
                    st.error(str(e))
    else:
        st.info("No completed jobs yet.")

render()

# Auto-refresh every 5 seconds
time.sleep(5)
st.rerun()
```

- [ ] **Step 2: Manually verify**

Trigger a job from the Configs page (or via `POST /configs/{id}/run`). Open Monitor page — confirm it shows the running job, live log tail, and auto-refreshes.

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/2_Monitor.py
git commit -m "feat(frontend): Monitor page with 5s auto-refresh and log display"
```

---

### Task 11: Preferences Page (`frontend/pages/3_Preferences.py`)

> **Parallel-safe with Tasks 9 and 10.**

**Files:**
- Create: `frontend/pages/3_Preferences.py`

- [ ] **Step 1: Create `frontend/pages/3_Preferences.py`**

```python
"""Streamlit page: LLM Evaluation Preferences."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Preferences", page_icon="🧠", layout="wide")
st.title("🧠 LLM Evaluation Preferences")
st.caption("This text is passed to the AI to score listings 0–100. Changes take effect on the next job run.")

try:
    prefs_data = api.get("/preferences")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

content = prefs_data.get("content", "")
last_saved = prefs_data.get("last_saved")

if last_saved:
    st.caption(f"Last saved: {last_saved} UTC")

new_content = st.text_area(
    "Preferences",
    value=content,
    height=400,
    label_visibility="collapsed",
    help="Describe must-haves, nice-to-haves, and deal-breakers.",
)

if st.button("💾 Save Preferences", type="primary"):
    try:
        api.put("/preferences", json={"content": new_content})
        st.success("Preferences saved! They will be used on the next scrape run.")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to save: {e}")
```

- [ ] **Step 2: Manually verify**

Open http://localhost:8501/Preferences → confirm text area loads existing content → edit → save → confirm `data/preferences.txt` was updated on disk.

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/3_Preferences.py
git commit -m "feat(frontend): Preferences page with editable text area and save"
```

---

## Chunk 5: Docker Integration

### Task 12: Docker Compose Smoke Test

**Files:**
- Modify: `.gitignore` (ensure `data/app.db` and `.env` are ignored)
- Create: `data/preferences.txt` (seed file for first run)

- [ ] **Step 1: Create seed `data/preferences.txt`** (if not already there from existing repo)

```bash
cp preferences.txt data/preferences.txt
```

- [ ] **Step 2: Create `.env` from `.env.example`**

```bash
cp .env.example .env
# Fill in OPENROUTER_API_KEY (required for analyse), Notion keys (optional)
```

- [ ] **Step 3: Build and start containers**

```bash
docker compose up --build -d
```

Expected: both services start, no build errors.

- [ ] **Step 4: Verify backend health**

```bash
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 5: Verify Streamlit loads**

Open http://localhost:8501 in browser. Navigate to all 3 pages — no errors.

- [ ] **Step 6: Create a config and run it**

Via the Streamlit UI:
1. Go to Search Configs → create a minimal config (1 page, small area)
2. Click "▶ Run now"
3. Monitor page — confirm job appears as running, then done
4. Verify: `sqlite3 data/app.db "select count(*) from listing;"` returns > 0

- [ ] **Step 7: Verify persistence across restart**

```bash
docker compose down && docker compose up -d
curl http://localhost:8000/configs   # configs should still be there
```

- [ ] **Step 8: Stop containers**

```bash
docker compose down
```

- [ ] **Step 9: Final commit**

```bash
git add data/preferences.txt .env.example
git commit -m "feat: complete streamlit+docker platform — end-to-end integration verified"
```

---

## Notes for Implementers

### Browser Lifecycle
The `BrowserManager` singleton (`from apt_scrape.server import browser`) lazily starts Camoufox on first `await browser.fetch_page()` call. FastAPI's lifespan calls `await browser.close()` on shutdown. **Never call `browser.close()` inside `runner.py`** — it would terminate the browser for all subsequent jobs.

### Timezone for Scheduler
APScheduler runs in UTC (`timezone="UTC"`). All `schedule_time` values in the DB are interpreted as UTC. Document this clearly for users in the UI.

### SQLite Write Contention
If two jobs run simultaneously (different configs), both write to SQLite. SQLite handles concurrent writes via WAL mode. Enable WAL mode in `db.py` after engine creation if you see `database is locked` errors:
```python
from sqlalchemy import event
@event.listens_for(engine.sync_engine, "connect")
def set_wal(dbapi_conn, _):
    dbapi_conn.execute("PRAGMA journal_mode=WAL")
```

### Monitor Page Refresh Pattern
The `time.sleep(5) + st.rerun()` pattern causes the entire page to re-render every 5 seconds. This is fine for a local tool but will feel slightly janky. If needed, wrap the dynamic section in `@st.fragment` (Streamlit ≥1.37) to limit reruns to just that section.
