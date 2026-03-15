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
2. Convert each to the dict format expected by `notion_push` (matching the shape produced by the runner).
3. Call `mark_notion_duplicates(listing_dicts)` — marks already-present listings with `notion_skipped=True`.
4. Filter to only non-skipped listings, call `push_listings(to_push)`.
5. For pushed listings, update `notion_page_id` in the DB.

**Response:**
```json
{ "pushed": 3, "skipped": 1, "errors": [] }
```

**Error handling:** If Notion credentials are missing or the push fails, return a clear error message rather than a 500.

### 2. `GET /listings` — add `job_id` query param

Add optional `job_id: Optional[int] = Query(None)` filter to `list_listings`. Needed so the Monitor page can retrieve listing IDs for a specific job before calling the push endpoint.

---

## Frontend Changes

### 3. `frontend/pages/4_Listings.py` — multi-row selection + bulk push

- Change `selection_mode="single-row"` → `selection_mode="multi-row"`.
- When one or more rows are selected, show a "Push to Notion" button above the table.
- On click: collect IDs of selected rows, call `api.post("/listings/notion-push", json={"listing_ids": ids})`, show `st.success` / `st.error` with pushed/skipped counts.

### 4. `frontend/pages/4_Listings.py` — single listing detail push

- In the detail panel (already rendered below the table for a selected row), add a "Push to Notion" button.
- If `listing["notion_page_id"]` is already set, show "Already in Notion" (disabled).
- Otherwise call the same endpoint with `[listing["id"]]`.

### 5. `frontend/pages/2_Monitor.py` — per-job push button

- In each `done` job expander, add a "Push to Notion" button alongside the existing "Delete" button.
- On click:
  1. Call `api.get("/listings", params={"job_id": job["id"], "limit": 1000})` to retrieve listing IDs for that job.
  2. Call `api.post("/listings/notion-push", json={"listing_ids": [l["id"] for l in listings]})`.
  3. Show pushed/skipped counts.

---

## Data Flow

```
User clicks "Push to Notion"
  → POST /listings/notion-push {listing_ids}
  → fetch Listing records from DB
  → mark_notion_duplicates(dicts)   # skips already-in-Notion
  → push_listings(non-skipped)
  → update notion_page_id in DB
  → return {pushed, skipped, errors}
```

---

## Out of Scope

- Pushing listings that were never enriched / scored (no special handling — push what's in the DB).
- Bulk-push of all listings across all jobs (not needed; per-job and multi-select cover the use cases).
- Modifying the `auto_notion_push` config flag behavior (unchanged).
