# External Integrations

**Analysis Date:** 2026-03-16

## APIs & External Services

**Real Estate Listing Sites:**
- Immobiliare.it - Italian property portal, parsed via site adapter in `apt_scrape/sites/immobiliare.py`
  - SDK/Client: BeautifulSoup4 (HTML parsing)
  - Auth: None (public scraping)
- Casa.it - Italian property portal, parsed via `apt_scrape/sites/casa.py`
  - SDK/Client: BeautifulSoup4
  - Auth: None
- Idealista.it - Italian property portal, parsed via `apt_scrape/sites/idealista.py`
  - SDK/Client: BeautifulSoup4
  - Auth: None

**LLM / AI Analysis:**
- OpenRouter - LLM service provider for structured apartment analysis
  - SDK/Client: `langchain-openai` via `apt_scrape/analysis.py`
  - Auth: `OPENROUTER_API_KEY` (env var)
  - Model: Configurable via `OPENROUTER_MODEL` (default: `google/gemini-2.0-flash-lite`)
  - Purpose: Scores each listing 0–100 against preferences using LangGraph agent

**Notion:**
- Notion Apartments Database - Push scraped listings with relational links
  - SDK/Client: `notion-client==2.2.1`
  - Auth: `NOTION_API_KEY` (env var)
  - Database IDs:
    - `NOTION_APARTMENTS_DB_ID` - Main listings database
    - `NOTION_AREAS_DB_ID` - Area/neighborhood lookup
    - `NOTION_AGENCIES_DB_ID` - Agency/landlord lookup
  - Purpose: Duplicate deduplication, geocoding via Nominatim, property enrichment. Location: `apt_scrape/notion_push.py`

**Geolocation:**
- Nominatim (OpenStreetMap) - Free geocoding service
  - SDK/Client: `httpx` (raw HTTP requests in `apt_scrape/notion_push.py`)
  - Auth: None (public API, rate-limited)
  - Purpose: Converts addresses to lat/lon for Notion "Place" property (map view)

## Data Storage

**Databases:**
- SQLite3 (via sqlalchemy)
  - Connection: File-based at `DB_PATH` env var (default: `data/app.db`)
  - Client: SQLModel 0.0.21 (Pydantic + SQLAlchemy ORM)
  - Tables defined in `backend/db.py`: SearchConfig, Job, Listing, Site
  - Storage: Mounted volume in Docker (`/data:/data`)

**File Storage:**
- Local filesystem only
  - Preferences file: `data/preferences.txt` (plain text for AI scoring)
  - Results directory: `results/` (scraped data dumps)
  - Logs: `.logs/` (job run logs)
  - PIDs: `.pids/` (process tracking)

**Caching:**
- None configured in application layer
- SQLite journal mode optimized for mounted FUSE filesystems (PRAGMA journal_mode=MEMORY)

## Authentication & Identity

**Auth Provider:**
- None required - application is single-user
- MCP server authentication: Implied Claude Desktop session (no explicit token)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, DataDog, or similar)
- Errors logged to stderr and captured in `.logs/` directory
- Job status tracked in `Job` table (`backend/db.py`): pending, running, completed, failed

**Logs:**
- Standard Python logging (configured in `apt_scrape/server.py` at INFO level to stderr)
- Backend: uvicorn logs to stdout
- Frontend: Streamlit logs to stdout
- Job execution logs: Stored in `Job.logs` field in database for dashboard replay

## CI/CD & Deployment

**Hosting:**
- Local/self-hosted (Docker Compose recommended)
- Docker Hub images: Python 3.12-slim
- No cloud deployment configuration detected

**CI Pipeline:**
- None detected (no GitHub Actions, GitLab CI, or similar)
- Manual testing via pytest-asyncio

## Environment Configuration

**Required env vars:**
- `OPENROUTER_API_KEY` - For LLM scoring (optional)
- `OPENROUTER_MODEL` - LLM model slug (optional, default: google/gemini-2.0-flash-lite)
- `NOTION_API_KEY` - For Notion push (optional)
- `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID` - Database IDs (optional)
- `NORDVPN_USER`, `NORDVPN_PASS`, `NORDVPN_SERVERS` - VPN SOCKS5 proxy (optional)
- `PROXY_ROTATE_EVERY` - Rotation threshold in requests (default: 15)
- `DB_PATH` - SQLite location (default: `data/app.db`)
- `PREFERENCES_FILE` - Preferences path (default: `data/preferences.txt`)
- `BACKEND_URL` - For frontend (default: `http://backend:8000` in Docker)
- `PYTHONPATH=/workspace` - For editable installs

**Secrets location:**
- `.env` file (never committed via `.gitignore`)
- Template: `.env.example`
- Runtime loading: `python-dotenv` in `apt_scrape/server.py` via `load_dotenv()`

## Webhooks & Callbacks

**Incoming:**
- MCP stdio server - Claude Desktop calls via stdin/stdout transport (`apt_scrape/server.py`)
- FastAPI endpoints for manual triggers and status queries (see `backend/routers/`)

**Outgoing:**
- None configured
- Notion API pushes are one-way (REST POST)
- Nominatim geocoding calls are request-response (no callbacks)

## Browser Automation & Anti-Scraping

**Browser Engine:**
- Camoufox (stealth Firefox with anti-detection headers)
  - Manages: Request delays, header randomization, proxy rotation
  - Location: `apt_scrape/server.py` BrowserManager class

**Proxy Rotation:**
- NordVPN SOCKS5 proxies (optional)
  - Configuration: `NORDVPN_USER`, `NORDVPN_PASS`, `NORDVPN_SERVERS` env vars
  - Proactive rotation: Every N requests (`PROXY_ROTATE_EVERY`, default 15)
  - Reactive rotation: On DataDome/403 block detection
  - Implementation: `apt_scrape/server.py` proxy builder function

**Rate Limiting:**
- REQUEST_DELAY_SECONDS = 2.0 between scrape requests
- Per-config configurable: `rate_limit_seconds` field in SearchConfig
- Concurrency controls for detail-page fetching: 5 slots default (configurable)

---

*Integration audit: 2026-03-16*
