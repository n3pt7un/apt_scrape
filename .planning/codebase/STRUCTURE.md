# Codebase Structure

**Analysis Date:** 2026-03-16

## Directory Layout

```
apt_scrape/
├── apt_scrape/                    # Core scraping engine (Python package)
│   ├── sites/                     # Site-specific adapters (plugin registry)
│   │   ├── base.py                # Abstract SiteAdapter base class
│   │   ├── immobiliare.py         # Immobiliare.it scraper
│   │   ├── casa.py                # Casa.it scraper
│   │   ├── idealista.py           # Idealista.it scraper
│   │   ├── configs/               # YAML config files (selectors, URL patterns)
│   │   └── __init__.py            # Adapter registry
│   ├── analysis.py                # AI scoring via LangGraph + OpenRouter
│   ├── enrichment.py              # Detail-page and post-date enrichment
│   ├── notion_push.py             # Notion API integration (deduplication, upload)
│   ├── export.py                  # CSV and markdown export utilities
│   ├── cli.py                     # Command-line interface
│   ├── server.py                  # MCP server + BrowserManager (Camoufox)
│   └── __init__.py                # Package version
├── backend/                       # REST API backend (FastAPI + APScheduler)
│   ├── main.py                    # FastAPI app entry point
│   ├── db.py                      # SQLModel table definitions + engine setup
│   ├── runner.py                  # Job execution pipeline orchestrator
│   ├── scheduler.py               # APScheduler cron job setup
│   ├── routers/                   # FastAPI route handlers
│   │   ├── configs.py             # /configs — create, list, update, delete SearchConfig
│   │   ├── jobs.py                # /jobs — list, get status, overall stats
│   │   ├── listings.py            # /listings — query, filter, Notion push
│   │   ├── preferences.py         # /preferences — get/update preferences.txt
│   │   ├── sites.py               # /sites — list adapters, get areas per site
│   │   └── __init__.py            # Router imports
│   ├── requirements.txt           # Backend dependencies (fastapi, sqlmodel, etc.)
│   ├── Dockerfile                 # Docker image for backend
│   └── __init__.py                # Package marker
├── frontend/                      # Streamlit dashboard (pages + API client)
│   ├── app.py                     # Main page (hero + navigation)
│   ├── api.py                     # HTTP client for backend
│   ├── pages/                     # Multi-page dashboard
│   │   ├── 1_Search_Configs.py    # Create/edit SearchConfigs
│   │   ├── 2_Monitor.py           # Job monitor and logs
│   │   ├── 3_Preferences.py       # Edit preferences.txt
│   │   ├── 4_Listings.py          # Browse listings, filter, push to Notion
│   │   ├── 5_Site_Settings.py     # View/edit per-site config overrides
│   │   └── 6_Stats.py             # Aggregated statistics and charts
│   ├── requirements.txt           # Frontend dependencies (streamlit, httpx)
│   ├── Dockerfile                 # Docker image for frontend
│   └── __init__.py
├── tests/                         # Test suite
│   ├── backend/                   # Backend tests
│   └── __pycache__
├── config/                        # Static configuration files
│   ├── default_areas_immobiliare.txt
│   ├── default_areas_casa.txt
│   ├── default_areas_idealista.txt
│   └── default_areas.txt
├── data/                          # Data directory (created at runtime)
│   └── app.db                     # SQLite database (created on first run)
├── templates/                     # Developer templates
│   └── new_site_adapter.py        # Template for adding new site
├── scripts/                       # Utility scripts
│   └── process_listings.py        # Post-processing script
├── results/                       # Output directories (created by scraping)
│   ├── archive/
│   ├── latest/
│   └── review_delete/
├── docker-compose.yml             # Docker Compose config (backend + frontend)
├── requirements.txt               # Root dependencies (common packages)
├── README.md                      # Project documentation
├── .env.example                   # Example environment variables
├── .env                           # Local env config (DO NOT COMMIT)
├── pytest.ini                     # Pytest configuration
└── apt                            # Shell script entry point (chmod +x)
```

## Directory Purposes

**`apt_scrape/`:**
- Purpose: Core scraping engine package (reusable, no web framework)
- Contains: Site adapters, browser manager, enrichment, analysis, CLI, MCP server
- Key files: `server.py` (MCP + browser), `sites/__init__.py` (adapter registry), `cli.py` (CLI entry)

**`apt_scrape/sites/`:**
- Purpose: Plugin system for site-specific scraping logic
- Contains: Adapter classes (immobiliare, casa, idealista) + YAML configs
- Key files: `base.py` (abstract base), `__init__.py` (registry)

**`backend/`:**
- Purpose: FastAPI web service for job scheduling, data persistence, statistics
- Contains: REST routers, database ORM, job runner, APScheduler integration
- Key files: `main.py` (app entry), `db.py` (SQLModel tables), `runner.py` (pipeline), `scheduler.py` (cron setup)

**`backend/routers/`:**
- Purpose: Organize REST endpoints by domain (configs, jobs, listings, etc.)
- Contains: FastAPI APIRouter handlers for each domain
- Pattern: Each file defines one router, imported and registered in `main.py`

**`frontend/`:**
- Purpose: Streamlit dashboard for configuration, monitoring, and manual Notion pushes
- Contains: Multi-page app structure, HTTP client, page components
- Key files: `app.py` (home page), `api.py` (backend client), `pages/` (feature pages)

**`frontend/pages/`:**
- Purpose: Individual feature pages of the Streamlit dashboard
- Pattern: Numbered files (1_*, 2_*, etc.) for sidebar ordering; each page calls backend API via `api.py`

**`tests/`:**
- Purpose: Test suite for backend logic and database operations
- Contains: Test modules (pytest)
- Pattern: Mirror directory structure of code (tests/backend/ mirrors backend/)

**`config/`:**
- Purpose: Static configuration files (default areas per site)
- Pattern: Text files listing default area slugs per site; loaded by API when user hasn't customized

**`data/`:**
- Purpose: Runtime data directory
- Contains: `app.db` (SQLite database, created on first run)
- Pattern: Mounted as volume in Docker; location configurable via `DB_PATH` env var

**`scripts/`:**
- Purpose: One-off utility scripts
- Contains: Post-processing, data migration, bulk operations
- Key files: `process_listings.py`

**`results/`:**
- Purpose: Output directory for exported/archived scraping results
- Contains: Subdirectories for archive, latest runs, listings for review/deletion

## Key File Locations

**Entry Points:**

- `backend/main.py`: FastAPI application — server startup, router registration, database init, scheduler start
- `frontend/app.py`: Streamlit home page — hero section, navigation to feature pages
- `apt_scrape/cli.py`: Command-line interface — search, detail, sites, dump commands
- `apt_scrape/server.py`: MCP server + BrowserManager singleton — tools exposed to MCP clients

**Configuration:**

- `.env`: Environment variables (secrets, API keys, DB path) — **NEVER COMMIT**
- `.env.example`: Template with all required/optional variables
- `apt_scrape/sites/configs/*.yaml`: Per-site selector definitions and URL patterns
- `config/default_areas_*.txt`: Default area slugs per site

**Core Logic:**

- `backend/db.py`: SQLModel table definitions (SearchConfig, Job, Listing, SiteConfigOverride)
- `backend/runner.py`: Scraping job pipeline orchestration (scrape → enrich → analyze → push)
- `apt_scrape/sites/base.py`: Abstract SiteAdapter base class and shared types
- `apt_scrape/enrichment.py`: Detail page and post-date enrichment functions
- `apt_scrape/analysis.py`: AI scoring integration (LangGraph + OpenRouter)
- `apt_scrape/notion_push.py`: Notion API integration with deduplication

**Testing:**

- `pytest.ini`: Pytest configuration (test discovery, logging)
- `tests/backend/`: Backend unit tests (database, routers, runner)

## Naming Conventions

**Files:**

- Python modules: snake_case (e.g., `search_configs.py`, `notion_push.py`)
- Frontend pages: Numbered prefix + title (e.g., `1_Search_Configs.py`, `2_Monitor.py`)
- YAML configs: site_id + ".yaml" (e.g., `immobiliare.yaml`)
- Text files: lowercase with underscores (e.g., `default_areas_immobiliare.txt`)

**Directories:**

- Package directories: lowercase with underscores (e.g., `apt_scrape`, `backend`, `frontend`)
- Feature/domain directories: lowercase with underscores (e.g., `routers`, `pages`, `sites`)

**Python Naming:**

- Classes: PascalCase (e.g., `SiteAdapter`, `BrowserManager`, `SearchConfig`)
- Functions: snake_case (e.g., `run_config_job()`, `enrich_with_details()`)
- Constants: UPPER_CASE (e.g., `REQUEST_DELAY_SECONDS`, `MAX_PAGES_LIMIT`)
- Private functions/attributes: Leading underscore (e.g., `_normalize_slug()`, `_browser`)

## Where to Add New Code

**New Site Adapter:**
- File: `apt_scrape/sites/your_site.py`
- Steps:
  1. Copy `templates/new_site_adapter.py` as template
  2. Define `SiteConfig` (or load YAML via `load_config_from_yaml()`)
  3. Subclass `SiteAdapter` from `apt_scrape/sites/base.py`
  4. Override `parse_search()` and `parse_detail()` as needed
  5. Register in `apt_scrape/sites/__init__.py` (add to `ADAPTERS` list)
  6. Create YAML config in `apt_scrape/sites/configs/your_site.yaml`

**New Dashboard Page:**
- File: `frontend/pages/{N}_{Feature_Name}.py`
- Steps:
  1. Copy existing page (e.g., `1_Search_Configs.py`) as template
  2. Call backend API via `api.py` functions (get, post, put, patch, delete)
  3. Use Streamlit components (st.title, st.columns, st.button, st.table, etc.)
  4. Number affects sidebar ordering (lower = higher in sidebar)

**New Backend Endpoint:**
- File: `backend/routers/your_domain.py`
- Steps:
  1. Import `APIRouter` from fastapi
  2. Create router: `router = APIRouter()`
  3. Define handlers with `@router.get()`, `@router.post()`, etc.
  4. Import and register in `backend/main.py`: `app.include_router(your_domain.router, prefix="/your-domain")`

**New Database Table:**
- File: `backend/db.py`
- Steps:
  1. Define SQLModel class inheriting from SQLModel with `table=True`
  2. Define fields with `Field()` for constraints, defaults, foreign keys
  3. Run migrations (optional): Add function in `backend/db.py` like `_migrate_*()` pattern if altering existing tables
  4. Call `create_db_and_tables()` on app startup (already done in `backend/main.py` lifespan)

**New Enrichment Function:**
- File: `apt_scrape/enrichment.py`
- Steps:
  1. Define async function accepting `listings` list and `browser: BrowserManager`
  2. Process in parallel batches with `asyncio.gather()`
  3. Modify listing dicts in-place or return new data
  4. Return tuple of `(processed_count, error_list)`
  5. Call from `backend/runner.py:run_config_job()` in pipeline

**Utility Functions:**
- File: `apt_scrape/export.py` (for export functions), new module as needed
- Pattern: No side effects, return serializable data (dicts, strings, lists)

## Special Directories

**`.planning/codebase/`:**
- Purpose: Architecture and planning documentation
- Generated: Manually maintained (GSD mapper writes here)
- Committed: Yes

**`.logs/`:**
- Purpose: Runtime logs from background services
- Generated: Yes (by backend/frontend at runtime)
- Committed: No

**`.pids/`:**
- Purpose: Process IDs for running services
- Generated: Yes (by apt start script)
- Committed: No

**`results/`:**
- Purpose: Exported scraping results and archives
- Generated: Yes (by scripts/process_listings.py and manual exports)
- Committed: No (data directory)

**`data/`:**
- Purpose: SQLite database and runtime data
- Generated: Yes (created on first app run)
- Committed: No

**`.venv/`:**
- Purpose: Python virtual environment
- Generated: Yes (created by `python -m venv .venv`)
- Committed: No

---

*Structure analysis: 2026-03-16*
