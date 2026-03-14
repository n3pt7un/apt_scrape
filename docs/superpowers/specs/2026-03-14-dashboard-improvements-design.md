# Dashboard & Backend Improvements — Design

**Date:** 2026-03-14  
**Status:** Approved (Approach B)  
**Scope:** Full redesign of Search Configs form, expanded schema (site + rate-limiting), runner changes, Monitor/Listings fixes. No Docker dependency; local CLI run only.

---

## Goals

1. **Fix broken UX** — Form widgets that receive `value=None` in edit mode cause wrong defaults; fix all create/edit form behavior.
2. **Add missing config** — Per-config site selection (immobiliare / casa / idealista), and rate-limiting: delay between requests, delay between pages, optional timeout.
3. **Improve clarity** — Single, well-structured form with clear sections; no ambiguous edit-in-place state.
4. **Fix Monitor** — Auto-refresh only when there are running jobs (or use a fragment); avoid constant 5s polling when idle.
5. **Stabilize Listings** — Page already exists; ensure API contract and any small UX fixes are documented and consistent.

---

## Out of Scope

- Changing the `apt_scrape` package (server, enrichment, sites). All new behavior is in `backend/` and `frontend/`.
- Docker: no changes to Dockerfile or docker-compose for this work.
- New pages (e.g. “Site Settings”): all new options live on Search Configs.

---

## 1. Schema Changes (`backend/db.py`)

### SearchConfig — new columns

| Column | Type | Default | Notes |
|--------|------|--------|--------|
| `site_id` | str | `"immobiliare"` | One of `list_adapters()`: immobiliare, casa, idealista. |
| `request_delay_sec` | float | 2.0 | Seconds to wait after each **request** (search + detail). Runner applies `asyncio.sleep(request_delay_sec)` after each `browser.fetch_page` (and before next). |
| `page_delay_sec` | float | 0.0 | Seconds to wait between **search result pages** (e.g. page 1 → page 2). Applied in runner only between page fetches, not inside enrichment. |
| `timeout_sec` | optional int | null | Reserved for future use when apt_scrape exposes a page load timeout. Stored in DB and API; runner ignores it for now. |

Existing columns unchanged. Migration: add columns with defaults; no backfill needed. SQLite: add columns via `ALTER TABLE` or recreate table in a migration step (implementation plan will specify).

---

## 2. Backend API

### Configs router (`backend/routers/configs.py`)

- **ConfigIn** (and response) includes: `site_id`, `request_delay_sec`, `page_delay_sec`, `timeout_sec` (optional).
- **GET /configs** and **GET /configs/{id}** return the new fields.
- **POST /configs** and **PUT /configs/{id}** accept the new fields; validation: `site_id` must be in `list_adapters()`.

### Runner (`backend/runner.py`)

- Load config’s `site_id`; resolve adapter with `get_adapter(cfg.site_id)`. If `site_id` missing or invalid, fall back to `list_adapters()[0]`.
- After each `await browser.fetch_page(...)` in the search loop: `await asyncio.sleep(cfg.request_delay_sec)` (use config value; if missing, 2.0).
- Between search pages (after processing one page, before fetching the next): `await asyncio.sleep(cfg.page_delay_sec)` (if missing, 0.0).
- Enrichment (detail fetches) is inside `apt_scrape.enrichment`; we do **not** modify that package. Optional: in runner, after calling `enrich_with_details`, we could add a single delay per batch if we ever expose “delay between detail batches” — leave that for a later iteration. For this design, only **search** request delay and **page** delay are applied in the runner.

### Scheduler

- No changes; scheduler already uses config from DB. New fields are read by the runner when the job runs.

---

## 3. Search Configs Page — Form Redesign (`frontend/pages/1_Search_Configs.py`)

### Structure (single form, two modes)

- **Create mode:** One form “New Search Config” with all fields and clear defaults (no `value=None`).
- **Edit mode:** Same form, title “Edit: &lt;name&gt;”, pre-filled from `edit_data`. All widgets receive **explicit** values (from `edit_data` or safe defaults). Never pass `value=None` or `default=None` to Streamlit widgets that require a value (e.g. `st.number_input`, `st.slider`, `st.time_input`).

### Sections (in order)

1. **Basics** — Name, Site (selectbox: immobiliare, casa, idealista), City, Area (optional), Operation, Property types (comma-separated).
2. **Filters** — Price range (slider), Min sqm (number_input, default 0), Min rooms (selectbox 1–5), Start page, End page.
3. **Schedule** — Days (multiselect), Time (UTC) (time_input; default 08:00 when creating).
4. **Rate limiting** — Request delay (sec): number_input, min 0, step 0.5, default 2.0. Page delay (sec): number_input, min 0, step 0.5, default 0. Timeout (sec): number_input, optional (placeholder “Optional”), stored as null if empty.
5. **Concurrency & VPN** — Detail concurrency (slider 1–10), VPN rotate batches (slider 1–10).
6. **Toggles** — AI analysis (toggle), Notion auto-push (toggle).

Submit: “Save” (create) or “Update” (edit). Cancel (edit only): clears `editing_id` / `edit_data` and reruns.

### Widget rules

- **number_input:** Always pass explicit `value=...` (from edit data or default). Use `value=defaults.get("min_sqm", 0)` etc., never `value=None`.
- **slider:** Same; for price use a tuple from `defaults` or `(700, 1200)`.
- **time_input:** Use `datetime.time(h, m)` from config or `datetime.time(8, 0)`; never `value=None`.
- **multiselect (days):** `default=defaults.get("schedule_days") or []` (list), never `default=None`.
- **toggle:** `value=defaults.get("auto_analyse", True)` etc., never `value=None`.

### Cards (list of configs)

- Keep existing card layout. Add a small label for **Site** (e.g. “casa”) next to the config name or in the caption. No other structural change to the list.

---

## 4. Monitor Page (`frontend/pages/2_Monitor.py`)

- **Conditional auto-refresh:** Only run `time.sleep(5)` and `st.rerun()` when there is at least one job with `status == "running"`. If there are no running jobs, render once and do not schedule a rerun (no sleep).
- Optional improvement: wrap the “Active Jobs” + “Recent Jobs” block in `@st.fragment` with a key so only that fragment reruns when refreshing (if Streamlit version supports it). If not, the above conditional is enough.

---

## 5. Listings Page (`frontend/pages/4_Listings.py`)

- No backend API change required for list/detail; existing `GET /listings` and the detail shown from the list response are sufficient.
- Ensure the page handles empty list and API errors the same way as other pages (st.info / st.error). No new features in this design; only confirm it’s consistent and documented.

---

## 6. Migration and Compatibility

- **DB:** Add new columns to `searchconfig` with defaults. Existing rows get `site_id='immobiliare'`, `request_delay_sec=2.0`, `page_delay_sec=0.0`, `timeout_sec=null`. Implementation plan will choose: either ALTER TABLE (SQLite supports ADD COLUMN) or a small migration script.
- **API:** Clients that don’t send the new fields still work; backend uses defaults for create/update.
- **Runner:** Old configs (no `site_id`) are handled by fallback to first adapter and default delays.

---

## 7. Verification

- Create a new config with site=casa, request_delay_sec=3, page_delay_sec=1. Run job; in logs, confirm delays and that casa adapter is used.
- Edit the same config; form shows correct values; update saves and next run uses new values.
- Monitor: with no running jobs, page loads once and does not keep rerunning; with one running job, it refreshes every 5s.
- Listings: filters and detail panel work; no regressions.

---

## 8. Documentation

- Update `docs/running-locally.md` if any new env or run steps.
- In `README` or docs, briefly mention “Search Configs: site selection and rate limits (request delay, page delay) per config.”
