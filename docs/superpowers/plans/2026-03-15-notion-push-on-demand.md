# On-demand Notion Push Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to push scraped listings to Notion on-demand from the Streamlit UI — per job, bulk selection, or single listing — without needing `auto_notion_push` enabled at scrape time.

**Architecture:** New `POST /listings/notion-push` backend endpoint reconstructs full listing dicts from `raw_json`, runs dedup via `mark_notion_duplicates`, pushes via `push_listings`, and writes `notion_page_id` back to the DB. Three Streamlit surfaces call this single endpoint.

**Tech Stack:** FastAPI (async), SQLModel, `apt_scrape.notion_push`, Streamlit

---

## File Map

| File | Change |
|------|--------|
| `backend/routers/listings.py` | Add `job_id` filter to `GET /listings`; add `POST /listings/notion-push` endpoint |
| `tests/backend/test_listings.py` | New — tests for `job_id` filter and notion-push endpoint |
| `frontend/pages/4_Listings.py` | Multi-row selection, bulk push button, detail panel push button |
| `frontend/pages/2_Monitor.py` | Per-job "Push to Notion" button |

---

## Chunk 1: Backend — `job_id` filter + notion-push endpoint

### Task 1: Add `job_id` filter to `GET /listings`

**Files:**
- Modify: `backend/routers/listings.py`
- Test: `tests/backend/test_listings.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/backend/test_listings.py`. Note the `_seed()` helper uses a counter to generate unique URLs so multiple calls within one test session don't collide on the `unique=True` constraint on `Listing.url`.

```python
# tests/backend/test_listings.py
import json
import os
os.environ["DB_PATH"] = ":memory:"

from fastapi.testclient import TestClient
from sqlmodel import Session
from backend.main import app
from backend.db import create_db_and_tables, engine, SearchConfig, Job, Listing

create_db_and_tables()
client = TestClient(app)

_seed_counter = 0


def _seed():
    """Seed one config, two jobs, and two listings (one per job). Uses a counter for unique URLs."""
    global _seed_counter
    _seed_counter += 1
    n = _seed_counter

    with Session(engine) as s:
        cfg = SearchConfig(
            name=f"T{n}", city="milano", area=None, operation="affitto",
            property_type="appartamenti", schedule_days='["mon"]', schedule_time="08:00"
        )
        s.add(cfg)
        s.commit()
        s.refresh(cfg)

        job_a = Job(config_id=cfg.id, status="done", triggered_by="manual", log="")
        job_b = Job(config_id=cfg.id, status="done", triggered_by="manual", log="")
        s.add(job_a)
        s.add(job_b)
        s.commit()
        s.refresh(job_a)
        s.refresh(job_b)

        url_a = f"https://example.com/{n}/a"
        url_b = f"https://example.com/{n}/b"
        lst_a = Listing(
            url=url_a,
            job_id=job_a.id,
            config_id=cfg.id,
            title=f"Apt {n}A",
            raw_json=json.dumps({"url": url_a, "title": f"Apt {n}A"}),
        )
        lst_b = Listing(
            url=url_b,
            job_id=job_b.id,
            config_id=cfg.id,
            title=f"Apt {n}B",
            raw_json=json.dumps({"url": url_b, "title": f"Apt {n}B"}),
        )
        s.add(lst_a)
        s.add(lst_b)
        s.commit()
        s.refresh(lst_a)
        s.refresh(lst_b)
        return cfg.id, job_a.id, job_b.id, lst_a.id, lst_b.id


def test_filter_by_job_id():
    cfg_id, job_a_id, job_b_id, lst_a_id, lst_b_id = _seed()
    resp = client.get(f"/listings?job_id={job_a_id}")
    assert resp.status_code == 200
    ids = [l["id"] for l in resp.json()]
    assert lst_a_id in ids
    assert lst_b_id not in ids
```

- [ ] **Step 2: Run to confirm it fails**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape
python -m pytest tests/backend/test_listings.py::test_filter_by_job_id -v
```

Expected: `FAILED` — endpoint has no `job_id` param yet.

- [ ] **Step 3: Add `job_id` filter to `GET /listings`**

In `backend/routers/listings.py`, add `job_id` to the `list_listings` function signature (after `config_id`):

```python
job_id: Optional[int] = Query(None),
```

Then add the filter inside the function, after the `config_id` filter block:

```python
if job_id is not None:
    stmt = stmt.where(Listing.job_id == job_id)
```

- [ ] **Step 4: Run the test to confirm it passes**

```bash
python -m pytest tests/backend/test_listings.py::test_filter_by_job_id -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add backend/routers/listings.py tests/backend/test_listings.py
git commit -m "feat: add job_id filter to GET /listings"
```

---

### Task 2: `POST /listings/notion-push` endpoint

**Files:**
- Modify: `backend/routers/listings.py`
- Test: `tests/backend/test_listings.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/backend/test_listings.py`:

```python
def test_notion_push_empty_ids():
    """Returns 400 when listing_ids is empty."""
    resp = client.post("/listings/notion-push", json={"listing_ids": []})
    assert resp.status_code == 400


def test_notion_push_missing_credentials(monkeypatch):
    """Returns 503 when NOTION_API_KEY is not set."""
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
    monkeypatch.delenv("NOTION_APARTMENTS_DB_ID", raising=False)
    resp = client.post("/listings/notion-push", json={"listing_ids": [1]})
    assert resp.status_code == 503
    assert "credentials" in resp.json()["detail"].lower()


def test_notion_push_success(monkeypatch):
    """Returns pushed/skipped counts; updates notion_page_id in DB."""
    cfg_id, job_a_id, job_b_id, lst_a_id, lst_b_id = _seed()

    async def fake_mark_duplicates(listings):
        return 0  # no duplicates

    async def fake_push(listings):
        for lst in listings:
            lst["notion_page_id"] = "fake-page-id-123"
            lst["notion_skipped"] = False

    monkeypatch.setenv("NOTION_API_KEY", "fake-key")
    monkeypatch.setenv("NOTION_APARTMENTS_DB_ID", "fake-db-id")
    # Patch at the import site used by the endpoint (module-level imports in listings.py)
    monkeypatch.setattr("backend.routers.listings.mark_notion_duplicates", fake_mark_duplicates)
    monkeypatch.setattr("backend.routers.listings.push_listings", fake_push)

    resp = client.post("/listings/notion-push", json={"listing_ids": [lst_a_id]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pushed"] == 1
    assert data["skipped"] == 0
    assert data["errors"] == []

    # Verify notion_page_id written back to DB
    with Session(engine) as s:
        updated = s.get(Listing, lst_a_id)
        assert updated.notion_page_id == "fake-page-id-123"


def test_notion_push_skips_duplicates(monkeypatch):
    """Skipped listings (already in Notion) get their notion_page_id backfilled."""
    cfg_id, job_a_id, job_b_id, lst_a_id, lst_b_id = _seed()

    async def fake_mark_duplicates(listings):
        for lst in listings:
            lst["notion_skipped"] = True
            lst["notion_page_id"] = "existing-page-id"
        return len(listings)

    async def fake_push(listings):
        pass  # nothing to push

    monkeypatch.setenv("NOTION_API_KEY", "fake-key")
    monkeypatch.setenv("NOTION_APARTMENTS_DB_ID", "fake-db-id")
    monkeypatch.setattr("backend.routers.listings.mark_notion_duplicates", fake_mark_duplicates)
    monkeypatch.setattr("backend.routers.listings.push_listings", fake_push)

    resp = client.post("/listings/notion-push", json={"listing_ids": [lst_b_id]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["pushed"] == 0
    assert data["skipped"] == 1

    # notion_page_id backfilled for skipped listing
    with Session(engine) as s:
        updated = s.get(Listing, lst_b_id)
        assert updated.notion_page_id == "existing-page-id"
```

- [ ] **Step 2: Run to confirm they fail**

```bash
python -m pytest tests/backend/test_listings.py::test_notion_push_empty_ids tests/backend/test_listings.py::test_notion_push_missing_credentials tests/backend/test_listings.py::test_notion_push_success tests/backend/test_listings.py::test_notion_push_skips_duplicates -v
```

Expected: all `FAILED` — endpoint doesn't exist yet.

- [ ] **Step 3: Add imports to `backend/routers/listings.py`**

At the top of `backend/routers/listings.py`, add these imports. The existing import line is:
```python
from fastapi import APIRouter, Depends, Query
```
Change it to:
```python
import json as _json_mod
import os

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
```

Also add module-level imports for the notion push functions (needed so monkeypatching works correctly in tests):
```python
from apt_scrape.notion_push import mark_notion_duplicates, push_listings
```

- [ ] **Step 4: Implement the endpoint**

Add to the bottom of `backend/routers/listings.py`:

```python
class NotionPushRequest(BaseModel):
    listing_ids: list[int]


@router.post("/notion-push")
async def notion_push(
    body: NotionPushRequest,
    session: Session = Depends(get_session),
):
    if not body.listing_ids:
        raise HTTPException(status_code=400, detail="listing_ids must not be empty")

    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    if not api_key or not apartments_db_id:
        raise HTTPException(status_code=503, detail="Notion credentials not configured")

    # Fetch DB records
    records = {
        lst.id: lst
        for lst in session.exec(
            select(Listing).where(Listing.id.in_(body.listing_ids))
        ).all()
    }

    # Reconstruct full dicts from raw_json, overlay live DB fields
    listing_dicts = []
    for lid in body.listing_ids:
        rec = records.get(lid)
        if rec is None:
            continue
        try:
            d = _json_mod.loads(rec.raw_json or "{}")
        except Exception:
            d = {}
        d["ai_score"] = rec.ai_score
        d["ai_verdict"] = rec.ai_verdict
        d["notion_page_id"] = rec.notion_page_id
        d["_db_id"] = rec.id  # carry DB id for write-back
        listing_dicts.append(d)

    if not listing_dicts:
        return {"pushed": 0, "skipped": 0, "errors": []}

    # 1. Dedup check
    await mark_notion_duplicates(listing_dicts)

    # 2. Push non-skipped
    to_push = [d for d in listing_dicts if not d.get("notion_skipped")]
    errors: list[str] = []
    if to_push:
        try:
            await push_listings(to_push)
        except Exception as exc:
            errors.append(str(exc))

    # 3. Write notion_page_id back to DB (newly pushed + backfill for skipped-but-null)
    for d in listing_dicts:
        page_id = d.get("notion_page_id")
        if not page_id:
            continue
        db_id = d.get("_db_id")
        rec = records.get(db_id)
        if rec and rec.notion_page_id != page_id:
            rec.notion_page_id = page_id
            session.add(rec)
    session.commit()

    pushed = sum(
        1 for d in listing_dicts
        if not d.get("notion_skipped") and d.get("notion_page_id")
    )
    skipped = sum(1 for d in listing_dicts if d.get("notion_skipped"))

    return {"pushed": pushed, "skipped": skipped, "errors": errors}
```

- [ ] **Step 5: Run all listing tests**

```bash
python -m pytest tests/backend/test_listings.py -v
```

Expected: all `PASSED`

- [ ] **Step 6: Commit**

```bash
git add backend/routers/listings.py tests/backend/test_listings.py
git commit -m "feat: add POST /listings/notion-push endpoint with dedup and DB write-back"
```

---

## Chunk 2: Frontend — Listings page

### Task 3: Multi-row selection + bulk push + single detail push

**Files:**
- Modify: `frontend/pages/4_Listings.py`

The Listings page currently uses `selection_mode="single-row"` and shows a detail panel for the one selected row. We change it to `"multi-row"`, show a push button for any selection, and only show the detail panel when exactly one row is selected.

- [ ] **Step 1: Switch to multi-row selection**

In `frontend/pages/4_Listings.py`, change:

```python
# old
    selection_mode="single-row",
# new
    selection_mode="multi-row",
```

- [ ] **Step 2: Replace the post-dataframe section**

In `4_Listings.py`, replace from the comment line (line 107, exact text including trailing dashes):

```
# ── Selected listing detail ───────────────────────────────────────────────────
```

…to the end of the file, with:

```python
# ── Selection actions ─────────────────────────────────────────────────────────
selected_rows = event.selection.rows if hasattr(event, "selection") else []

if len(selected_rows) > 1:
    selected_ids = [listings[i]["id"] for i in selected_rows]
    if st.button(f"Push {len(selected_ids)} listing(s) to Notion", type="primary"):
        try:
            result = api.post("/listings/notion-push", json={"listing_ids": selected_ids})
            st.success(
                f"Notion push complete: {result['pushed']} pushed, "
                f"{result['skipped']} already in Notion."
            )
            if result.get("errors"):
                st.error(f"Errors: {result['errors']}")
            st.rerun()
        except Exception as e:
            st.error(f"Push failed: {e}")

# ── Selected listing detail (only when exactly one row selected) ──────────────
if len(selected_rows) == 1:
    idx = selected_rows[0]
    listing = listings[idx]

    st.subheader("Listing Detail")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"**{listing.get('title', '')}**")
        st.write(f"**Price:** {listing.get('price', '—')}")
        st.write(f"**Area:** {listing.get('sqm', '—')} sqm · {listing.get('rooms', '—')} rooms")
        st.write(f"**Location:** {listing.get('area', '—')}, {listing.get('city', '—')}")
        st.write(f"**Config:** {listing.get('config_name', '—')}")
        st.write(f"**Scraped:** {str(listing.get('scraped_at', ''))[:19]}")
        st.link_button("Open listing", listing.get("url", "#"))
    with d2:
        score = listing.get("ai_score")
        if score is not None:
            color = "green" if score >= 70 else ("orange" if score >= 40 else "red")
            st.markdown(f"**AI Score:** :{color}[{score}/100]")
        else:
            st.write("**AI Score:** not scored")
        verdict = listing.get("ai_verdict")
        if verdict:
            st.markdown("**AI Verdict:**")
            st.write(verdict)
        if listing.get("notion_page_id"):
            st.write(f"**Notion:** {listing['notion_page_id']}")
            st.button("Already in Notion", disabled=True)
        else:
            if st.button("Push this listing to Notion"):
                try:
                    result = api.post(
                        "/listings/notion-push",
                        json={"listing_ids": [listing["id"]]},
                    )
                    st.success(
                        f"Done: {result['pushed']} pushed, {result['skipped']} skipped."
                    )
                    if result.get("errors"):
                        st.error(f"Errors: {result['errors']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Push failed: {e}")
```

- [ ] **Step 3: Manual smoke test**

Start the backend and frontend, navigate to the Listings page. Verify:
- Multiple rows can be selected.
- "Push N listing(s) to Notion" bulk button appears only when **more than one** row is selected.
- When exactly one row is selected, only the detail panel push button is shown (no duplicate bulk button).
- Detail panel only appears when exactly one row is selected.
- "Already in Notion" (disabled) shown for listings with `notion_page_id`.

- [ ] **Step 4: Commit**

```bash
git add frontend/pages/4_Listings.py
git commit -m "feat: add multi-row selection and Notion push buttons to Listings page"
```

---

## Chunk 3: Frontend — Monitor page

### Task 4: Per-job "Push to Notion" button

**Files:**
- Modify: `frontend/pages/2_Monitor.py`

- [ ] **Step 1: Add push button to completed job expanders**

In `frontend/pages/2_Monitor.py`, inside the `render` function, find and replace:

```python
                c_del, c_content = st.columns([1, 5])
                with c_del:
                    if st.button("Delete", key=f"del_rec_{job['id']}", use_container_width=True):
                        try:
                            api.delete(f"/jobs/{job['id']}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                with c_content:
```

With:

```python
                c_del, c_notion, c_content = st.columns([1, 1, 4])
                with c_del:
                    if st.button("Delete", key=f"del_rec_{job['id']}", use_container_width=True):
                        try:
                            api.delete(f"/jobs/{job['id']}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                with c_notion:
                    if job["status"] == "done" and st.button("Push to Notion", key=f"notion_{job['id']}", use_container_width=True):
                        try:
                            job_listings = api.get(
                                "/listings",
                                params={"job_id": job["id"], "limit": 1000},
                            )
                            if not job_listings:
                                st.warning("No listings found for this job.")
                            else:
                                listing_ids = [l["id"] for l in job_listings]
                                result = api.post(
                                    "/listings/notion-push",
                                    json={"listing_ids": listing_ids},
                                )
                                st.success(
                                    f"Notion push complete: {result['pushed']} pushed, "
                                    f"{result['skipped']} already in Notion."
                                )
                                if result.get("errors"):
                                    st.error(f"Errors: {result['errors']}")
                                st.rerun()
                        except Exception as e:
                            st.error(f"Push failed: {e}")
                with c_content:
```

- [ ] **Step 2: Manual smoke test**

Navigate to the Monitor page. On a completed job expander:
- Verify "Push to Notion" button appears next to "Delete".
- If Notion credentials are not set, a `Push failed: ...` error is shown.
- If no listings exist for the job, "No listings found" warning appears.

- [ ] **Step 3: Commit**

```bash
git add frontend/pages/2_Monitor.py
git commit -m "feat: add per-job Push to Notion button in Monitor page"
```

---

## Final: Run full test suite

- [ ] **Step 1: Run all backend tests**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape
python -m pytest tests/backend/ -v
```

Expected: all passing.

- [ ] **Step 2: Run all tests**

```bash
python -m pytest tests/ -v --ignore=tests/test_immobiliare.py
```

Expected: all passing.
