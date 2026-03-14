# Streamlit + Docker Frontend Design

**Date:** 2026-03-14
**Status:** Draft

---

## Context

The current `apt_scrape` tool is a CLI-only script that requires manual invocation of shell scripts and Python CLI commands to scrape listings, run AI analysis, and push to Notion. There is no way to configure search parameters, manage schedules, or monitor jobs without editing shell scripts or command-line arguments.

**Goal:** Build a local-Docker-deployable system with a Streamlit frontend and a FastAPI backend that exposes all scraping and analysis capabilities through a UI — supporting scheduled scraping, per-area search configs, job monitoring, and editable LLM preferences.

---

## Architecture

### Services (docker-compose)

Two containers sharing a bind-mounted `./data/` directory:

| Service | Image | Port | Role |
|---|---|---|---|
| `backend` | `./backend` | 8000 | FastAPI + APScheduler + all scraping logic |
| `frontend` | `./frontend` | 8501 | Streamlit UI |

The `backend` container imports `apt_scrape` as a Python package via `pip install -e /workspace` where `/workspace` is the repo root mounted as a volume. No duplication of scraping code.

### Communication

Streamlit → FastAPI over HTTP (`BACKEND_URL=http://backend:8000`). All state lives in SQLite. Frontend is stateless.

### Persistence (`./data/` volume mount)

```
data/
├── app.db           # SQLite database
├── preferences.txt  # LLM scoring preferences (editable via UI)
└── results/         # JSON outputs per job (optional, for debugging)
```

---

## Directory Structure

```
apt_scrape/
├── apt_scrape/              # Existing package — UNCHANGED
├── backend/
│   ├── Dockerfile           # Python 3.12-slim + Playwright + pip install -e /workspace
│   ├── requirements.txt     # fastapi, uvicorn, apscheduler, sqlmodel, aiofiles
│   ├── main.py              # FastAPI app entry point + lifespan (scheduler start/stop)
│   ├── db.py                # SQLModel table definitions + engine setup
│   ├── scheduler.py         # APScheduler setup; job runner function
│   └── routers/
│       ├── configs.py       # CRUD for search_configs
│       ├── jobs.py          # Job status, logs, manual trigger
│       └── preferences.py   # Read/write preferences.txt
├── frontend/
│   ├── Dockerfile           # Python 3.12-slim + streamlit
│   ├── requirements.txt     # streamlit, httpx
│   ├── app.py               # Streamlit entry (sidebar nav)
│   └── pages/
│       ├── 1_Search_Configs.py
│       ├── 2_Monitor.py
│       └── 3_Preferences.py
├── docker-compose.yml
├── .env.example             # All required env vars documented
└── data/                    # Created on first run; gitignored
```

---

## SQLite Schema (SQLModel)

### `search_configs`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `name` | str | Display name (e.g. "Milano · Citta Studi") |
| `city` | str | e.g. "milano" |
| `area` | str | e.g. "citta-studi" |
| `operation` | str | "affitto" or "vendita" |
| `property_type` | str | comma-separated, e.g. "appartamenti,attici" |
| `min_price` | int | |
| `max_price` | int | |
| `min_sqm` | int | |
| `min_rooms` | int | integer (matches CLI `--min-rooms` type) |
| `start_page` | int | default 1 |
| `end_page` | int | default 10 |
| `schedule_days` | str | JSON array of day names, e.g. `["mon","wed","fri"]` |
| `schedule_time` | str | "HH:MM" 24h, e.g. "08:00" |
| `detail_concurrency` | int | default 5; passed to `enrich_with_details()` |
| `vpn_rotate_batches` | int | default 3; passed to `enrich_with_details()` |
| `auto_analyse` | bool | run AI scoring automatically |
| `auto_notion_push` | bool | push to Notion automatically after scrape |
| `enabled` | bool | schedule active or paused |
| `created_at` | datetime | |

### `jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `config_id` | int FK → search_configs | |
| `status` | str | "pending" / "running" / "done" / "failed" |
| `triggered_by` | str | "schedule" or "manual" |
| `started_at` | datetime | |
| `finished_at` | datetime | nullable |
| `listing_count` | int | nullable; set after upsert |
| `log` | text | append-only log lines (newline-separated) |

### `listings`
| Column | Type | Notes |
|---|---|---|
| `id` | int PK | |
| `url` | str UNIQUE | dedup key |
| `job_id` | int FK → jobs | last job that upserted this listing |
| `config_id` | int FK → search_configs | |
| `title` | str | |
| `price` | str | raw price string |
| `sqm` | str | raw size string |
| `rooms` | str | |
| `area` | str | |
| `city` | str | |
| `ai_score` | int | nullable; null if auto_analyse=False |
| `ai_verdict` | str | nullable |
| `notion_page_id` | str | nullable; null if auto_notion_push=False |
| `raw_json` | text | full listing dict as JSON, stored **after all mutations** (includes `notion_fields`, `ai_score`, `notion_page_id`) |
| `scraped_at` | datetime | |

---

## FastAPI Backend

### Endpoints

#### `/configs`
- `GET /configs` — list all configs
- `POST /configs` — create config
- `GET /configs/{id}` — get single config
- `PUT /configs/{id}` — update config + reload scheduler
- `DELETE /configs/{id}` — delete config + remove from scheduler
- `POST /configs/{id}/run` — trigger immediate job (returns `{"job_id": int}`)
- `PATCH /configs/{id}/toggle` — flip `enabled` bool + reload scheduler

#### `/jobs`
- `GET /jobs` — list recent jobs (optional `?config_id=` filter), returns status + listing_count
- `GET /jobs/{id}` — get job detail + full log text

#### `/preferences`
- `GET /preferences` — read `PREFERENCES_FILE` content + file mtime as `last_saved`
- `PUT /preferences` — write full text to `PREFERENCES_FILE`

### Scheduler (APScheduler)

`AsyncIOScheduler` starts in the FastAPI `lifespan` context. On startup:
1. Reads all enabled `search_configs` from DB
2. Adds a `CronTrigger` job per config (day_of_week + hour + minute derived from `schedule_days`/`schedule_time`)
3. Config writes call `scheduler.reload_config(config_id)` to add/update/remove the APScheduler job

**Job runner function (`scheduler.py: run_config_job(config_id: int)`):**

Executes in this exact order, appending log lines to `job.log` after each step:

1. Insert `job` row (status=`"running"`, triggered_by from context)
2. Build `SearchFilters` from config fields (import `apt_scrape.sites.base.SearchFilters` directly — **do not call `cli.py`**)
3. For each registered site adapter: call `adapter.build_search_url(filters)`, fetch pages with `camoufox`, call `adapter.parse_search(html)` → collect `listings: list[dict]`
4. Call `enrich_with_details(listings, concurrency=config.detail_concurrency, rotate_every_batches=config.vpn_rotate_batches)` from `apt_scrape.enrichment`
5. Stamp `_area` and `_city` on each listing dict
6. If `auto_analyse=True`: call `analyse_listings(listings, load_preferences())` from `apt_scrape.analysis` (preferences loaded from `PREFERENCES_FILE=/data/preferences.txt`)
7. If `auto_notion_push=True`: call `push_listings(listings)` from `apt_scrape.notion_push` (mutates listing dicts with `notion_page_id`)
8. Upsert all listing dicts into `listings` table: INSERT OR REPLACE by `url`; `raw_json` = full listing dict serialized to JSON **at this point** (captures all mutations from steps 5–7)
9. Update `job.listing_count`, `job.status="done"`, `job.finished_at`; on any exception set `status="failed"` and log traceback

**Concurrency between jobs:** APScheduler is configured with `max_instances=1` per job (no two instances of the same config run simultaneously). Different configs may run concurrently; the browser (Camoufox/Playwright) is instantiated fresh per job run, not shared across jobs.

### Backend Dockerfile

```dockerfile
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl && rm -rf /var/lib/apt/lists/*
WORKDIR /workspace
# Install apt_scrape package in editable mode from the mounted repo root
COPY ../requirements.txt /tmp/pkg_requirements.txt
RUN pip install --no-cache-dir -r /tmp/pkg_requirements.txt
# Install Playwright + Chromium (used by Camoufox under the hood)
RUN pip install playwright && playwright install chromium --with-deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app/backend
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

The docker-compose volume mount `.:/workspace` makes `apt_scrape` importable; the backend uses `PYTHONPATH=/workspace`.

---

## Streamlit Frontend

### Page: Search Configs (`1_Search_Configs.py`)

- On load: `GET /configs` → display list; each row shows name, area, schedule summary, enabled toggle, AI badge, Notion badge
- "▶ Run now" button → `POST /configs/{id}/run` → `st.switch_page("2_Monitor.py")`
- "+ New Config" button → expander with form fields:
  - Basic: name (text), city (text), area (text), operation (selectbox: affitto/vendita), property type (text, comma-separated)
  - Filters: price range (`st.slider`), sqm min (int), rooms min (int selectbox: 1–5)
  - Pagination: start page, end page (int inputs)
  - Schedule: days multiselect (Mon–Sun), time (`st.time_input`)
  - Rate limits: detail concurrency slider (1–10), VPN rotate batches slider (1–10)
  - Toggles: AI analysis (`st.toggle`), Notion push (selectbox: off / auto)
  - Enable/disable toggle
  - Save → `POST /configs` or `PUT /configs/{id}`
- Click existing config row → same form pre-filled; Delete button → `DELETE /configs/{id}`

### Page: Monitor (`2_Monitor.py`)

- Auto-refreshes every 5s via `st.rerun()` controlled by `time.sleep(5)` in a fragment
- `GET /jobs` on each refresh → show running jobs at top with status badge and truncated log tail
- Recent jobs table: config name, status badge, listing count, duration, started_at timestamp
- Click job row → expander with full `job.log` text (via `GET /jobs/{id}`)
- **Log delivery:** polling only (MVP). The Monitor page fetches `GET /jobs/{id}` every 5s and displays `job.log` as a `st.code` block. No SSE required.

### Page: Preferences (`3_Preferences.py`)

- `GET /preferences` on load → populates `st.text_area` (height=400, monospace via CSS hack)
- Displays `last_saved` timestamp from response
- "Save Preferences" button → `PUT /preferences` with text area content → success toast
- Helper text: "This text is passed to the LLM to score listings 0–100. Changes take effect on the next job run."

---

## Docker Compose

```yaml
services:
  backend:
    build:
      context: .
      dockerfile: backend/Dockerfile
    volumes:
      - .:/workspace          # makes apt_scrape importable via PYTHONPATH
      - ./data:/data          # SQLite + preferences.txt
    environment:
      - PYTHONPATH=/workspace
      - DB_PATH=/data/app.db
      - PREFERENCES_FILE=/data/preferences.txt
    env_file: .env
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

### Environment Variables (`.env`)
```
# LLM / Analysis
OPENROUTER_API_KEY=
OPENROUTER_MODEL=google/gemini-2.0-flash-lite

# Notion
NOTION_API_KEY=
NOTION_APARTMENTS_DB_ID=
NOTION_AREAS_DB_ID=
NOTION_AGENCIES_DB_ID=
```

---

## Key Design Decisions

1. **Existing `apt_scrape` package is untouched.** The backend imports it directly via editable install from the mounted repo root.
2. **Scheduler bypasses `cli.py` entirely.** The job runner calls scraping primitives directly (`SearchFilters`, site adapters, `enrich_with_details`, `analyse_listings`, `push_listings`) — avoids `cli.py`'s browser lifecycle management and `click.echo` side effects.
3. **Strict pipeline ordering.** Each job runs: scrape → enrich → analyse → push → upsert. The `listings` table row is written only after all mutations, so `raw_json` always contains the final state.
4. **Preferences editable in UI.** `PUT /preferences` writes directly to `/data/preferences.txt`. The scheduler calls `load_preferences()` from `apt_scrape.analysis` on each job run, so edits take effect immediately on the next run.
5. **Per-config rate limits.** Each config carries `detail_concurrency` and `vpn_rotate_batches`, passed directly to `enrich_with_details()`.
6. **Notion push is per-config.** `auto_notion_push=True` means it runs automatically; `False` means it never runs from the scheduler (no manual push from UI in MVP).
7. **Log delivery is polling.** Monitor page polls `GET /jobs/{id}` every 5s. No SSE endpoint needed for MVP.
8. **Browser isolation per job.** Camoufox browser instances are created fresh per job run (`max_instances=1` per APScheduler job) to avoid shared state issues when multiple configs run concurrently.

---

## Verification

1. `docker compose up --build` — both services start without errors
2. `http://localhost:8501` loads Streamlit with 3 sidebar pages
3. Create a search config → `GET /configs` returns it; row appears in DB
4. Click "Run now" → Monitor page shows job status "running" then "done"; listings appear in `listings` table with non-null `raw_json`
5. If `auto_analyse=True`: listings in DB have non-null `ai_score`
6. If `auto_notion_push=True`: listings in DB have non-null `notion_page_id`
7. Preferences page: edit text → Save → `GET /preferences` returns new content; `data/preferences.txt` on host updated
8. Enable a scheduled config, set trigger time +2min → verify job fires at scheduled time
9. `docker compose down && docker compose up` → configs, jobs, listings all persist from volume
