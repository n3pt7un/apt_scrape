# Dashboard UX Overhaul — Design Spec

**Date:** 2026-04-12
**Approach:** Streamlit Power User — full custom CSS, merged Operations page, Listings redesign, Plotly charts

## Goals

1. Surface operational health issues (silent degradation, schedule drift, failures) at a glance
2. Make the Listings table less clunky with better columns, smart defaults, and inline detail
3. Apply a Palantir-style dark theme across the entire app
4. Reduce page count and remove unnecessary navigation hops

## Usage Pattern

Quick daily health checks (5-second scan) most days, occasional deep dives into listings and market data.

---

## 1. Palantir Dark Theme System

Global CSS injection via `st.markdown(unsafe_allow_html=True)` loaded from a shared `theme.py` module. Every page imports it.

### Color Palette

| Role | Value |
|------|-------|
| Background | `#0a0a0a` |
| Card/surface | `#111111` |
| Elevated element | `#1a1a1a` |
| Border subtle | `#2a2a2a` |
| Border emphasis | `#333333` |
| Text primary | `#e0e0e0` |
| Text secondary | `#888888` |
| Text muted | `#555555` |
| Accent green | `#00d97e` (healthy, success, good scores) |
| Accent amber | `#f7c948` (warnings, degradation) |
| Accent red | `#e63757` (failures, errors, critical) |
| Accent blue | `#0061ff` (informational, links, neutral) |
| Accent cyan | `#00b8d9` (chart accents, secondary data) |

### Typography

- UI text: system sans-serif (`-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`)
- Data values, prices, timestamps, IDs: monospace (`'JetBrains Mono', 'SF Mono', 'Fira Code', monospace`)

### Component Overrides

- **`st.metric`** — dark card with glowing accent color for deltas
- **`st.dataframe`** — dark rows, subtle row hover highlight, header in muted uppercase
- **`st.selectbox`, `st.text_input`** — dark inputs with subtle borders
- **Sidebar** — `#0d0d0d` background, muted nav links, active page gets left border accent bar in blue
- **`st.button`** — outlined by default, filled for primary actions
- **`st.expander`** — dark surface, subtle border

### Status Indicators

Consistent across all pages: small CSS-rendered colored dots (not emoji) using `::before` pseudo-elements. Green / amber / red / grey.

### Implementation

A single `src/frontend/theme.py` module exporting:
- `apply_theme()` — injects the full CSS block, called at the top of every page
- Color constants for use in Plotly chart configs
- Helper functions: `status_dot(color)`, `mono(value)` — return styled HTML fragments

---

## 2. Operations Page (Merged Monitor + Stats)

Replaces both the current Monitor page (`2_Monitor.py`) and Stats page (`6_Stats.py`). Becomes the landing/default page.

### Zone 1: Health Strip (~80px, always visible)

A single row of 4-5 indicator cards, each showing: status dot + label + value.

| Indicator | Green | Amber | Red |
|-----------|-------|-------|-----|
| Pipeline Status | Last job succeeded | >6h since last run | Last job failed |
| Schedule Health | All enabled configs ran on time | Any missed by >1h | Any missed by >6h |
| Yield Trend | 7-day avg unique/run stable or rising | Dropping >20% vs prior 7d | Dropping >50% |
| Dupe Rate | <30% | 30-60% | >60% |
| AI Cost (7d) | Normal | >2x prior 7-day period | — |

Each card is clickable/expandable for detail.

### Zone 2: Trend Charts (two-column Plotly layout)

**Left column:**
- **Listings over time** — stacked area chart: unique vs dupes per run, x-axis = date. Shows yield degradation.
- **Success rate timeline** — line chart: % of jobs completing successfully, rolling 7-day window.

**Right column:**
- **Price per sqm by area** — grouped bar chart. Market intelligence view.
- **Run duration trend** — line chart showing if jobs take longer over time (early warning for site blocking).

All charts: dark background (`#111111`), grid lines `#1a1a1a`, data in accent colors. Plotly dark template customized to match palette.

### Zone 3: Recent Activity Feed

Compact table replacing the current Monitor's "Recent Jobs" section.

| Column | Content |
|--------|---------|
| Status dot | Green / red / amber |
| Config name | Which search ran (links to Search Configs page) |
| Time | Relative + absolute ("2h ago · 14:30") |
| Yield | "43 found, 31 unique, 12 dupes" |
| Duration | "2m 34s" — amber highlight if >2x historical average |
| AI cost | "$0.03" |
| Expand | Full log, area breakdown, error details if failed |

Active jobs appear at the top with a pulsing status dot and live log tail via `st.empty()` + polling.

---

## 3. Listings Page Redesign

### Smart Defaults

Page loads showing last 7 days of listings, sorted by AI score descending. Best listings first.

### Column Layout

| Column | Format | Notes |
|--------|--------|-------|
| Status dot | Colored by AI score tier | Instant visual scan |
| Title | Truncated, full on hover | Primary identifier |
| €/mo | Monospace, right-aligned | Price |
| €/sqm | Calculated, monospace, right-aligned | Key comparison metric (new) |
| sqm | Monospace | Size |
| Rooms | Monospace | Quick filter |
| Area | Text | Location |
| AI Score | Colored number | Sortable |
| Scraped | Relative time ("2h ago") | Freshness |
| Notion | Small icon: ✓ pushed / — not | Export tracking |

**Removed from default view:** City (redundant within a search), Config name (in filters), full URL (in detail panel).

### Filter Bar

Horizontal strip above the table (not in sidebar):
- Config dropdown (multi-select)
- Score range slider (0-100)
- Price range min/max inputs
- Area multi-select
- Date range picker (presets: 7d / 30d / all)
- Title search text input

### Detail Panel

Clicking a row opens an inline expander or right-column panel:
- Full title + direct link to listing URL
- All data fields: price, sqm, rooms, area, city, €/sqm
- AI score with full verdict text
- Config name + scrape timestamp
- Notion push button (if not already pushed)
- "Open listing" external link button

No page navigation — detail is inline.

---

## 4. Navigation & Page Structure

### Page Changes

| Page | Change |
|------|--------|
| Home | **Removed** — unnecessary navigation hop |
| Monitor + Stats | **Merged** into Operations (new page 1) |
| Operations | New landing page / default |
| Listings | Redesigned per Section 3 |
| Search Configs | Unchanged functionally, gets dark theme |
| Preferences | Unchanged functionally, gets dark theme |
| Site Settings | Unchanged functionally, gets dark theme |

**5 pages** (down from 7).

### Sidebar

- Dark background (`#0d0d0d`)
- Active page: left border accent bar in blue (`#0061ff`), white text
- Inactive pages: muted grey (`#888888`)
- Pipeline health dot next to "Operations" label — visible from any page
- No emoji in page titles — clean text labels

### Cross-page Links

- Listings → clicking config name opens Search Configs filtered to that config
- Operations → clicking job config name links to Search Configs, clicking listing count links to Listings filtered to that job
- Implemented via `st.page_link()` with query params

---

## 5. Backend Changes

### New Endpoint: `GET /jobs/health`

Computes health indicators server-side. Frontend maps status strings to colors.

```json
{
  "pipeline_status": "healthy | warning | critical",
  "last_job_status": "done | failed",
  "last_job_ago_sec": 3600,
  "schedule_health": "healthy | warning | critical",
  "missed_schedules": [],
  "yield_trend": "stable | declining | critical",
  "yield_7d_avg": 28.5,
  "yield_prev_7d_avg": 31.2,
  "dupe_rate_7d": 0.34,
  "dupe_rate_trend": "rising | stable | falling",
  "ai_cost_7d": 0.42,
  "ai_cost_prev_7d": 0.38
}
```

Health logic:
- **Pipeline status:** Compare `last_job.status` and `now - last_job.finished_at`
- **Schedule health:** For each enabled config with a schedule, check if a job ran within the expected window (schedule_time ± 1h for amber, ± 6h for red)
- **Yield trend:** Compare average `listing_count` over last 7 days vs prior 7 days
- **Dupe rate:** `sum(dupes_removed) / sum(scraped_count)` over last 7 days
- **AI cost:** Sum `ai_cost_usd` over last 7 days vs prior 7 days

### Extended: `GET /jobs/stats`

Add to existing response:

- `timeline`: array of per-job objects with `config_name`, `started_at`, `duration_sec`, `scraped_count`, `listing_count`, `dupes_removed`, `ai_cost_usd`, `avg_price_eur`, `avg_price_per_sqm`, `area_stats`, `status`
- `price_per_sqm_by_area`: dict mapping area slug to average €/sqm

### Extended: Listing Response

Add computed `price_per_sqm` field. Parse existing string `price` and `sqm` fields server-side, compute ratio, return as float (nullable if parsing fails).

### No Database Migrations

All health indicators computed from existing `Job` and `Listing` tables. No new tables or columns needed.

---

## Out of Scope

- Auto-refresh / WebSocket live updates (Streamlit polling with `st.empty()` is sufficient)
- Framework migration (staying in Streamlit)
- Changes to scraping logic, AI scoring, or Notion integration
- Changes to Search Configs, Preferences, or Site Settings page functionality
