# Technology Stack

**Analysis Date:** 2026-03-16

## Languages

**Primary:**
- Python 3.12 - Backend scraping, analysis, API, and frontend orchestration

## Runtime

**Environment:**
- Python 3.12 (slim Docker images)

**Package Manager:**
- pip
- Lockfile: No (uses requirements.txt per module)

## Frameworks

**Web API:**
- FastAPI 0.115.6 - REST API backend for job management, config CRUD, listings queries, Notion push orchestration. Location: `backend/main.py`

**Frontend UI:**
- Streamlit 1.42.0 - Multi-page dashboard for search configs, job monitoring, listings browsing, preferences editing, site settings. Location: `frontend/app.py`

**Web Scraping:**
- Camoufox (latest via fetch) - Stealth Firefox browser for anti-scraping bypass. Handles proxy rotation, request delays, header obfuscation. Location: `apt_scrape/server.py`
- BeautifulSoup4 4.12.0 - HTML parsing for data extraction. Location: `apt_scrape/sites/`
- lxml 5.0.0 - XML/HTML processing backend for BeautifulSoup

**Task Scheduling:**
- APScheduler 3.10.4 - Cron-based job scheduling for recurring scrape jobs. Location: `backend/scheduler.py`

**AI/LLM:**
- LangGraph 0.2+ - Graph-based LLM agent framework for structured multi-step analysis. Location: `apt_scrape/analysis.py`
- LangChain-OpenAI 0.2+ - OpenRouter client integration
- LangChain-Core 0.3+ - Shared abstractions for LLM tools and state management

**Testing:**
- pytest-asyncio 0.23+ - Async test execution support

**Build/Dev:**
- Docker Compose - Multi-container orchestration
- uvicorn[standard] 0.32.1 - ASGI server for FastAPI

## Key Dependencies

**Critical:**
- fastapi 0.115.6 - REST API framework with async/await support
- camoufox - Stealth browser for scraping with proxy support
- sqlmodel 0.0.21 - SQLAlchemy ORM with Pydantic validation; table definitions in `backend/db.py`
- notion-client 2.2.1 - Notion API SDK for pushing listings to Notion databases
- langchain-openai - OpenRouter integration for LLM analysis via `apt_scrape/analysis.py`
- langgraph - LLM agent orchestration with state graphs

**HTTP/Network:**
- httpx 0.28.1 - Async HTTP client (used in both backend and frontend)
- pproxy 2.7.8 - Proxy rotation and SOCKS5 handling
- python-dotenv 1.0.1 - Environment variable loading

**Data Processing:**
- beautifulsoup4 4.12.0 - HTML parsing for site adapters
- lxml 5.0.0 - Fast XML/HTML processing
- pyyaml 6.0+ - YAML parsing for site config overrides (`backend/routers/sites.py`)

**CLI:**
- click 8.1.0+ - Command-line interface for `apt` CLI tool

**MCP (Model Context Protocol):**
- mcp 1.0.0+ - Server implementation for Claude Desktop integration. Location: `apt_scrape/server.py`

## Configuration

**Environment:**
- Located in `.env` (note: `.env` file present - contains sensitive credentials)
- Template provided: `.env.example`
- Key required vars:
  - `NORDVPN_USER`, `NORDVPN_PASS`, `NORDVPN_SERVERS` - VPN proxy rotation (optional)
  - `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` - LLM integration (optional)
  - `NOTION_API_KEY`, `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID` - Notion push (optional)
  - `DB_PATH` - SQLite database location (default: `data/app.db`)
  - `PREFERENCES_FILE` - Path to preferences.txt for AI scoring (default: `data/preferences.txt`)

**Build:**
- Docker Compose: `docker-compose.yml`
- Backend Dockerfile: `backend/Dockerfile`
- Frontend Dockerfile: `frontend/Dockerfile`
- Module requirements split per component:
  - `requirements.txt` - Root-level shared dependencies (MCP, LangGraph, Notion, web scraping libraries)
  - `backend/requirements.txt` - FastAPI, APScheduler, SQLModel, Uvicorn
  - `frontend/requirements.txt` - Streamlit, httpx, PyYAML

## Platform Requirements

**Development:**
- Python 3.12+
- ~100 MB disk for Camoufox browser binary (downloaded on first run via `camoufox fetch`)
- 500 MB+ for venv and dependencies

**Production:**
- Docker (docker-compose recommended)
- Network connectivity to: Immobiliare.it, Casa.it, Idealista.it, OpenRouter API, Notion API
- NordVPN account (optional, for SOCKS5 proxy rotation)
- Environment variables configured (see `.env.example`)

---

*Stack analysis: 2026-03-16*
