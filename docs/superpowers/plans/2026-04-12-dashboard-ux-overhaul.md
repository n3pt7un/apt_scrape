# Dashboard UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overhaul the Streamlit dashboard with a Palantir dark theme, a merged Operations health-monitoring page, a redesigned Listings table, and streamlined 5-page navigation.

**Architecture:** Global CSS injection via a shared `theme.py` module. New `/jobs/health` backend endpoint computes pipeline health server-side. Monitor + Stats pages merge into a single Operations page. Plotly replaces `st.bar_chart` for dark-themed interactive charts. Listings gets horizontal filters, €/sqm column, and inline detail.

**Tech Stack:** Streamlit (custom CSS), Plotly (dark charts), FastAPI (health endpoint), SQLModel (existing DB), httpx (API client)

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `src/frontend/theme.py` | Dark theme CSS injection, color constants, HTML helper functions |
| `src/frontend/pages/1_Operations.py` | Merged Monitor + Stats: health strip, trend charts, activity feed |

### Modified files
| File | Changes |
|------|---------|
| `src/frontend/app.py` | Redirect to Operations instead of showing Home page |
| `src/frontend/pages/2_Listings.py` | Renamed from `4_Listings.py`, full redesign with horizontal filters, €/sqm, inline detail |
| `src/frontend/pages/3_Search_Configs.py` | Renamed from `1_Search_Configs.py`, add `theme.apply_theme()` call |
| `src/frontend/pages/4_Preferences.py` | Renamed from `3_Preferences.py`, add `theme.apply_theme()` call |
| `src/frontend/pages/5_Site_Settings.py` | Keep name, add `theme.apply_theme()` call |
| `src/backend/routers/jobs.py` | Add `/jobs/health` endpoint, extend `/jobs/stats/overall` with timeline + price_per_sqm_by_area |
| `src/backend/routers/listings.py` | Add `price_per_sqm` computed field, add `area` and `days` filters |
| `src/frontend/api.py` | No changes needed (generic HTTP client) |

### Deleted files
| File | Reason |
|------|--------|
| `src/frontend/pages/2_Monitor.py` | Merged into Operations |
| `src/frontend/pages/6_Stats.py` | Merged into Operations |
| `src/frontend/pages/1_Search_Configs.py` | Renamed to `3_Search_Configs.py` |
| `src/frontend/pages/3_Preferences.py` | Renamed to `4_Preferences.py` |
| `src/frontend/pages/4_Listings.py` | Renamed to `2_Listings.py` |

---

## Task 1: Dark Theme Module

**Files:**
- Create: `src/frontend/theme.py`

- [ ] **Step 1: Create theme.py with color constants and CSS**

```python
"""frontend.theme — Palantir dark theme for the Streamlit dashboard."""

# ── Color palette ────────────────────────────────────────────────────────────
BG_PRIMARY = "#0a0a0a"
BG_CARD = "#111111"
BG_ELEVATED = "#1a1a1a"
BORDER_SUBTLE = "#2a2a2a"
BORDER_EMPHASIS = "#333333"
TEXT_PRIMARY = "#e0e0e0"
TEXT_SECONDARY = "#888888"
TEXT_MUTED = "#555555"

GREEN = "#00d97e"
AMBER = "#f7c948"
RED = "#e63757"
BLUE = "#0061ff"
CYAN = "#00b8d9"

# Mapping for health status strings from /jobs/health
STATUS_COLORS = {
    "healthy": GREEN,
    "stable": GREEN,
    "warning": AMBER,
    "declining": AMBER,
    "rising": AMBER,
    "critical": RED,
    "falling": GREEN,  # dupe rate falling is good
}

# ── Plotly layout template ───────────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor=BG_CARD,
    plot_bgcolor=BG_CARD,
    font=dict(color=TEXT_PRIMARY, family="system-ui, -apple-system, sans-serif"),
    xaxis=dict(gridcolor=BG_ELEVATED, zerolinecolor=BORDER_SUBTLE),
    yaxis=dict(gridcolor=BG_ELEVATED, zerolinecolor=BORDER_SUBTLE),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_SECONDARY)),
    margin=dict(l=40, r=20, t=40, b=40),
)

MONO_FONT = "'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace"

# ── CSS ──────────────────────────────────────────────────────────────────────
_CSS = f"""
<style>
/* === Base === */
.stApp, .stApp > header {{
    background-color: {BG_PRIMARY} !important;
    color: {TEXT_PRIMARY} !important;
}}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background-color: #0d0d0d !important;
    border-right: 1px solid {BORDER_SUBTLE} !important;
}}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown span,
section[data-testid="stSidebar"] label {{
    color: {TEXT_SECONDARY} !important;
}}

/* Active sidebar nav link */
section[data-testid="stSidebar"] a[aria-current="page"] {{
    border-left: 3px solid {BLUE} !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}}

/* Headers */
.stApp h1, .stApp h2, .stApp h3 {{
    color: {TEXT_PRIMARY} !important;
}}
.stApp h1 {{
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
}}

/* Metric cards */
div[data-testid="stMetric"] {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
    padding: 16px !important;
}}
div[data-testid="stMetric"] label {{
    color: {TEXT_SECONDARY} !important;
    font-size: 0.75rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
    color: {TEXT_PRIMARY} !important;
    font-family: {MONO_FONT} !important;
}}

/* Dataframe */
.stDataFrame {{
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
}}

/* Inputs */
.stTextInput input, .stTextArea textarea, .stNumberInput input,
.stSelectbox > div > div {{
    background-color: {BG_ELEVATED} !important;
    color: {TEXT_PRIMARY} !important;
    border-color: {BORDER_SUBTLE} !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {{
    border-color: {BLUE} !important;
    box-shadow: 0 0 0 1px {BLUE} !important;
}}

/* Buttons — outlined default */
.stButton > button {{
    background-color: transparent !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_EMPHASIS} !important;
    border-radius: 6px !important;
    transition: all 0.15s ease !important;
}}
.stButton > button:hover {{
    border-color: {BLUE} !important;
    color: {BLUE} !important;
}}
/* Primary button — filled */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stFormSubmitButton"] {{
    background-color: {BLUE} !important;
    color: #ffffff !important;
    border-color: {BLUE} !important;
}}

/* Expander */
.streamlit-expanderHeader {{
    background-color: {BG_CARD} !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 6px !important;
}}
details[data-testid="stExpander"] {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
}}

/* Container borders */
div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] > div > div.element-container {{
    color: {TEXT_PRIMARY} !important;
}}
div.stContainer {{
    border-color: {BORDER_SUBTLE} !important;
}}

/* Dividers */
hr {{
    border-color: {BORDER_SUBTLE} !important;
}}

/* Captions */
.stCaption, .stApp .stMarkdown small {{
    color: {TEXT_MUTED} !important;
}}

/* Code blocks */
.stCode, .stApp pre {{
    background-color: {BG_ELEVATED} !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
}}

/* Alerts */
.stAlert {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    background-color: transparent !important;
}}
.stTabs [data-baseweb="tab"] {{
    color: {TEXT_SECONDARY} !important;
}}
.stTabs [aria-selected="true"] {{
    color: {TEXT_PRIMARY} !important;
    border-bottom-color: {BLUE} !important;
}}

/* Selectbox dropdown */
div[data-baseweb="select"] {{
    background-color: {BG_ELEVATED} !important;
}}
div[data-baseweb="popover"] {{
    background-color: {BG_ELEVATED} !important;
}}
div[data-baseweb="popover"] li {{
    color: {TEXT_PRIMARY} !important;
}}

/* Slider */
.stSlider > div > div > div {{
    color: {TEXT_SECONDARY} !important;
}}

/* Forms */
div[data-testid="stForm"] {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
    padding: 1rem !important;
}}

/* Dialog */
div[data-testid="stDialog"] > div {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_EMPHASIS} !important;
}}

/* Multiselect */
span[data-baseweb="tag"] {{
    background-color: {BORDER_EMPHASIS} !important;
    color: {TEXT_PRIMARY} !important;
}}

/* Toggle */
div[data-testid="stToggle"] label span {{
    color: {TEXT_PRIMARY} !important;
}}
</style>
"""


def apply_theme():
    """Inject the Palantir dark theme CSS. Call at the top of every page."""
    import streamlit as st
    st.markdown(_CSS, unsafe_allow_html=True)


def status_dot(color: str, size: int = 8) -> str:
    """Return an inline HTML span for a colored status dot."""
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'border-radius:50%;background:{color};margin-right:6px;'
        f'vertical-align:middle;"></span>'
    )


def mono(value) -> str:
    """Wrap a value in monospace font styling."""
    return f'<span style="font-family:{MONO_FONT};color:{TEXT_PRIMARY}">{value}</span>'


def health_color(status: str) -> str:
    """Map a health status string to its accent color."""
    return STATUS_COLORS.get(status, TEXT_MUTED)
```

- [ ] **Step 2: Verify the module imports correctly**

Run:
```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -c "from frontend.theme import apply_theme, status_dot, mono, health_color, PLOTLY_LAYOUT; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/frontend/theme.py
git commit -m "feat: add Palantir dark theme module with CSS injection and helpers"
```

---

## Task 2: Backend Health Endpoint

**Files:**
- Modify: `src/backend/routers/jobs.py`

- [ ] **Step 1: Add the `/jobs/health` endpoint**

Add these imports at the top of `src/backend/routers/jobs.py` (after existing imports):

```python
from datetime import datetime, timedelta
```

Add this endpoint **after** the existing `overall_stats` function (after line 70):

```python
@router.get("/health")
def pipeline_health(session: Session = Depends(get_session)):
    """Compute operational health indicators for the dashboard."""
    from backend.db import SearchConfig
    now = datetime.utcnow()

    # --- Pipeline status ---
    last_job = session.exec(
        select(Job).order_by(Job.started_at.desc()).limit(1)
    ).first()

    if not last_job:
        pipeline_status = "warning"
        last_job_status = None
        last_job_ago_sec = None
    else:
        last_job_status = last_job.status
        finished = last_job.finished_at or last_job.started_at
        last_job_ago_sec = (now - finished).total_seconds()
        if last_job.status == "failed":
            pipeline_status = "critical"
        elif last_job_ago_sec > 6 * 3600:
            pipeline_status = "warning"
        else:
            pipeline_status = "healthy"

    # --- Schedule health ---
    configs = session.exec(
        select(SearchConfig).where(SearchConfig.enabled == True)
    ).all()
    missed_schedules = []
    schedule_health = "healthy"

    for cfg in configs:
        days = cfg.schedule_days
        if isinstance(days, str):
            import json as _j
            try:
                days = _j.loads(days)
            except Exception:
                days = []
        if not days:
            continue
        # Find last job for this config
        last_cfg_job = session.exec(
            select(Job)
            .where(Job.config_id == cfg.id)
            .order_by(Job.started_at.desc())
            .limit(1)
        ).first()
        if not last_cfg_job:
            missed_schedules.append(cfg.name)
            schedule_health = "critical"
            continue
        ago = (now - (last_cfg_job.finished_at or last_cfg_job.started_at)).total_seconds()
        if ago > 6 * 3600:
            missed_schedules.append(cfg.name)
            if schedule_health != "critical":
                schedule_health = "critical"
        elif ago > 3600:
            if schedule_health == "healthy":
                schedule_health = "warning"

    # --- Yield trend (7-day windows) ---
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    recent_jobs = session.exec(
        select(Job).where(
            Job.status == "done",
            Job.started_at >= seven_days_ago,
        )
    ).all()
    prev_jobs = session.exec(
        select(Job).where(
            Job.status == "done",
            Job.started_at >= fourteen_days_ago,
            Job.started_at < seven_days_ago,
        )
    ).all()

    def _avg_yield(jobs_list):
        counts = [j.listing_count or 0 for j in jobs_list]
        return round(sum(counts) / len(counts), 1) if counts else 0

    yield_7d = _avg_yield(recent_jobs)
    yield_prev_7d = _avg_yield(prev_jobs)

    if yield_prev_7d == 0:
        yield_trend = "stable"
    else:
        pct_change = (yield_7d - yield_prev_7d) / yield_prev_7d
        if pct_change < -0.5:
            yield_trend = "critical"
        elif pct_change < -0.2:
            yield_trend = "declining"
        else:
            yield_trend = "stable"

    # --- Dupe rate (7-day) ---
    total_scraped_7d = sum(j.scraped_count or 0 for j in recent_jobs)
    total_dupes_7d = sum(j.dupes_removed or 0 for j in recent_jobs)
    dupe_rate_7d = round(total_dupes_7d / total_scraped_7d, 2) if total_scraped_7d else 0

    # Compare to previous 7d
    total_scraped_prev = sum(j.scraped_count or 0 for j in prev_jobs)
    total_dupes_prev = sum(j.dupes_removed or 0 for j in prev_jobs)
    dupe_rate_prev = round(total_dupes_prev / total_scraped_prev, 2) if total_scraped_prev else 0

    if dupe_rate_7d > dupe_rate_prev + 0.1:
        dupe_rate_trend = "rising"
    elif dupe_rate_7d < dupe_rate_prev - 0.1:
        dupe_rate_trend = "falling"
    else:
        dupe_rate_trend = "stable"

    # --- AI cost (7-day) ---
    ai_cost_7d = round(sum(j.ai_cost_usd or 0 for j in recent_jobs), 4)
    ai_cost_prev_7d = round(sum(j.ai_cost_usd or 0 for j in prev_jobs), 4)

    return {
        "pipeline_status": pipeline_status,
        "last_job_status": last_job_status,
        "last_job_ago_sec": round(last_job_ago_sec) if last_job_ago_sec is not None else None,
        "schedule_health": schedule_health,
        "missed_schedules": missed_schedules,
        "yield_trend": yield_trend,
        "yield_7d_avg": yield_7d,
        "yield_prev_7d_avg": yield_prev_7d,
        "dupe_rate_7d": dupe_rate_7d,
        "dupe_rate_trend": dupe_rate_trend,
        "ai_cost_7d": ai_cost_7d,
        "ai_cost_prev_7d": ai_cost_prev_7d,
    }
```

- [ ] **Step 2: Extend `overall_stats` with timeline and price_per_sqm_by_area**

Replace the existing `overall_stats` function (lines 31-70 of `src/backend/routers/jobs.py`) with:

```python
@router.get("/stats/overall")
def overall_stats(session: Session = Depends(get_session)):
    """Aggregate stats across all completed jobs."""
    from backend.db import SearchConfig

    jobs = session.exec(select(Job).where(Job.status == "done")).all()

    total_runs = len(jobs)
    total_listings = sum(j.listing_count or 0 for j in jobs)
    total_scraped = sum(j.scraped_count or 0 for j in jobs)
    total_dupes = sum(j.dupes_removed or 0 for j in jobs)
    total_tokens = sum(j.ai_tokens_used or 0 for j in jobs)
    total_cost = sum(j.ai_cost_usd or 0.0 for j in jobs)

    total_duration_sec = sum(
        (j.finished_at - j.started_at).total_seconds()
        for j in jobs
        if j.finished_at and j.started_at
    )

    # Config name lookup
    config_ids = {j.config_id for j in jobs}
    configs = {
        c.id: c.name
        for c in session.exec(
            select(SearchConfig).where(SearchConfig.id.in_(config_ids))
        ).all()
    } if config_ids else {}

    # All listings for price calculations
    listings = session.exec(select(Listing)).all()
    prices = [p for l in listings if (p := _parse_price(l.price or "")) is not None and p > 0]
    avg_price = round(sum(prices) / len(prices), 0) if prices else None

    # Area distribution
    area_dist: dict[str, int] = {}
    for l in listings:
        a = l.area or ""
        area_dist[a] = area_dist.get(a, 0) + 1

    # Price per sqm by area
    area_price_sqm: dict[str, list[float]] = {}
    for l in listings:
        price = _parse_price(l.price or "")
        sqm = _parse_price(l.sqm or "")  # reuse parser for numeric extraction
        if price and sqm and sqm > 0:
            a = l.area or ""
            area_price_sqm.setdefault(a, []).append(price / sqm)
    price_per_sqm_by_area = {
        a: round(sum(vals) / len(vals), 1)
        for a, vals in area_price_sqm.items()
        if vals
    }

    # Timeline: per-job objects
    timeline = []
    for job in jobs:
        duration_sec = None
        if job.finished_at and job.started_at:
            duration_sec = round((job.finished_at - job.started_at).total_seconds(), 1)

        job_listings = [l for l in listings if l.job_id == job.id]
        job_prices = [p for l in job_listings if (p := _parse_price(l.price or "")) is not None and p > 0]
        job_avg_price = round(sum(job_prices) / len(job_prices), 0) if job_prices else None

        # Price per sqm for this job
        job_sqm_prices = []
        for l in job_listings:
            pr = _parse_price(l.price or "")
            sq = _parse_price(l.sqm or "")
            if pr and sq and sq > 0:
                job_sqm_prices.append(pr / sq)
        job_avg_price_per_sqm = round(sum(job_sqm_prices) / len(job_sqm_prices), 1) if job_sqm_prices else None

        stored_area_stats = {}
        try:
            stored_area_stats = json.loads(job.area_stats or "{}")
        except Exception:
            pass

        timeline.append({
            "job_id": job.id,
            "config_name": configs.get(job.config_id, f"#{job.config_id}"),
            "started_at": job.started_at,
            "finished_at": job.finished_at,
            "duration_sec": duration_sec,
            "scraped_count": job.scraped_count or 0,
            "listing_count": job.listing_count or 0,
            "dupes_removed": job.dupes_removed or 0,
            "ai_tokens_used": job.ai_tokens_used or 0,
            "ai_cost_usd": job.ai_cost_usd or 0,
            "avg_price_eur": job_avg_price,
            "avg_price_per_sqm": job_avg_price_per_sqm,
            "area_stats": stored_area_stats,
            "status": job.status,
        })

    return {
        "total_runs": total_runs,
        "total_listings": total_listings,
        "total_scraped": total_scraped,
        "total_dupes_removed": total_dupes,
        "total_ai_tokens": total_tokens,
        "total_ai_cost_usd": round(total_cost, 4),
        "total_duration_sec": round(total_duration_sec, 0),
        "avg_price_eur": avg_price,
        "area_distribution": area_dist,
        "price_per_sqm_by_area": price_per_sqm_by_area,
        "timeline": timeline,
    }
```

- [ ] **Step 3: Add `price_per_sqm` to listings response**

In `src/backend/routers/listings.py`, add the `_parse_price` helper and the computed field. Add this import and helper at the top of the file (after line 10):

```python
import re


def _parse_price(price_str: str) -> Optional[float]:
    """Extract a numeric value from strings like '€ 1.200/mese' or '45 m²'."""
    cleaned = price_str.replace(".", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    return float(m.group(1)) if m else None
```

Then in the `list_listings` function, modify the result-building loop (around line 55-61) to add price_per_sqm:

Replace:
```python
    result = []
    for lst in listings:
        d = lst.model_dump()
        d.pop("raw_json", None)
        d["config_name"] = configs.get(lst.config_id, "")
        result.append(d)
    return result
```

With:
```python
    result = []
    for lst in listings:
        d = lst.model_dump()
        d.pop("raw_json", None)
        d["config_name"] = configs.get(lst.config_id, "")
        # Computed: price per sqm
        price = _parse_price(lst.price or "")
        sqm = _parse_price(lst.sqm or "")
        d["price_per_sqm"] = round(price / sqm, 1) if price and sqm and sqm > 0 else None
        result.append(d)
    return result
```

Also add `area` and `days` query params to `list_listings`. Update the function signature and body — replace lines 17-46:

```python
@router.get("")
def list_listings(
    config_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    min_score: Optional[int] = Query(None),
    max_score: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    area: Optional[str] = Query(None),
    days: Optional[int] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    session: Session = Depends(get_session),
):
    stmt = select(Listing).order_by(Listing.scraped_at.desc())
    if config_id is not None:
        stmt = stmt.where(Listing.config_id == config_id)
    if job_id is not None:
        stmt = stmt.where(Listing.job_id == job_id)
    if min_score is not None:
        stmt = stmt.where(Listing.ai_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(Listing.ai_score <= max_score)
    if search:
        q = f"%{search}%"
        stmt = stmt.where(
            or_(
                Listing.title.like(q),
                Listing.area.like(q),
                Listing.city.like(q),
            )
        )
    if area:
        stmt = stmt.where(Listing.area == area)
    if days is not None and days > 0:
        from datetime import datetime, timedelta
        cutoff = datetime.utcnow() - timedelta(days=days)
        stmt = stmt.where(Listing.scraped_at >= cutoff)
    stmt = stmt.offset(offset).limit(limit)
```

- [ ] **Step 4: Test the new endpoint manually**

Run the backend and test:
```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
sleep 3
curl -s http://localhost:8000/jobs/health | python -m json.tool
curl -s "http://localhost:8000/jobs/stats/overall" | python -m json.tool | head -30
curl -s "http://localhost:8000/listings?days=7&limit=2" | python -m json.tool | head -20
kill %1
```
Expected: JSON responses with the new fields. `/jobs/health` returns `pipeline_status`, `schedule_health`, etc. `/jobs/stats/overall` includes `timeline` and `price_per_sqm_by_area`. Listings include `price_per_sqm`.

- [ ] **Step 5: Commit**

```bash
git add src/backend/routers/jobs.py src/backend/routers/listings.py
git commit -m "feat: add /jobs/health endpoint, extend stats with timeline, add price_per_sqm to listings"
```

---

## Task 3: Operations Page

**Files:**
- Create: `src/frontend/pages/1_Operations.py`
- Delete: `src/frontend/pages/2_Monitor.py`
- Delete: `src/frontend/pages/6_Stats.py`

- [ ] **Step 1: Create the Operations page**

```python
"""Streamlit page: Operations — pipeline health, trends, and activity feed."""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import api
import theme

st.set_page_config(page_title="Operations", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Operations")

# ── Config name lookup ───────────────────────────────────────────────────────
try:
    configs_list = api.get("/configs")
    config_names = {c["id"]: c["name"] for c in configs_list}
except Exception:
    configs_list = []
    config_names = {}


def cfg_label(config_id):
    name = config_names.get(config_id)
    return f"{name}" if name else f"#{config_id}"


def _fmt_duration(sec):
    if sec is None:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    return f"{sec // 60}m {sec % 60}s"


def _fmt_ago(seconds):
    """Human-friendly relative time."""
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


# ══════════════════════════════════════════════════════════════════════════════
# ZONE 1: Health Strip
# ══════════════════════════════════════════════════════════════════════════════
try:
    health = api.get("/jobs/health")
except Exception:
    health = {}

if health:
    h1, h2, h3, h4, h5 = st.columns(5)

    def _health_metric(col, label, status_key, value):
        status = health.get(status_key, "healthy")
        color = theme.health_color(status)
        dot = theme.status_dot(color, size=10)
        col.markdown(
            f'{dot} <span style="color:{theme.TEXT_SECONDARY};font-size:0.75rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">{label}</span><br>'
            f'<span style="font-family:{theme.MONO_FONT};font-size:1.2rem;'
            f'color:{theme.TEXT_PRIMARY}">{value}</span>',
            unsafe_allow_html=True,
        )

    pipeline_val = health.get("last_job_status", "—")
    if health.get("last_job_ago_sec") is not None:
        pipeline_val += f" · {_fmt_ago(health['last_job_ago_sec'])}"
    _health_metric(h1, "Pipeline", "pipeline_status", pipeline_val)

    sched_val = "all on time"
    missed = health.get("missed_schedules", [])
    if missed:
        sched_val = f"{len(missed)} missed"
    _health_metric(h2, "Schedule", "schedule_health", sched_val)

    yield_val = f"{health.get('yield_7d_avg', 0):.0f}/run"
    _health_metric(h3, "Yield (7d)", "yield_trend", yield_val)

    dupe_val = f"{health.get('dupe_rate_7d', 0):.0%}"
    dupe_status = health.get("dupe_rate_trend", "stable")
    # Override: map dupe rate value to color directly
    dupe_pct = health.get("dupe_rate_7d", 0)
    if dupe_pct > 0.6:
        dupe_color_status = "critical"
    elif dupe_pct > 0.3:
        dupe_color_status = "warning"
    else:
        dupe_color_status = "healthy"
    color = theme.health_color(dupe_color_status)
    dot = theme.status_dot(color, size=10)
    h4.markdown(
        f'{dot} <span style="color:{theme.TEXT_SECONDARY};font-size:0.75rem;'
        f'text-transform:uppercase;letter-spacing:0.05em">Dupe Rate</span><br>'
        f'<span style="font-family:{theme.MONO_FONT};font-size:1.2rem;'
        f'color:{theme.TEXT_PRIMARY}">{dupe_val}</span>'
        f' <span style="color:{theme.TEXT_MUTED};font-size:0.75rem">{dupe_status}</span>',
        unsafe_allow_html=True,
    )

    cost_val = f"${health.get('ai_cost_7d', 0):.2f}"
    cost_prev = health.get("ai_cost_prev_7d", 0)
    cost_7d = health.get("ai_cost_7d", 0)
    if cost_prev > 0 and cost_7d > cost_prev * 2:
        cost_status = "warning"
    else:
        cost_status = "healthy"
    _health_metric(h5, "AI Cost (7d)", cost_status, cost_val)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ZONE 2: Trend Charts
# ══════════════════════════════════════════════════════════════════════════════
try:
    overall = api.get("/jobs/stats/overall")
except Exception:
    overall = {}

timeline = overall.get("timeline", [])

if timeline:
    chart_left, chart_right = st.columns(2)

    with chart_left:
        # Listings over time — stacked area
        st.markdown(
            f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">Listings Over Time</span>',
            unsafe_allow_html=True,
        )
        dates = [t["started_at"] for t in timeline]
        unique = [t["listing_count"] for t in timeline]
        dupes = [t["dupes_removed"] for t in timeline]

        fig_listings = go.Figure()
        fig_listings.add_trace(go.Scatter(
            x=dates, y=unique, mode="lines", name="Unique",
            fill="tozeroy", line=dict(color=theme.GREEN, width=2),
            fillcolor=f"rgba(0,217,126,0.15)",
        ))
        fig_listings.add_trace(go.Scatter(
            x=dates, y=dupes, mode="lines", name="Dupes",
            fill="tozeroy", line=dict(color=theme.RED, width=2),
            fillcolor=f"rgba(230,55,87,0.15)",
        ))
        fig_listings.update_layout(**theme.PLOTLY_LAYOUT, height=280, showlegend=True)
        st.plotly_chart(fig_listings, use_container_width=True)

        # Success rate timeline
        st.markdown(
            f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">Job Success Rate</span>',
            unsafe_allow_html=True,
        )
        try:
            all_jobs = api.get("/jobs")
        except Exception:
            all_jobs = []

        if all_jobs:
            # Calculate rolling success rate (by job order, not exact 7-day window)
            sorted_jobs = sorted(all_jobs, key=lambda j: j.get("started_at", ""))
            success_dates = []
            success_rates = []
            window = 7
            for i, j in enumerate(sorted_jobs):
                if j.get("status") in ("done", "failed"):
                    chunk = sorted_jobs[max(0, i - window + 1):i + 1]
                    chunk = [c for c in chunk if c.get("status") in ("done", "failed")]
                    if chunk:
                        rate = sum(1 for c in chunk if c["status"] == "done") / len(chunk)
                        success_dates.append(j.get("started_at"))
                        success_rates.append(round(rate * 100, 1))

            if success_dates:
                fig_success = go.Figure()
                fig_success.add_trace(go.Scatter(
                    x=success_dates, y=success_rates, mode="lines",
                    line=dict(color=theme.CYAN, width=2),
                    fill="tozeroy", fillcolor=f"rgba(0,184,217,0.1)",
                ))
                fig_success.update_layout(
                    **theme.PLOTLY_LAYOUT, height=200, showlegend=False,
                    yaxis=dict(
                        **theme.PLOTLY_LAYOUT["yaxis"],
                        range=[0, 105], ticksuffix="%",
                    ),
                )
                st.plotly_chart(fig_success, use_container_width=True)

    with chart_right:
        # Price per sqm by area
        price_sqm = overall.get("price_per_sqm_by_area", {})
        if price_sqm:
            st.markdown(
                f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
                f'text-transform:uppercase;letter-spacing:0.05em">Price per sqm by Area</span>',
                unsafe_allow_html=True,
            )
            # Sort by price descending
            sorted_areas = sorted(price_sqm.items(), key=lambda x: -x[1])
            areas = [a[0] or "whole city" for a in sorted_areas]
            values = [a[1] for a in sorted_areas]

            fig_price = go.Figure()
            fig_price.add_trace(go.Bar(
                x=values, y=areas, orientation="h",
                marker=dict(color=theme.BLUE, line=dict(width=0)),
                text=[f"€{v:.0f}" for v in values],
                textposition="outside",
                textfont=dict(color=theme.TEXT_SECONDARY, size=11),
            ))
            fig_price.update_layout(
                **theme.PLOTLY_LAYOUT, height=280,
                yaxis=dict(**theme.PLOTLY_LAYOUT["yaxis"], autorange="reversed"),
                xaxis=dict(**theme.PLOTLY_LAYOUT["xaxis"], title="€/sqm"),
            )
            st.plotly_chart(fig_price, use_container_width=True)

        # Run duration trend
        st.markdown(
            f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">Run Duration Trend</span>',
            unsafe_allow_html=True,
        )
        dur_dates = [t["started_at"] for t in timeline if t.get("duration_sec")]
        dur_values = [t["duration_sec"] for t in timeline if t.get("duration_sec")]

        if dur_dates:
            fig_dur = go.Figure()
            fig_dur.add_trace(go.Scatter(
                x=dur_dates, y=dur_values, mode="lines+markers",
                line=dict(color=theme.AMBER, width=2),
                marker=dict(size=5, color=theme.AMBER),
            ))
            fig_dur.update_layout(
                **theme.PLOTLY_LAYOUT, height=200, showlegend=False,
                yaxis=dict(**theme.PLOTLY_LAYOUT["yaxis"], title="seconds"),
            )
            st.plotly_chart(fig_dur, use_container_width=True)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ZONE 3: Recent Activity Feed
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
    f'text-transform:uppercase;letter-spacing:0.05em">Recent Activity</span>',
    unsafe_allow_html=True,
)

try:
    jobs = api.get("/jobs")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    jobs = []

STATUS_COLORS_MAP = {
    "running": theme.AMBER,
    "done": theme.GREEN,
    "failed": theme.RED,
    "pending": theme.TEXT_MUTED,
}

running = [j for j in jobs if j["status"] == "running"]
recent = [j for j in jobs if j["status"] != "running"]

# Active jobs first
if running:
    for job in running:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                dot = theme.status_dot(theme.AMBER, size=10)
                st.markdown(
                    f'{dot} **{cfg_label(job["config_id"])}** · '
                    f'<span style="font-family:{theme.MONO_FONT};color:{theme.AMBER}">running</span> · '
                    f'started {str(job.get("started_at", ""))[:16]}',
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("Cancel", key=f"cancel_{job['id']}", type="primary", use_container_width=True):
                    try:
                        api.post(f"/jobs/{job['id']}/cancel")
                        st.success("Job cancelled.")
                    except Exception as e:
                        st.error(f"Cancel failed: {e}")
                    time.sleep(1)
                    st.rerun()
            log_lines = (job.get("log") or "").strip().split("\n")
            st.code("\n".join(log_lines[-10:]), language=None)

# Recent jobs
for job in recent[:20]:
    color = STATUS_COLORS_MAP.get(job["status"], theme.TEXT_MUTED)
    dot = theme.status_dot(color, size=8)

    scraped = job.get("scraped_count") or 0
    unique = job.get("listing_count") or 0
    dupes = job.get("dupes_removed") or 0
    yield_str = f"{scraped} found, {unique} unique, {dupes} dupes"

    duration = None
    if job.get("finished_at") and job.get("started_at"):
        from datetime import datetime
        try:
            start = datetime.fromisoformat(str(job["started_at"]))
            end = datetime.fromisoformat(str(job["finished_at"]))
            duration = (end - start).total_seconds()
        except Exception:
            pass

    finished_str = str(job.get("finished_at") or "")[:16]
    cost_str = f"${job.get('ai_cost_usd', 0) or 0:.2f}"

    label = (
        f"{cfg_label(job['config_id'])} · {job['status']} · "
        f"{yield_str} · {_fmt_duration(duration)} · {cost_str} · {finished_str}"
    )

    with st.expander(label, expanded=False):
        # Stats row
        if job["status"] == "done":
            try:
                stats = api.get(f"/jobs/{job['id']}/stats")
                sc1, sc2, sc3, sc4, sc5 = st.columns(5)
                sc1.metric("Found", stats.get("scraped_count") or "—")
                sc2.metric("Unique", stats.get("listing_count") or "—")
                sc3.metric("Dupes", stats.get("dupes_removed") or "—")
                avg = stats.get("avg_price_eur")
                sc4.metric("Avg price", f"€{avg:,.0f}" if avg else "—")
                sc5.metric("Duration", _fmt_duration(stats.get("duration_sec")))

                area_stats = stats.get("area_stats") or {}
                if len(area_stats) > 1:
                    st.caption("**By area:** " + "  ·  ".join(
                        f"{a or 'whole city'}: {n}" for a, n in sorted(area_stats.items(), key=lambda x: -x[1])
                    ))
            except Exception:
                pass
            st.divider()

        # Action buttons
        bc1, bc2, bc3 = st.columns([1, 1, 4])
        with bc1:
            if st.button("Delete", key=f"del_{job['id']}", use_container_width=True):
                try:
                    api.delete(f"/jobs/{job['id']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
        with bc2:
            if job["status"] == "done" and st.button("Notion Push", key=f"notion_{job['id']}", use_container_width=True):
                try:
                    job_listings = api.get("/listings", params={"job_id": job["id"], "limit": 1000})
                    if not job_listings:
                        st.warning("No listings found for this job.")
                    else:
                        listing_ids = [l["id"] for l in job_listings]
                        result = api.post("/listings/notion-push", json={"listing_ids": listing_ids})
                        st.success(f"Pushed {result['pushed']}, skipped {result['skipped']}.")
                        if result.get("errors"):
                            st.error(f"Errors: {result['errors']}")
                        st.rerun()
                except Exception as e:
                    st.error(f"Push failed: {e}")

        # Full log
        try:
            detail = api.get(f"/jobs/{job['id']}")
            st.code(detail.get("log", "(no log)"), language=None)
        except Exception as e:
            st.error(str(e))

# Auto-refresh when jobs are running
if running:
    time.sleep(5)
    st.rerun()
```

- [ ] **Step 2: Delete old Monitor and Stats pages**

```bash
rm src/frontend/pages/2_Monitor.py
rm src/frontend/pages/6_Stats.py
```

- [ ] **Step 3: Verify the page loads**

Start the frontend and navigate to the Operations page:
```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m streamlit run src/frontend/app.py --server.port 8501 &
sleep 3
curl -s http://localhost:8501 | head -5
kill %1
```
Expected: No import errors. Page renders (Streamlit returns HTML).

- [ ] **Step 4: Commit**

```bash
git add src/frontend/pages/1_Operations.py
git rm src/frontend/pages/2_Monitor.py src/frontend/pages/6_Stats.py
git commit -m "feat: add Operations page merging Monitor + Stats, with health strip and Plotly charts"
```

---

## Task 4: Listings Page Redesign

**Files:**
- Create: `src/frontend/pages/2_Listings.py` (new version)
- Delete: `src/frontend/pages/4_Listings.py` (old version)

- [ ] **Step 1: Create the redesigned Listings page**

```python
"""Streamlit page: Listings browser — redesigned with horizontal filters and inline detail."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import streamlit as st
import pandas as pd

import api
import theme

st.set_page_config(page_title="Listings", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Listings")

# ── Config & area lookups ────────────────────────────────────────────────────
try:
    configs = api.get("/configs")
except Exception:
    configs = []

config_options = {"All": None}
for c in configs:
    config_options[c["name"]] = c["id"]

# Collect known areas from configs
all_areas = set()
for c in configs:
    area = c.get("area") or ""
    for a in area.split(","):
        a = a.strip()
        if a:
            all_areas.add(a)

# ── Horizontal filter bar ────────────────────────────────────────────────────
f1, f2, f3, f4, f5, f6 = st.columns([2, 1, 1, 2, 1, 2])

with f1:
    selected_configs = st.multiselect("Config", list(config_options.keys())[1:], default=[], key="lst_configs")
with f2:
    score_min, score_max = st.slider("AI Score", 0, 100, (0, 100), key="lst_score")
with f3:
    price_min = st.number_input("Min €", min_value=0, value=0, step=100, key="lst_price_min")
with f4:
    price_max = st.number_input("Max €", min_value=0, value=0, step=100, key="lst_price_max",
                                 help="0 = no limit")
with f5:
    date_preset = st.selectbox("Period", ["7 days", "30 days", "All time"], index=0, key="lst_date")
with f6:
    search_text = st.text_input("Search title / area", placeholder="e.g. bicocca", key="lst_search")

# ── Build API params ─────────────────────────────────────────────────────────
params: dict = {"limit": 500}

# Config filter — if multiple selected, we'll filter client-side
selected_config_id = None
if len(selected_configs) == 1:
    selected_config_id = config_options.get(selected_configs[0])
    if selected_config_id is not None:
        params["config_id"] = selected_config_id

if score_min > 0:
    params["min_score"] = score_min
if score_max < 100:
    params["max_score"] = score_max
if search_text.strip():
    params["search"] = search_text.strip()

# Date filter
days_map = {"7 days": 7, "30 days": 30, "All time": None}
days = days_map.get(date_preset)
if days:
    params["days"] = days

try:
    listings = api.get("/listings", params=params)
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

# Client-side multi-config filter
if len(selected_configs) > 1:
    selected_ids = {config_options[name] for name in selected_configs if config_options.get(name)}
    listings = [l for l in listings if l.get("config_id") in selected_ids]

# Client-side price filter
if price_min > 0 or price_max > 0:
    def _in_price_range(lst):
        pps = lst.get("price_per_sqm")
        # Filter by monthly price, not per sqm
        import re
        price_str = lst.get("price", "")
        cleaned = price_str.replace(".", "").replace(",", ".")
        m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if not m:
            return True  # keep items we can't parse
        val = float(m.group(1))
        if price_min > 0 and val < price_min:
            return False
        if price_max > 0 and val > price_max:
            return False
        return True
    listings = [l for l in listings if _in_price_range(l)]

if not listings:
    st.info("No listings found. Run a search config job first, or adjust your filters.")
    st.stop()

# ── Summary metrics ──────────────────────────────────────────────────────────
scored = [l for l in listings if l.get("ai_score") is not None]
avg_score = round(sum(l["ai_score"] for l in scored) / len(scored), 1) if scored else None
prices_per_sqm = [l["price_per_sqm"] for l in listings if l.get("price_per_sqm")]
avg_pps = round(sum(prices_per_sqm) / len(prices_per_sqm), 1) if prices_per_sqm else None

m1, m2, m3, m4 = st.columns(4)
m1.metric("Listings", len(listings))
m2.metric("AI Scored", len(scored))
m3.metric("Avg Score", avg_score if avg_score is not None else "—")
m4.metric("Avg €/sqm", f"€{avg_pps:.0f}" if avg_pps else "—")

st.markdown("---")

# ── Build table ──────────────────────────────────────────────────────────────
def _relative_time(dt_str):
    if not dt_str:
        return ""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(dt_str))
        now = datetime.utcnow()
        diff = (now - dt).total_seconds()
        if diff < 3600:
            return f"{int(diff // 60)}m ago"
        if diff < 86400:
            return f"{int(diff // 3600)}h ago"
        return f"{int(diff // 86400)}d ago"
    except Exception:
        return str(dt_str)[:10]


# Sort by AI score descending (best first)
listings_sorted = sorted(listings, key=lambda l: l.get("ai_score") or -1, reverse=True)

rows = []
for l in listings_sorted:
    rows.append({
        "Title": (l.get("title") or "")[:55],
        "€/mo": l.get("price", ""),
        "€/sqm": f'{l["price_per_sqm"]:.0f}' if l.get("price_per_sqm") else "—",
        "sqm": l.get("sqm", ""),
        "Rooms": l.get("rooms", ""),
        "Area": l.get("area", ""),
        "Score": l.get("ai_score"),
        "Scraped": _relative_time(l.get("scraped_at")),
        "Notion": "✓" if l.get("notion_page_id") else "—",
    })

df = pd.DataFrame(rows)

event = st.dataframe(
    df,
    column_config={
        "Score": st.column_config.NumberColumn("Score", format="%d", width="small"),
        "€/sqm": st.column_config.TextColumn("€/sqm", width="small"),
        "Rooms": st.column_config.TextColumn("Rooms", width="small"),
        "Notion": st.column_config.TextColumn("Notion", width="small"),
    },
    use_container_width=True,
    hide_index=True,
    selection_mode="multi-row",
    on_select="rerun",
)

# ── Selection actions ────────────────────────────────────────────────────────
selected_rows = event.selection.rows if hasattr(event, "selection") else []

if len(selected_rows) > 1:
    selected_ids = [listings_sorted[i]["id"] for i in selected_rows]
    if st.button(f"Push {len(selected_ids)} listing(s) to Notion", type="primary", key="bulk_push"):
        try:
            result = api.post("/listings/notion-push", json={"listing_ids": selected_ids})
            st.success(f"Pushed {result['pushed']}, skipped {result['skipped']}.")
            if result.get("errors"):
                st.error(f"Errors: {result['errors']}")
            st.rerun()
        except Exception as e:
            st.error(f"Push failed: {e}")

# ── Inline detail panel ──────────────────────────────────────────────────────
if len(selected_rows) == 1:
    listing = listings_sorted[selected_rows[0]]

    st.markdown("---")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"### {listing.get('title', '')}")
        st.markdown(
            f"**Price:** {listing.get('price', '—')}  \n"
            f"**€/sqm:** {listing.get('price_per_sqm', '—')}  \n"
            f"**Size:** {listing.get('sqm', '—')} sqm · {listing.get('rooms', '—')} rooms  \n"
            f"**Area:** {listing.get('area', '—')}, {listing.get('city', '—')}  \n"
            f"**Config:** {listing.get('config_name', '—')}  \n"
            f"**Scraped:** {str(listing.get('scraped_at', ''))[:19]}"
        )
        st.link_button("Open listing ↗", listing.get("url", "#"))
    with d2:
        score = listing.get("ai_score")
        if score is not None:
            if score >= 70:
                color = theme.GREEN
            elif score >= 40:
                color = theme.AMBER
            else:
                color = theme.RED
            dot = theme.status_dot(color, size=12)
            st.markdown(
                f'{dot} <span style="font-family:{theme.MONO_FONT};font-size:2rem;'
                f'color:{color}">{score}</span>'
                f'<span style="color:{theme.TEXT_MUTED};font-size:1rem">/100</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(f"**AI Score:** not scored")

        verdict = listing.get("ai_verdict")
        if verdict:
            st.markdown(f"**AI Verdict:**")
            st.write(verdict)

        if listing.get("notion_page_id"):
            st.button("Already in Notion", disabled=True, key=f"already_{listing['id']}")
        else:
            if st.button("Push to Notion", key=f"push_{listing['id']}"):
                try:
                    result = api.post("/listings/notion-push", json={"listing_ids": [listing["id"]]})
                    st.success(f"Pushed {result['pushed']}, skipped {result['skipped']}.")
                    if result.get("errors"):
                        st.error(f"Errors: {result['errors']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Push failed: {e}")
```

- [ ] **Step 2: Delete old Listings page**

```bash
rm src/frontend/pages/4_Listings.py
```

- [ ] **Step 3: Commit**

```bash
git add src/frontend/pages/2_Listings.py
git rm src/frontend/pages/4_Listings.py
git commit -m "feat: redesign Listings page with horizontal filters, €/sqm column, sorted by score"
```

---

## Task 5: Rename and Theme Remaining Pages

**Files:**
- Rename: `src/frontend/pages/1_Search_Configs.py` → `src/frontend/pages/3_Search_Configs.py`
- Rename: `src/frontend/pages/3_Preferences.py` → `src/frontend/pages/4_Preferences.py`
- Modify: `src/frontend/pages/5_Site_Settings.py`
- Modify: `src/frontend/app.py`

- [ ] **Step 1: Rename Search Configs**

```bash
git mv src/frontend/pages/1_Search_Configs.py src/frontend/pages/3_Search_Configs.py
```

Then edit `src/frontend/pages/3_Search_Configs.py` — add theme import and apply after the `st.set_page_config` line. Replace:

```python
st.set_page_config(page_title="Search Configs", page_icon="⚙️", layout="wide")
st.title("⚙️ Search Configurations")
```

With:

```python
import theme

st.set_page_config(page_title="Search Configs", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Search Configs")
```

Also update the `st.switch_page` call that references the old Monitor page. Find:

```python
                        st.switch_page("pages/2_Monitor.py")
```

Replace with:

```python
                        st.switch_page("pages/1_Operations.py")
```

- [ ] **Step 2: Rename Preferences**

```bash
git mv src/frontend/pages/3_Preferences.py src/frontend/pages/4_Preferences.py
```

Edit `src/frontend/pages/4_Preferences.py` — replace:

```python
st.set_page_config(page_title="Preferences", page_icon="🧠", layout="wide")
st.title("🧠 LLM Evaluation Preferences")
```

With:

```python
import theme

st.set_page_config(page_title="Preferences", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Preferences")
```

- [ ] **Step 3: Theme Site Settings**

Edit `src/frontend/pages/5_Site_Settings.py` — replace:

```python
st.set_page_config(page_title="Site Settings", page_icon="🔧", layout="wide")
st.title("🔧 Site Settings")
```

With:

```python
import theme

st.set_page_config(page_title="Site Settings", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Site Settings")
```

- [ ] **Step 4: Update app.py to redirect to Operations**

Replace the entire content of `src/frontend/app.py` with:

```python
"""frontend.app — Streamlit multi-page app entry point. Redirects to Operations."""
import streamlit as st
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="apt_scrape",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Redirect to Operations (the real landing page)
st.switch_page("pages/1_Operations.py")
```

- [ ] **Step 5: Commit**

```bash
git add src/frontend/pages/3_Search_Configs.py src/frontend/pages/4_Preferences.py src/frontend/pages/5_Site_Settings.py src/frontend/app.py
git commit -m "feat: rename pages for new nav order, apply dark theme to all pages, redirect home to Operations"
```

---

## Task 6: Final Integration and Cleanup

**Files:**
- Verify all pages
- Clean up any stale references

- [ ] **Step 1: Verify no broken page references**

Search the codebase for any references to old page filenames:

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && grep -r "2_Monitor\|6_Stats\|4_Listings\|1_Search_Configs\|3_Preferences" src/frontend/ --include="*.py"
```

Expected: No matches (all references updated). If any found, update them.

- [ ] **Step 2: Verify page file listing**

```bash
ls -la src/frontend/pages/
```

Expected files:
- `1_Operations.py`
- `2_Listings.py`
- `3_Search_Configs.py`
- `4_Preferences.py`
- `5_Site_Settings.py`

No other `.py` files should exist.

- [ ] **Step 3: Run a full import check**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape
python -c "
import sys
sys.path.insert(0, 'src/frontend')
sys.path.insert(0, 'src')
import theme
print('theme OK')
print('Colors:', theme.BG_PRIMARY, theme.GREEN, theme.RED)
print('dot:', theme.status_dot(theme.GREEN))
print('mono:', theme.mono('€1,200'))
"
```

Expected: All imports succeed, helpers produce HTML strings.

- [ ] **Step 4: Check backend starts without errors**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && timeout 5 python -c "
import sys
sys.path.insert(0, 'src')
from backend.routers.jobs import pipeline_health, overall_stats
print('Backend endpoints importable: OK')
" 2>&1 || true
```

Expected: `Backend endpoints importable: OK`

- [ ] **Step 5: Add .superpowers/ to .gitignore if not already there**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape
grep -q ".superpowers/" .gitignore 2>/dev/null || echo ".superpowers/" >> .gitignore
```

- [ ] **Step 6: Commit final cleanup**

```bash
git add -A
git commit -m "chore: final integration cleanup, verify all pages and imports"
```
