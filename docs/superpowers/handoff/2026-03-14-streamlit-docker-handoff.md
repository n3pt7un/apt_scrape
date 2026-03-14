# Handoff: Streamlit + Docker Platform — Wave 4 Onward

**Date:** 2026-03-14
**Branch:** `feat/streamlit-docker-platform`
**Repo:** `/Users/tarasivaniv/Downloads/apt_scrape`
**Status:** Tasks 1–6 complete (15/15 tests passing). Tasks 7–12 remain.

---

## What Has Been Built

### Commits on branch (newest first)

```
55f54fb feat(backend): preferences and jobs routers with tests
11594f2 feat(backend): configs CRUD router + fix StaticPool for in-memory test engine
4e952c5 feat(backend): FastAPI app entry with lifespan and stub routers
a153e20 feat(backend): add SQLModel schema for search_configs, jobs, listings
25f1433 feat: add Docker + project scaffolding for streamlit platform
```

### Files created so far

```
backend/
├── __init__.py
├── Dockerfile
├── requirements.txt          # fastapi, uvicorn, apscheduler, sqlmodel, aiofiles, python-dotenv, httpx
├── db.py                     # SQLModel schema: SearchConfig, Job, Listing; engine with StaticPool for :memory:
├── main.py                   # FastAPI app + lifespan (scheduler start/stop + browser close on shutdown)
├── scheduler.py              # STUB — only stubs remain: start/stop/reload_config/trigger_now
├── runner.py                 # DOES NOT EXIST YET
└── routers/
    ├── __init__.py
    ├── configs.py            # FULL CRUD: GET/POST/PUT/DELETE/PATCH toggle/POST run
    ├── jobs.py               # GET /jobs, GET /jobs/{id}
    └── preferences.py        # GET/PUT /preferences (reads PREFERENCES_FILE env var at call time)

frontend/
├── Dockerfile
├── requirements.txt          # streamlit, httpx
├── app.py                    # DOES NOT EXIST YET
├── api.py                    # DOES NOT EXIST YET
└── pages/                    # DOES NOT EXIST YET

docker-compose.yml            # Done
.env.example                  # Done
data/.gitkeep                 # Done

tests/backend/
├── __init__.py
├── test_db.py                # 4 passing
├── test_main.py              # 1 passing
├── test_configs.py           # 4 passing
├── test_jobs.py              # 4 passing
└── test_preferences.py       # 2 passing
```

### Run all tests
```bash
cd /Users/tarasivaniv/Downloads/apt_scrape
python -m pytest tests/backend/ -v
# Expected: 15 passed
```

---

## Critical Design Decisions Already Made

1. **StaticPool fix in `backend/db.py`:** When `DB_PATH=:memory:`, the engine uses `StaticPool` so all connections in tests share the same in-memory database. This is already in place — do not undo it.

2. **Browser singleton:** `apt_scrape/server.py` defines `browser = BrowserManager()` at module level (line 453). The runner imports this directly: `from apt_scrape.server import browser`. The browser is **never closed inside `runner.py`** — it stays alive across job runs, managed by the FastAPI lifespan in `main.py`.

3. **runner.py bypasses cli.py entirely.** Call scraping primitives directly. Never call `browser.close()`.

4. **`trigger_now` creates a real Job row synchronously** (so the API can return a real `job_id` immediately), then fires `run_config_job` as a background asyncio task.

5. **`load_preferences()` reads `PREFERENCES_FILE` env var at call time** (via `apt_scrape.analysis.load_preferences()`). The `preferences.py` router also reads the env var at call time via `_prefs_path()`.

6. **MVP uses first registered adapter only.** `list_adapters()[0]` = Immobiliare.it. No `site` field on SearchConfig. Multi-site is a future extension.

7. **Pipeline order:** scrape → enrich_with_details → enrich_post_dates → stamp → analyse → notion_push → upsert

---

## Confirmed `apt_scrape` Package API Signatures

These are the exact signatures — **do not guess**:

```python
# apt_scrape/enrichment.py
async def enrich_with_details(
    listings: list[dict],
    browser: BrowserManager,
    fallback_adapter: Any,
    detail_limit: int | None = None,
    *,
    concurrency: int = 5,
    rotate_every_batches: int = 3,
) -> tuple[int, list[dict[str, str]]]: ...

async def enrich_post_dates(
    listings: list[dict],
    browser: BrowserManager,
    fallback_adapter: Any,
    *,
    concurrency: int = 5,
    rotate_every_batches: int = 3,
) -> tuple[int, list[dict[str, str]]]: ...

# apt_scrape/analysis.py
def load_preferences(path: str | None = None) -> str:
    # reads PREFERENCES_FILE env var if path=None, raises FileNotFoundError if missing

async def analyse_listings(listings: list[dict], preferences: str) -> None: ...

# apt_scrape/notion_push.py
async def push_listings(listings: list[dict]) -> None: ...

# apt_scrape/sites/__init__.py
def list_adapters() -> list[str]: ...       # returns ["immobiliare", ...]
def get_adapter(site_id: str) -> SiteAdapter: ...

# apt_scrape/server.py
browser = BrowserManager()   # module-level singleton at line 453
```

### SearchFilters import path:
```python
from apt_scrape.sites import SearchFilters, get_adapter, list_adapters
```

---

## Remaining Tasks

### Task 7: `backend/runner.py` (MUST DO FIRST — Task 8 depends on it)

**Test file** `tests/backend/test_runner.py`:

```python
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
import backend.runner as backend_runner_module
backend_runner_run = backend_runner_module.run_config_job


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

        job_id = asyncio.run(backend_runner_run(config_id, logs.append))

    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job is not None
        assert job.status == "done"
        assert job.listing_count == 1
        assert job.config_id == config_id
```

**Implementation** `backend/runner.py`:

```python
"""backend.runner — Core job execution pipeline.

Pipeline order: scrape → enrich → post_dates → stamp → analyse → notion_push → upsert
NEVER calls browser.close() — browser lifecycle is managed by FastAPI lifespan.
"""

import json
import logging
import os
from datetime import datetime
from typing import Callable

from sqlmodel import Session, select as sql_select

from apt_scrape.enrichment import enrich_post_dates, enrich_with_details
from apt_scrape.server import browser
from apt_scrape.sites import SearchFilters, get_adapter, list_adapters

logger = logging.getLogger(__name__)


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
    """Execute a scraping job for the given config. Returns job_id."""
    from backend.db import Job, Listing, SearchConfig, engine

    # 1. Create or reuse job record
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
            source = list_adapters()[0]
            adapter = get_adapter(source)
            city_slug = _normalize_slug(cfg.city)
            area_slug = _normalize_slug(cfg.area) if cfg.area else None
            property_types = _parse_property_types(cfg.property_type)
            detail_concurrency = cfg.detail_concurrency
            vpn_rotate_batches = cfg.vpn_rotate_batches
            auto_analyse = cfg.auto_analyse
            auto_notion_push = cfg.auto_notion_push
            start_page = cfg.start_page
            end_page = cfg.end_page
            min_price = cfg.min_price
            max_price = cfg.max_price
            min_sqm = cfg.min_sqm
            min_rooms = cfg.min_rooms
            operation = cfg.operation

        # 2. Scrape search pages
        all_listings: list[dict] = []
        for pt in property_types:
            for page_num in range(start_page, end_page + 1):
                filters = SearchFilters(
                    city=city_slug, area=area_slug, operation=operation,
                    property_type=pt, min_price=min_price, max_price=max_price,
                    min_sqm=min_sqm, min_rooms=min_rooms, page=page_num,
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

        # 3. Enrich details
        _log(f"Enriching details (concurrency={detail_concurrency})...")
        await enrich_with_details(
            deduped, browser, adapter, None,
            concurrency=detail_concurrency,
            rotate_every_batches=vpn_rotate_batches,
        )

        # 4. Enrich post dates
        await enrich_post_dates(
            deduped, browser, adapter,
            concurrency=detail_concurrency,
            rotate_every_batches=vpn_rotate_batches,
        )

        # 5. Stamp area/city
        for listing in deduped:
            listing["_area"] = area_slug or ""
            listing["_city"] = city_slug

        # 6. AI Analysis
        if auto_analyse and deduped:
            _log("Running AI analysis...")
            from apt_scrape.analysis import analyse_listings, load_preferences
            try:
                prefs = load_preferences()
                await analyse_listings(deduped, prefs)
                _log("Analysis complete.")
            except FileNotFoundError:
                _log("[warn] preferences.txt not found — skipping analysis.")

        # 7. Notion Push
        if auto_notion_push and deduped:
            _log("Pushing to Notion...")
            from apt_scrape.notion_push import push_listings
            await push_listings(deduped)
            _log("Notion push complete.")

        # 8. Upsert listings to DB
        _log("Upserting listings to DB...")
        with Session(engine) as session:
            for listing in deduped:
                url = str(listing.get("url", "")).strip()
                if not url:
                    continue
                existing = session.exec(
                    sql_select(Listing).where(Listing.url == url)
                ).first()
                row_data = dict(
                    url=url, job_id=job_id, config_id=config_id,
                    title=listing.get("title", ""), price=listing.get("price", ""),
                    sqm=listing.get("sqm", ""), rooms=listing.get("rooms", ""),
                    area=area_slug or "", city=city_slug,
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

        # 9. Mark job done
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

**Run and commit:**
```bash
python -m pytest tests/backend/test_runner.py -v   # expect 1 PASS
git add backend/runner.py tests/backend/test_runner.py
git commit -m "feat(backend): job runner pipeline (scrape → enrich → analyse → push → upsert)"
```

---

### Task 8: `backend/scheduler.py` (depends on Task 7)

**Test file** `tests/backend/test_scheduler.py`:

```python
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


def test_trigger_now_creates_background_task():
    enabled_id = _seed_enabled_config()
    with patch("backend.scheduler.run_config_job", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = 42
        import backend.scheduler as sched
        job_id = sched.trigger_now(enabled_id)
        assert isinstance(job_id, int)


def test_reload_config_does_not_raise_for_unknown_id():
    import backend.scheduler as sched
    sched.reload_config(99999)
```

**Implementation** `backend/scheduler.py` (replace the stub entirely):

```python
"""backend.scheduler — APScheduler setup and job management."""

import asyncio
import json
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from backend.db import Job, SearchConfig, engine
from backend.runner import run_config_job

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")

DAY_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
}


def _make_job_id(config_id: int) -> str:
    return f"config_{config_id}"


def _build_trigger(schedule_days: list[str], schedule_time: str) -> CronTrigger:
    days_str = ",".join(DAY_MAP.get(d, d) for d in schedule_days) or "*"
    hour, minute = schedule_time.split(":")
    return CronTrigger(day_of_week=days_str, hour=int(hour), minute=int(minute), timezone="UTC")


async def _run_job_wrapper(config_id: int) -> None:
    try:
        await run_config_job(config_id, lambda msg: None)
    except Exception:
        logger.exception("Unhandled error in job for config %d", config_id)


async def start_scheduler() -> None:
    with Session(engine) as session:
        configs = session.exec(select(SearchConfig).where(SearchConfig.enabled == True)).all()

    for cfg in configs:
        days = json.loads(cfg.schedule_days or "[]")
        if not days:
            continue
        trigger = _build_trigger(days, cfg.schedule_time)
        _scheduler.add_job(
            _run_job_wrapper, trigger=trigger, args=[cfg.id],
            id=_make_job_id(cfg.id), replace_existing=True,
            coalesce=True, max_instances=1,
        )
        logger.info("Scheduled config %d (%s) at %s on %s", cfg.id, cfg.name, cfg.schedule_time, days)

    _scheduler.start()
    logger.info("Scheduler started with %d jobs.", len(_scheduler.get_jobs()))


async def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


def reload_config(config_id: int) -> None:
    if not _scheduler.running:
        return
    job_id = _make_job_id(config_id)
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = session.get(SearchConfig, config_id)

    if cfg is None or not cfg.enabled:
        return

    days = json.loads(cfg.schedule_days or "[]")
    if not days:
        return

    trigger = _build_trigger(days, cfg.schedule_time)
    _scheduler.add_job(
        _run_job_wrapper, trigger=trigger, args=[cfg.id],
        id=job_id, replace_existing=True, coalesce=True, max_instances=1,
    )
    logger.info("Reloaded schedule for config %d", config_id)


def trigger_now(config_id: int) -> int:
    """Create a Job record synchronously, fire pipeline as background task. Returns real job_id."""
    with Session(engine) as session:
        job = Job(config_id=config_id, status="pending", triggered_by="manual")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    async def _run():
        await run_config_job(config_id, lambda msg: None, existing_job_id=job_id)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        asyncio.run(_run())

    return job_id
```

**Run and commit:**
```bash
python -m pytest tests/backend/test_scheduler.py -v   # expect 2 PASS
python -m pytest tests/backend/ -v                    # expect all PASS
git add backend/scheduler.py tests/backend/test_scheduler.py
git commit -m "feat(backend): APScheduler with CronTrigger per search config"
```

---

### Task 9: Streamlit app entry + Search Configs page

**No unit tests for Streamlit pages — write files and commit.**

Create `frontend/api.py`:

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

Create `frontend/app.py`:

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

Create `frontend/pages/1_Search_Configs.py`:

```python
"""Streamlit page: Search Configurations."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Search Configs", page_icon="⚙️", layout="wide")
st.title("⚙️ Search Configurations")

try:
    configs = api.get("/configs")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

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
                        api.post(f"/configs/{cfg['id']}/run")
                        st.success("Job started!")
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
            "schedule_days": schedule_days, "schedule_time": time_str,
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

**Commit:**
```bash
git add frontend/
git commit -m "feat(frontend): Streamlit app entry, api client, Search Configs page"
```

---

### Task 10: Monitor page

Create `frontend/pages/2_Monitor.py`:

```python
"""Streamlit page: Job Monitor."""
import time
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Monitor", page_icon="📡", layout="wide")
st.title("📡 Job Monitor")

STATUS_COLORS = {"running": "🟡", "done": "🟢", "failed": "🔴", "pending": "⚪"}


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

**Commit:**
```bash
git add frontend/pages/2_Monitor.py
git commit -m "feat(frontend): Monitor page with 5s auto-refresh and log display"
```

---

### Task 11: Preferences page

Create `frontend/pages/3_Preferences.py`:

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

**Commit:**
```bash
git add frontend/pages/3_Preferences.py
git commit -m "feat(frontend): Preferences page with editable text area and save"
```

---

### Task 12: Docker integration smoke test

```bash
# Copy seed preferences if not present
cp preferences.txt data/preferences.txt 2>/dev/null || true

# Create .env from example and fill in API keys
cp .env.example .env
# Edit .env with real OPENROUTER_API_KEY etc.

# Build and run
docker compose up --build -d

# Verify
curl http://localhost:8000/health          # {"status": "ok"}
curl http://localhost:8000/configs         # []
# Open http://localhost:8501 — Streamlit loads with 3 sidebar pages

# Create a config via UI, click Run now, verify Monitor page shows job
# If auto_analyse=True, verify listings have ai_score in SQLite
# docker compose down && docker compose up → configs persist
```

---

## Quick Reference: How to Run Tests

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape

# Run all backend tests (should be 15 passing before you start)
python -m pytest tests/backend/ -v

# Run a single file
python -m pytest tests/backend/test_runner.py -v
```

## Gotchas

- **Do not modify anything under `apt_scrape/`** — the package is treated as read-only
- **Do not call `browser.close()`** in runner.py — FastAPI lifespan handles it
- **SQLite `:memory:` tests:** The StaticPool fix in `backend/db.py` is critical; don't remove it
- **`load_preferences()` raises `FileNotFoundError`** if the file doesn't exist — the runner catches this and logs a warning
- **`analyse_listings` is async**, `load_preferences` is sync — handled correctly in runner.py above
- **`trigger_now` must return a real `job_id` (int)**, not a proxy value — done via synchronous Job insert
- **Streamlit pages have no unit tests** — they're verified manually against a running backend
