# Architecture

**Analysis Date:** 2026-03-16

## Pattern Overview

**Overall:** Three-tier architecture with modular site adapters

**Key Characteristics:**
- Plugin-based site adapter system (config-driven when possible, Python overrides when needed)
- Async Python backend (FastAPI) managing scraping jobs, scheduling, and data persistence
- Streamlit dashboard frontend for configuration and monitoring
- Singleton browser manager with optional proxy rotation and rate limiting
- Data enrichment pipeline: scrape → enrich details → post dates → analyze → push to external services

## Layers

**Presentation Layer (Streamlit):**
- Purpose: Multi-page interactive dashboard for managing scrapes, viewing results, editing preferences
- Location: `frontend/`
- Contains: Page components (`frontend/pages/`), HTTP client (`frontend/api.py`), Streamlit app entry (`frontend/app.py`)
- Depends on: Backend FastAPI server (via HTTP)
- Used by: End users, orchestrated by Streamlit server

**API Layer (FastAPI):**
- Purpose: REST endpoints for config management, job control, listing queries, Notion push, statistics
- Location: `backend/main.py`, `backend/routers/`
- Contains: Route handlers (configs, jobs, listings, preferences, sites), scheduler setup, database initialization
- Depends on: Database (SQLModel/SQLite), scraping runner, job scheduler
- Used by: Streamlit frontend, CLI, MCP server

**Business Logic Layer (Scraping & Enrichment):**
- Purpose: Core scraping pipeline, data enrichment, analysis, and external integrations
- Location: `apt_scrape/`
- Contains: Site adapters, browser manager, enrichment logic, notion sync, AI analysis, export utilities
- Depends on: Browser (Camoufox), site-specific selectors, LLM APIs, Notion API
- Used by: Backend runner, CLI, MCP server

**Data Access Layer:**
- Purpose: Database abstraction and ORM
- Location: `backend/db.py`
- Contains: SQLModel table definitions (SearchConfig, Job, Listing, SiteConfigOverride), engine setup, migration helpers
- Depends on: SQLite database (configurable path via `DB_PATH` env var)
- Used by: All backend routers, job runner, statistics generation

## Data Flow

**Search Job Execution:**

1. User creates SearchConfig (via dashboard or API) with filters, schedule, site_id
2. APScheduler triggers job at scheduled time or user clicks manual run
3. `backend/runner.py:run_config_job()` creates Job record and orchestrates pipeline
4. Job retrieves SearchConfig + site-specific overrides from database
5. Site adapter builds URL from filters using selectors from config (YAML) or overrides
6. BrowserManager.fetch_page() fetches search results page via Camoufox (with optional proxy rotation and rate limiting)
7. Site adapter parses HTML, extracts listing summaries (title, price, area, url)
8. Optional detail enrichment: for each listing, fetch detail page and parse rich fields (description, features, energy class)
9. Optional post-date enrichment: query each listing's timestamp via secondary request
10. AI analysis (if auto_analyse=true): LangGraph evaluates each listing against preferences.txt, scores 1-10
11. Optional Notion push (if auto_notion_push=true): push_listings() deduplicates and uploads to Notion
12. Job record finalized with stats (listing_count, ai_tokens_used, ai_cost_usd) and marked "done"

**State Management:**

- Config state: SearchConfig table (name, filters, schedule, per-site overrides)
- Job state: Job table (status: pending/running/done/failed, logs, statistics)
- Listing state: Listing table (scraped listings with parsed fields, AI scores, Notion page IDs)
- Browser state: Singleton BrowserManager instance managed by FastAPI lifespan (startup/shutdown)
- Proxy rotation state: In-memory _proxy_index and _requests_since_rotation in BrowserManager
- Scheduler state: APScheduler CronTrigger per SearchConfig (enabled/disabled via config)

## Key Abstractions

**SiteAdapter:**
- Purpose: Encapsulate site-specific parsing logic and configuration
- Examples: `apt_scrape/sites/immobiliare.py`, `apt_scrape/sites/casa.py`, `apt_scrape/sites/idealista.py`
- Pattern: Subclass `SiteAdapter` (base in `apt_scrape/sites/base.py`), override methods to customize parsing, or keep config-driven defaults

**SearchFilters:**
- Purpose: Normalized filter parameters across all sites
- Examples: city, area, operation (affitto/vendita), property_type, price range, sqm, rooms, publication recency
- Pattern: Always use SearchFilters dataclass to abstract away site-specific query parameter naming

**BrowserManager:**
- Purpose: Lifecycle and request management for Camoufox stealth browser
- Location: `apt_scrape/server.py`
- Pattern: Singleton instance created on startup, closed on shutdown; handles proxy rotation, rate limiting, block detection

**Enrichment Pipeline:**
- Purpose: Stateless functions that add richer data to listing dicts
- Location: `apt_scrape/enrichment.py`
- Pattern: `enrich_with_details()` (fetch detail pages in parallel batches) and `enrich_post_dates()` (query timestamps)

## Entry Points

**FastAPI Backend:**
- Location: `backend/main.py`
- Triggers: Launched via `apt start` (CLI) or `docker compose up` or direct `uvicorn backend.main:app`
- Responsibilities: Serve REST API, initialize database, start scheduler, manage browser lifecycle

**Streamlit Frontend:**
- Location: `frontend/app.py`
- Triggers: Launched via `apt start` or `streamlit run frontend/app.py`
- Responsibilities: Render dashboard, call backend API, manage multi-page navigation

**CLI:**
- Location: `apt_scrape/cli.py`
- Triggers: Invoked via `python -m apt_scrape.cli [command]` or `apt [command]`
- Responsibilities: One-off searches, detail fetches, site listing, HTML dumps

**MCP Server:**
- Location: `apt_scrape/server.py` (FastMCP-based tools)
- Triggers: Launched by Claude Desktop or MCP client
- Responsibilities: Expose search, detail, and listing operations as standardized MCP tools

**Job Runner (Background Task):**
- Location: `backend/runner.py:run_config_job()`
- Triggers: Called by scheduler (async task) or by /jobs POST endpoint
- Responsibilities: Execute full scraping pipeline and persist results

## Error Handling

**Strategy:** Three-tier error handling with fallback and logging

**Patterns:**

1. **Browser Errors (BrowserManager):** Detect blocks (DataDome, bot-challenge pages, short HTML); rotate proxy or wait before retry
2. **Parsing Errors (SiteAdapter):** Return None/empty for missing fields; log parse failures but continue processing batch
3. **Detail/Enrichment Errors:** Collect per-URL errors in a list; enrich_with_details() continues on individual listing failures and returns error tuples
4. **Job Errors:** Catch in run_config_job(), log to Job.log, set Job.status = "failed"; caller logs exception to stderr
5. **API Errors (FastAPI):** HTTPException with status codes (400 bad request, 503 unavailable for missing credentials, 404 not found)

## Cross-Cutting Concerns

**Logging:**
- Backend: Python logging to stderr (DEBUG/INFO/WARNING/ERROR levels)
- CLI/Server: Logs go to stderr while stdout is reserved for JSON output or MCP transport
- Frontend: Uses Streamlit's streamlit.write() for debugging, no persistent logs
- Job logs: Buffered in memory and periodically flushed to Job.log database field

**Validation:**
- Input: FastAPI request models (Pydantic) validate incoming JSON (query params, request bodies)
- Database: SQLModel ensures type safety on table inserts
- Site configs: YAML validation via load_config_from_yaml() (basic schema checking)

**Authentication:**
- Frontend: No built-in auth; assumes trusted local deployment or reverse proxy with auth
- API: No auth; assumes same
- External APIs: Credentials via env vars (NOTION_API_KEY, OPENROUTER_API_KEY, NORDVPN_USER/PASS)

**Rate Limiting:**
- Browser-level: REQUEST_DELAY_SECONDS (default 2.0) enforced globally via BrowserManager._rate_limit()
- Per-config: request_delay_sec, page_delay_sec configurable per SearchConfig
- Proxy rotation: Rotate every PROXY_ROTATE_EVERY requests (default 15) or on block detection
- VPN: Pause 60 seconds after exhausting all proxies before cycling again

---

*Architecture analysis: 2026-03-16*
