# Design: On-demand Notion Push from Streamlit UI

**Date:** 2026-03-15
**Status:** Approved

## Problem

Users who ran a scrape job without `auto_notion_push` enabled have no way to push the resulting listings to Notion after the fact. The data lives in the DB but the only push path is the automated one that runs during the job pipeline.

## Solution

Add a single backend endpoint `POST /listings/notion-push` and surface it from three places in the Streamlit UI: the Listings table (multi-row selection), the Listings detail panel (single listing), and the Monitor page (per completed job).

Deduplication is always run before any push — no listing already present in Notion will be pushed again.

---

## Backend Changes

### 1. `POST /listings/notion-push` — new endpoint in `backend/routers/listings.py`

**Request body:**
```json
{ "listing_ids": [1, 2, 3] }
```

**Logic:**
1. Fetch full `Listing` records from DB for the given IDs.
2. Reconstruct each listing dict by parsing `listing.raw_json` (JSON-decoded). This is required because `notion_push` functions (`_build_properties`, etc.) expect the full original scraper dict — including `notion_fields`, `detail`, `detail_agency`, `detail_address`, `detail_energy_class`, `_area`, `source`, `ai_reason` etc. — none of which are columns on the `Listing` model. Only `raw_json` contains the full shape.
3. Overlay DB-only fields that may have been added after scrape: copy `ai_score`, `ai_verdict`, `notion_page_id` from the `Listing` record onto each dict so they reflect the current DB state.
4. Call `await mark_notion_duplicates(listing_dicts)` — marks already-present listings with `notion_skipped=True` and populates `notion_page_id` on each dict.
5. Filter to only non-skipped listings, call `await push_listings(to_push)`.
6. For each successfully pushed listing, update `Listing.notion_page_id` in the DB.
7. Skipped (already-in-Notion) listings: also backfill `Listing.notion_page_id` in the DB if the column is currently NULL (using the value set by `mark_notion_duplicates`).

**The endpoint must be `async def`** since both `mark_notion_duplicates` and `push_listings` are async functions.

**Response (200):**
```json
{ "pushed": 3, "skipped": 1, "errors": [] }
```
`errors` is a list of strings describing per-listing failures (e.g. `"Listing 42: Notion API error 400"`).

**Error responses:**
- `503` if Notion credentials (`NOTION_API_KEY`, `NOTION_APARTMENTS_DB_ID`) are not configured, body: `{"detail": "Notion credentials not configured"}`.
- `400` if `listing_ids` is empty.
- Push failures: `push_listings` raises on failure (does not return per-listing errors). The endpoint wraps the call in try/except; on exception, return `200` with `{"pushed": 0, "skipped": N, "errors": ["<exception message>"]}`. The `errors` field is a list of at most one top-level error string, not per-listing granularity.

### 2. `GET /listings` — add `job_id` query param

Add optional `job_id: Optional[int] = Query(None)` filter to `list_listings`. Needed so the Monitor page can retrieve listing IDs for a specific job. The existing `limit` ceiling of 1000 is accepted as sufficient; jobs producing more than 1000 listings are not a current concern.

---

## Frontend Changes

### 3. `frontend/pages/4_Listings.py` — multi-row selection + bulk push

- Change `selection_mode="single-row"` → `selection_mode="multi-row"`.
- When one or more rows are selected, show a "Push to Notion" button above the table.
- On click: collect IDs of selected rows, call `api.post("/listings/notion-push", json={"listing_ids": ids})`, show `st.success` / `st.error` with pushed/skipped counts.
- After a successful push, call `st.rerun()` so listing data is refreshed and button states reflect the updated `notion_page_id` values.

### 4. `frontend/pages/4_Listings.py` — single listing detail push

- The detail panel is shown only when **exactly one** row is selected (same as the previous single-row behaviour). When multiple rows are selected, the detail panel is hidden.
- In the detail panel, add a "Push to Notion" button.
- If `listing["notion_page_id"]` is already set, render `st.button("Already in Notion", disabled=True)`.
- Otherwise call `api.post("/listings/notion-push", json={"listing_ids": [listing["id"]]})` and show result, then `st.rerun()`.

### 5. `frontend/pages/2_Monitor.py` — per-job push button

- In each `done` job expander, add a "Push to Notion" button alongside the existing "Delete" button.
- On click:
  1. Call `api.get("/listings", params={"job_id": job["id"], "limit": 1000})` to retrieve listings for that job.
  2. If no listings returned, show `st.warning("No listings found for this job.")`.
  3. Otherwise call `api.post("/listings/notion-push", json={"listing_ids": [l["id"] for l in listings]})`.
  4. Show pushed/skipped counts via `st.success` / `st.error`.
  5. Call `st.rerun()` after a successful push (Monitor does not display per-listing Notion state, but rerun ensures consistency if the page ever does).

---

## Data Flow

```
User clicks "Push to Notion"
  → POST /listings/notion-push {listing_ids}
  → fetch Listing records from DB
  → reconstruct dicts from raw_json + overlay ai_score/ai_verdict/notion_page_id
  → await mark_notion_duplicates(dicts)   # sets notion_skipped=True on already-present
  → await push_listings(non-skipped)
  → update notion_page_id in DB for pushed + backfill for skipped-but-null
  → return {pushed, skipped, errors}
  → frontend calls st.rerun() to refresh UI state
```

---

## Out of Scope

- Pushing listings that were never enriched / scored (no special handling — push what's in the DB).
- Bulk-push of all listings across all jobs (not needed; per-job and multi-select cover the use cases).
- Modifying the `auto_notion_push` config flag behavior (unchanged).
- Pagination for the Monitor job listing fetch (1000-row ceiling is accepted).
