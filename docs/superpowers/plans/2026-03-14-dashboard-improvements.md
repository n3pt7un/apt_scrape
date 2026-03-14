# Dashboard Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign Search Configs form with correct create/edit behavior, add per-config site selection and rate-limiting (request delay, page delay, optional timeout), fix Monitor auto-refresh, align Listings with the API, and add per-site config overrides (areas, selectors, wait selectors) so users can experiment with site parameters.

**Architecture:** Expand `SearchConfig` schema in backend/db.py; validate and persist new fields in configs router; apply site and delays in backend/runner.py. Minimal apt_scrape extension for config overrides (config_from_dict, config_to_dict, deep_merge, get_adapter_with_overrides). Backend stores site overrides and exposes GET/PUT /sites/{id}/config and GET /sites/{id}/areas. Streamlit form rewritten with explicit defaults; area dropdown driven by selected site; new Site settings page for editing overrides. Monitor only auto-refreshes when jobs are running.

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
| `backend/db.py` (site overrides) | New model or table for site_config_overrides (site_id, overrides JSON). |
| `backend/routers/sites.py` | GET /sites, GET/PUT /sites/{id}/config, GET /sites/{id}/areas. |
| `backend/runner.py` (overrides) | Load overrides for job's site_id; call get_adapter_with_overrides(site_id, overrides). |
| `apt_scrape/sites/base.py` | config_from_dict, config_to_dict, deep_merge; refactor load_config_from_yaml to use config_from_dict. |
| `apt_scrape/sites/__init__.py` | get_adapter_with_overrides; site_id -> (adapter_class, config_path) mapping. |
| `frontend/pages/5_Site_Settings.py` | New page: select site, edit areas + wait selectors + optional selector overrides, save. |
| `frontend/pages/1_Search_Configs.py` (areas) | Area dropdown/options from GET /sites/{site_id}/areas when site selected. |
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

## Chunk 7: Per-site config overrides

Implement only after Chunks 1–6 are done. Spec: design doc §8.

### Task 8: apt_scrape — config_from_dict, config_to_dict, deep_merge, get_adapter_with_overrides

**Files:** Modify `apt_scrape/sites/base.py`; modify `apt_scrape/sites/__init__.py`.

- [ ] **Step 1: Extract config_from_dict in base.py**

Refactor `load_config_from_yaml` so the dict → SiteConfig logic lives in a new function `config_from_dict(d: dict) -> SiteConfig` (same structure as current YAML load). Change `load_config_from_yaml(path)` to open the file, `yaml.safe_load`, and call `config_from_dict(d)`.

- [ ] **Step 2: Add config_to_dict in base.py**

Implement `config_to_dict(config: SiteConfig) -> dict` that serializes the config to a nested dict (SelectorGroup → list of strings, SearchSelectors/DetailSelectors → nested dicts of lists). Export in `__all__`.

- [ ] **Step 3: Add deep_merge in base.py**

Implement `deep_merge(base: dict, overrides: dict) -> dict`. For dicts, recurse; for lists, overrides replace base; for scalars, overrides win. Export in `__all__`.

- [ ] **Step 4: Add get_adapter_with_overrides in __init__.py**

Build a mapping `site_id -> (adapter_class, config_path)` using each adapter module’s `_CONFIG_PATH`. Implement `get_adapter_with_overrides(site_id: str, overrides: dict | None = None) -> SiteAdapter`: if not overrides, return `get_adapter(site_id)`. Else load base dict from config path (yaml.safe_load), `merged = deep_merge(base_dict, overrides)`, `config = config_from_dict(merged)`, instantiate the adapter class with `config` and return. Handle Idealista’s extra raw YAML keys if needed (area_map etc.) so merged config still works.

- [ ] **Step 5: Run existing apt_scrape/sites tests**

```bash
python -m pytest tests/ -v -k "site or immobiliare or casa or idealista" 2>/dev/null || python -m pytest tests/ -v
```

Fix any regressions.

- [ ] **Step 6: Commit**

```bash
git add apt_scrape/sites/base.py apt_scrape/sites/__init__.py
git commit -m "feat(apt_scrape): config_from_dict, config_to_dict, deep_merge, get_adapter_with_overrides for site overrides"
```

### Task 9: Backend — site_config_overrides table and sites router

**Files:** Create or modify `backend/db.py` (new model); create `backend/routers/sites.py`; register router in `backend/main.py`; add tests.

- [ ] **Step 1: Add SiteConfigOverride model in db.py**

Table `siteconfigoverride` (or `site_config_overrides`): `site_id` (str, primary key), `overrides` (str, JSON). Default overrides = "{}".

- [ ] **Step 2: Migration for new table**

`create_db_and_tables()` already creates all tables; new model will create the table. For existing DBs, no ALTER needed (new table).

- [ ] **Step 3: Create backend/routers/sites.py**

- GET /sites → return `list_adapters()`.
- GET /sites/{site_id}/config → load base config from apt_scrape (config_to_dict of default adapter’s config), load overrides from DB for site_id, deep_merge, return merged dict. Optionally also return `overrides` only for the UI.
- GET /sites/{site_id}/areas → from overrides["areas"] if present, else from base config (e.g. area_map keys or "areas" key if any), else [].
- PUT /sites/{site_id}/config → body: partial overrides dict. Load current overrides from DB, deep_merge body into it, save. Validate site_id in list_adapters().

- [ ] **Step 4: Register sites router in main.py**

`app.include_router(sites.router, prefix="/sites", tags=["sites"])`. Define GET /sites before GET /sites/{site_id} so "/sites" is not captured as site_id.

- [ ] **Step 5: Add tests for sites router**

Test GET /sites returns list; GET /sites/immobiliare/config returns dict with search_selectors; PUT then GET returns updated overrides; GET /sites/immobiliare/areas.

- [ ] **Step 6: Commit**

```bash
git add backend/db.py backend/routers/sites.py backend/main.py tests/
git commit -m "feat(backend): site_config_overrides and sites API (config, areas)"
```

### Task 10: Runner uses get_adapter_with_overrides

**Files:** Modify `backend/runner.py`.

- [ ] **Step 1: Load overrides for config’s site_id**

Before resolving the adapter, query SiteConfigOverride for cfg.site_id. If row exists and overrides non-empty, pass overrides (JSON parsed) to get_adapter_with_overrides(site_id, overrides). Otherwise get_adapter(site_id).

- [ ] **Step 2: Run backend tests**

```bash
python -m pytest tests/backend/ -v
```

- [ ] **Step 3: Commit**

```bash
git add backend/runner.py
git commit -m "feat(backend): runner uses get_adapter_with_overrides when site overrides exist"
```

### Task 11: Frontend — Site settings page and area dropdown

**Files:** Create `frontend/pages/5_Site_Settings.py`; modify `frontend/pages/1_Search_Configs.py`.

- [ ] **Step 1: Create 5_Site_Settings.py**

Page title "Site settings". GET /sites for dropdown. On site select, GET /sites/{id}/config (or /config and /areas). Show areas (textarea one per line or multiselect), search_wait_selector, detail_wait_selector. Optional: expandable "Advanced" with search_selectors/detail_selectors as editable lists. Save → PUT /sites/{id}/config with overrides payload (only keys user can edit). Success message and rerun.

- [ ] **Step 2: Search Configs area field from GET /sites/{site_id}/areas**

When site_id changes (or on load when editing), call GET /sites/{site_id}/areas. Use returned list for area selectbox options (plus "Other" or free text for custom). If list empty, keep current preset or free text behavior.

- [ ] **Step 3: Manual check**

Open Site settings, select casa, set areas to ["bicocca","niguarda"], save. Open Search Configs, select site=casa, confirm area dropdown shows those areas. Run a job and confirm it uses overrides if set.

- [ ] **Step 4: Commit**

```bash
git add frontend/pages/5_Site_Settings.py frontend/pages/1_Search_Configs.py
git commit -m "feat(frontend): Site settings page and area dropdown from site overrides"
```

---

## Notes for implementers

- **apt_scrape:** Delays are applied only in backend/runner.py. For overrides, apt_scrape gets config_from_dict, config_to_dict, deep_merge, get_adapter_with_overrides (design §8.1). Do not change server.py or enrichment.
- **timeout_sec:** Stored in DB and API only; runner does not use it until apt_scrape exposes a page timeout parameter.
- **GET /configs/sites:** Implement in configs router so the UI can stay in sync with list_adapters() without hardcoding site IDs.
- **Site overrides:** Stored as JSON; only override keys are stored (partial merge on PUT). Runner loads overrides per job’s site_id and passes to get_adapter_with_overrides.
