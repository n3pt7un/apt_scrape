# uv Migration & Repo Reorganization — Design Spec

**Date:** 2026-03-16
**Status:** Approved

---

## Goal

Migrate environment management from plain venv + pip to `uv`. Consolidate three `requirements.txt` files into a single `pyproject.toml`. Register `apt` and `scr-apt` as proper uv console script entry points. Update docs to lead with uv while also covering conda and pip. Deprecate (but preserve) Docker support.

---

## Approach

**Option A — Single `pyproject.toml` with optional extras.** Chosen for simplicity and idiomatic uv structure.

---

## 1. Dependencies

All deps move into `pyproject.toml` at the repo root. The three `requirements.txt` files (`requirements.txt`, `backend/requirements.txt`, `frontend/requirements.txt`) are deleted.

```toml
[project]
name = "apt-scrape"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
  # core scraping + shared
  "mcp>=1.0.0",
  "pydantic>=2.0.0",
  "beautifulsoup4>=4.12.0",
  "camoufox[geoip]>=0.4.0",
  "lxml>=5.0.0",
  "pyyaml>=6.0",
  "python-dotenv>=1.0",
  "pproxy>=2.7.8",
  "click>=8.1.0",
  "langgraph>=0.2",
  "langchain-openai>=0.2",
  "langchain-core>=0.3",
  "notion-client==2.2.1",
]

[project.optional-dependencies]
backend  = [
  "fastapi==0.115.6",
  "uvicorn[standard]==0.32.1",
  "apscheduler==3.10.4",
  "sqlmodel==0.0.21",
  "aiofiles==24.1.0",
  "httpx==0.28.1",
]
frontend = [
  "streamlit==1.42.0",
  "httpx==0.28.1",
]

[project.scripts]
apt     = "apt_scrape.devctl:cli"
scr-apt = "apt_scrape.cli:cli"

[tool.uv]
dev-dependencies = ["pytest", "pytest-asyncio>=0.23"]
```

Local dev install: `uv sync --all-extras`

---

## 2. Entry Points

### `apt` → `apt_scrape/devctl.py`

Move the content of the root `apt` script into `apt_scrape/devctl.py`. The bare `apt` file at repo root is deleted. The module exposes a `cli` Click group identical to the current one.

Commands: `start`, `stop`, `restart`, `status`, `logs` (unchanged behavior).

### `scr-apt` → `apt_scrape/cli.py`

No code changes. The existing `cli` Click group in `apt_scrape/cli.py` is registered as the `scr-apt` entry point. `python -m apt_scrape.cli` continues to work as a fallback.

---

## 3. Documentation

### `docs/running-locally.md`

Rewritten to lead with uv. Sections for conda and pip follow as alternatives. Structure:

1. **uv (recommended)** — `uv sync --all-extras`, `camoufox fetch`, `apt start`
2. **conda** — create env, `pip install -e ".[backend,frontend]"` after activating
3. **pip** — `python -m venv .venv`, `pip install -e ".[backend,frontend]"`
4. Docker note — not currently maintained

### `README.md`

Setup section updated to show uv-first quickstart. A note links to `docs/running-locally.md` for conda/pip alternatives.

### Docker

Both docs include a note:
> Docker support is not currently maintained. `Dockerfile`s and `docker-compose.yml` are preserved for future use but may not work out of the box.

---

## Files Changed

| Action | File |
|--------|------|
| Create | `pyproject.toml` |
| Create | `apt_scrape/devctl.py` (content from `apt`) |
| Delete | `apt` (root script) |
| Delete | `requirements.txt` |
| Delete | `backend/requirements.txt` |
| Delete | `frontend/requirements.txt` |
| Rewrite | `docs/running-locally.md` |
| Update | `README.md` (setup section) |

---

## Out of Scope

- Docker fixes or updates
- Changes to scraper logic, backend, or frontend code
- `uv` lockfile committed to repo (`.python-version` may be added)
