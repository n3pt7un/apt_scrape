# Dashboard Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign Search Configs form with correct create/edit behavior, add per-config site selection and rate-limiting (request delay, page delay, optional timeout), fix Monitor auto-refresh, and align Listings with the API.

**Architecture:** Expand `SearchConfig` schema in backend/db.py; validate and persist new fields in configs router; apply site and delays in backend/runner.py (no changes to apt_scrape). Streamlit form rewritten with explicit defaults and clear sections; Monitor only auto-refreshes when jobs are running.

**Tech Stack:** SQLModel, FastAPI, Streamlit, existing apt_scrape adapters (immobiliare, casa, idealista).

**Spec:** `docs/superpowers/specs/2026-03-14-dashboard-improvements-design.md`

---

## File Structure

| File | Role |
|------|------|
| `backend/db.py` | Add columns: site_id, request_delay_sec, page_delay_sec, timeout_sec to SearchConfig. |
| `backend/routers/configs.py` | ConfigIn + validation for new fields; _to_response includes them. |
| `backend/runner.py` | Use cfg.site_id with get_adapter(); apply request_delay_sec and page_delay_sec. |
| `frontend/pages/1_Search_Configs.py` | Redesigned form: sections, explicit values (no None), site + rate limit fields. |
| `frontend/pages/2_Monitor.py` | Conditional refresh: sleep+rerun only when any job is running. |
| `tests/backend/test_db.py` | Optional: assert new columns exist and defaults. |
| `tests/backend/test_configs.py` | Tests for new fields in create/update/list. |
| `tests/backend/test_runner.py` | Mock get_adapter by site_id; assert asyncio.sleep called with delay. |

---

## Chunk 1: Schema and migration

### Task 1: Add new columns to SearchConfig

**Files:** Modify `backend/db.py`; extend `tests/backend/test_db.py` if needed.

- [ ] **Step 1: Add columns to SearchConfig in backend/db.py**

Add after `created_at` (or before it):

```python
site_id: str = "immobiliare"
request_delay_sec: float = 2.0
page_delay_sec: float = 0.0
timeout_sec: Optional[int] = None
```

- [ ] **Step 2: SQLite migration for existing DBs**

SQLite supports `ALTER TABLE searchconfig ADD COLUMN site_id TEXT DEFAULT 'immobiliare';` etc. In `create_db_and_tables()` we only call `SQLModel.metadata.create_all(engine)`, which does not add columns to existing tables. So either:

  - **Option A:** Add a small migration that runs after create_db_and_tables: use raw SQL `ALTER TABLE searchconfig ADD COLUMN ...` for each new column if the column doesn't exist (check via pragma table_info or try/except). Implement in a function `_migrate_searchconfig_20260314()` in db.py and call it from `create_db_and_tables()`.
  - **Option B:** Document that existing users must delete `data/app.db` to get new schema (acceptable for local dev).

Choose Option A for backward compatibility. In db.py, after `SQLModel.metadata.create_all(engine)`:

```python
def _migrate_searchconfig_20260314(conn):  # conn = engine.raw_connection() or use run with text()
    cur = conn.execute("PRAGMA table_info(searchconfig)")
    cols = [row[1] for row in cur.fetchall()]
    if "site_id" not in cols:
        conn.execute("ALTER TABLE searchconfig ADD COLUMN site_id TEXT DEFAULT 'immobiliare'")
    if "request_delay_sec" not in cols:
        conn.execute("ALTER TABLE searchconfig ADD COLUMN request_delay_sec REAL DEFAULT 2.0")
    if "page_delay_sec" not in cols:
        conn.execute("ALTER TABLE searchconfig ADD COLUMN page_delay_sec REAL DEFAULT 0.0")
    if "timeout_sec" not in cols:
        conn.execute("ALTER TABLE searchconfig ADD COLUMN timeout_sec INTEGER")
    conn.commit()
```

Call this from `create_db_and_tables()` using the engine (e.g. with engine.connect() and run the ALTERs). Use SQLAlchemy `text()` for portability.

- [ ] **Step 3: Run existing backend tests**

```bash
cd /path/to/apt_scrape && PYTHONPATH=. python -m pytest tests/backend/test_db.py -v
```

Fix any failures (e.g. test that creates SearchConfig may need to omit new fields or set them). Then run full backend suite: `python -m pytest tests/backend/ -v`.

- [ ] **Step 4: Commit**

```bash
git add backend/db.py tests/backend/test_db.py
git commit -m "feat(backend): add site_id, request_delay_sec, page_delay_sec, timeout_sec to SearchConfig"
```

---

## Chunk 2: Configs API

### Task 2: ConfigIn and validation for new fields

**Files:** Modify `backend/routers/configs.py`; modify `tests/backend/test_configs.py`.

- [ ] **Step 1: Extend ConfigIn in backend/routers/configs.py**

Add to ConfigIn:

```python
site_id: str = "immobiliare"
request_delay_sec: float = 2.0
page_delay_sec: float = 0.0
timeout_sec: Optional[int] = None
```

- [ ] **Step 2: Validate site_id on create and update**

At the top of the router, or in a dependency: get allowed list with `from apt_scrape.sites import list_adapters`. In create_config and update_config, before building the model, check `if data.site_id not in list_adapters(): raise HTTPException(422, "Invalid site_id")`.

- [ ] **Step 3: Include new fields in create/update**

Ensure SearchConfig is built/updated with the new fields (model_dump() already includes them). _to_response already returns model_dump() so new columns are included.

- [ ] **Step 3b: Add GET /configs/sites endpoint**

Add `@router.get("/sites")` that returns `list_adapters()` (from apt_scrape.sites). This allows the frontend to populate the site selectbox without hardcoding. Route must be defined before `@router.get("/{config_id}")` so "/sites" is not matched as config_id.

- [ ] **Step 4: Add tests in tests/backend/test_configs.py**

- test_create_config_with_site_and_delays: POST with site_id="casa", request_delay_sec=3, page_delay_sec=1; GET and assert values.
- test_update_config_site_id: create then PUT with site_id="idealista"; assert.
- test_create_config_invalid_site_id_returns_422: POST with site_id="unknown"; assert status 422.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/backend/test_configs.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/routers/configs.py tests/backend/test_configs.py
git commit -m "feat(backend): configs API supports site_id and rate-limit fields with validation"
```

---

## Chunk 3: Runner uses site and delays

### Task 3: Runner — site_id and delays

**Files:** Modify `backend/runner.py`; optionally extend `tests/backend/test_runner.py`.

- [ ] **Step 1: Resolve adapter by config.site_id**

In run_config_job, where we currently have `source = list_adapters()[0]`, replace with: get `site_id` from cfg (default "immobiliare"); if site_id not in list_adapters(), use list_adapters()[0]. Then `adapter = get_adapter(site_id)`.

- [ ] **Step 2: Apply request_delay_sec after each fetch_page in search loop**

After `html = await browser.fetch_page(...)` (and after parsing and extending all_listings), add `await asyncio.sleep(getattr(cfg, 'request_delay_sec', 2.0))`. Use a variable set once from cfg at the start of the try block (e.g. request_delay_sec = getattr(cfg, 'request_delay_sec', 2.0)).

- [ ] **Step 3: Apply page_delay_sec between search pages**

Between iterations of the inner loop (after processing one page, before the next page fetch), add `await asyncio.sleep(getattr(cfg, 'page_delay_sec', 0.0))`. Do not sleep before the first page; only between page N and page N+1.

- [ ] **Step 4: (Optional) Test runner delay and site**

In test_runner.py, patch list_adapters to return ["casa"], and patch get_adapter; assert that run_config_job uses the adapter for "casa". Optionally patch asyncio.sleep and assert it was called with the expected delay (e.g. request_delay_sec). If the existing test is heavily mocked, add a minimal test that only checks the adapter resolution and sleep calls.

- [ ] **Step 5: Run tests**

```bash
python -m pytest tests/backend/test_runner.py tests/backend/ -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/runner.py tests/backend/test_runner.py
git commit -m "feat(backend): runner uses config site_id and applies request/page delays"
```

---

## Chunk 4: Search Configs form redesign

### Task 4: Streamlit Search Configs page — structure and fixes

**Files:** Modify `frontend/pages/1_Search_Configs.py`.

- [ ] **Step 1: Fetch site list from backend**

Backend does not expose list_adapters(); options: (a) add GET /configs/sites that returns list_adapters(), or (b) hardcode ["immobiliare", "casa", "idealista"] in the frontend. Prefer (a) for consistency. Add in configs router: `@router.get("/sites")` that returns `list_adapters()`. Frontend calls `api.get("/configs/sites")` and uses it for the site selectbox. If that endpoint is not added, use (b) and document.

- [ ] **Step 2: Define defaults helper for edit mode**

Build a dict `defaults` from `edit_data` when editing, with keys for every form field. For create mode, use a second dict with create defaults (e.g. schedule_time 08:00, request_delay_sec 2.0, page_delay_sec 0, etc.). Use these for every widget below.

- [ ] **Step 3: Section 1 — Basics**

Single form. Section "Basics": name (text_input), site (selectbox from /configs/sites or hardcoded list), city, area, operation, property_type. All with explicit value= or default= from defaults.

- [ ] **Step 4: Section 2 — Filters**

Price slider: value=(defaults["min_price"], defaults["max_price"]) (e.g. (700, 1200) or from edit). min_sqm number_input value=defaults.get("min_sqm", 0). min_rooms selectbox index or value from defaults. start_page, end_page number_input with value=defaults.get("start_page", 1) etc.

- [ ] **Step 5: Section 3 — Schedule**

schedule_days multiselect default=defaults.get("schedule_days") or []. schedule_time: use datetime.time from defaults (parse "08:00" or store as time); time_input value=defaults["schedule_time"].

- [ ] **Step 6: Section 4 — Rate limiting**

request_delay_sec number_input min=0, step=0.5, value=defaults.get("request_delay_sec", 2.0). page_delay_sec number_input min=0, step=0.5, value=defaults.get("page_delay_sec", 0.0). timeout_sec number_input min=0, value=defaults.get("timeout_sec") or empty; allow None and send null in payload if empty.

- [ ] **Step 7: Section 5 — Concurrency & VPN; Section 6 — Toggles**

detail_concurrency, vpn_rotate_batches from defaults. auto_analyse, auto_notion_push toggles from defaults.

- [ ] **Step 8: Payload on submit**

Include site_id, request_delay_sec, page_delay_sec, timeout_sec (null if empty) in the dict sent to POST /configs or PUT /configs/{id}.

- [ ] **Step 9: Config cards list**

Add a small label showing site_id (e.g. badge or caption) per config card.

- [ ] **Step 10: Manual check**

Run backend and frontend locally; create config with site=casa and delays; edit and save; confirm no Streamlit errors and values persist.

- [ ] **Step 11: Commit**

```bash
git add frontend/pages/1_Search_Configs.py
git commit -m "feat(frontend): redesign Search Configs form with site, rate limits, and explicit defaults"
```

---

## Chunk 5: Monitor and Listings

### Task 5: Monitor conditional refresh

**Files:** Modify `frontend/pages/2_Monitor.py`.

- [ ] **Step 1: Only sleep and rerun when a job is running**

After calling render(), get jobs again (or use the same jobs list from render if you refactor to return it). If no job has status "running", do not call time.sleep(5) and st.rerun(). Only when there is at least one running job, do time.sleep(5) and st.rerun().

- [ ] **Step 2: Commit**

```bash
git add frontend/pages/2_Monitor.py
git commit -m "fix(frontend): Monitor auto-refresh only when jobs are running"
```

### Task 6: Listings page consistency

**Files:** Review `frontend/pages/4_Listings.py`; optionally `backend/routers/listings.py`.

- [ ] **Step 1: Confirm list and filters work**

Ensure GET /listings with params (config_id, min_score, search, limit) is used correctly and empty state / errors show st.info or st.error. No code change required if already correct; otherwise small fixes.

- [ ] **Step 2: Document in design/spec**

Design doc already states Listings need no new features; ensure README or running-locally mentions Listings page.

- [ ] **Step 3: Commit (if any file changed)**

```bash
git add frontend/pages/4_Listings.py docs/
git commit -m "docs: align Listings page with API and running docs"
```

---

## Chunk 6: Docs and final verification

### Task 7: Documentation and verification

**Files:** Modify `docs/running-locally.md` and/or README; optionally `docs/superpowers/specs/2026-03-14-dashboard-improvements-design.md`.

- [ ] **Step 1: Document new options**

In README or running-locally, add one line: Search Configs support site selection (immobiliare, casa, idealista) and rate limits (request delay, page delay) per config.

- [ ] **Step 2: End-to-end verification**

Start backend and frontend; create config (site=casa, request_delay_sec=2, page_delay_sec=1); run job; check job log for delays and casa usage. Edit config; save; run again; confirm updated values. Open Monitor with no running job; confirm page does not keep rerunning. Open Listings; apply filters; confirm data and detail panel.

- [ ] **Step 3: Final commit**

```bash
git add README.md docs/
git commit -m "docs: document dashboard site and rate-limit options"
```

---

## Notes for implementers

- **apt_scrape:** Do not change apt_scrape/server.py or enrichment. Delays are applied only in backend/runner.py around fetch_page and between pages.
- **timeout_sec:** Stored in DB and API only; runner does not use it until apt_scrape exposes a page timeout parameter.
- **GET /configs/sites:** Implement in configs router so the UI can stay in sync with list_adapters() without hardcoding site IDs in the frontend.
