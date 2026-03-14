# Design: README & Documentation Update

**Date:** 2026-03-14
**Branch:** feat/streamlit-docker-platform
**Goal:** Rewrite README and update setup docs to reflect the full platform (dashboard, `apt` CLI, Docker, Notion, AI scoring) with real screenshots and a polished developer-focused structure, then merge to main.

---

## Context

The current README describes the original CLI/MCP tool but is significantly out of date. Since then the project has grown into a full platform:

- **Streamlit dashboard** with 6 pages (Search Configs, Monitor, Preferences, Listings, Site Settings, Stats) — in sidebar order
- **FastAPI backend** with APScheduler for cron-triggered scrape jobs
- **`apt` dev CLI** (`start` / `stop` / `status` / `restart` / `logs`)
- **Docker Compose** setup alongside the existing local dev setup
- **AI scoring** via LangGraph + OpenRouter (scores listings against a plain-text preferences file)
- **Notion push** for synced listing storage with duplicate detection
- **Per-site config overrides** for areas and CSS selectors managed via the UI

The README also lacks any visual assets (screenshots, badges) and has no mention of the new Stats page, AI cost tracking, or Notion integration.

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| README structure | Developer-focused | Explain architecture + what it does before installation |
| Screenshots | Real PNGs at `docs/screenshots/` (5 images) | Always render on GitHub, provided by user |
| Screenshot layout | 2×2 grid + 1 full-width | Balanced density, shows breadth without scrolling |
| Primary setup path | Local (`apt start`) | Most common use case; Docker is a secondary option |
| Badges | Tech stack + MIT license | Inline shields.io badges in header |
| `running-locally.md` | Expand to cover `apt` CLI, env vars, Notion/AI config | Existing doc is accurate but incomplete |

---

## README Structure

```
# 🏠 rent-fetch
[badges: Python · FastAPI · Streamlit · Camoufox · Docker · MCP · MIT]

One-line description.

## What it does
- Feature bullet list (scrape, schedule, AI score, Notion push, MCP)
- ASCII architecture diagram

## Dashboard
[2×2 screenshot grid: Search Configs, Monitor, Listings, Stats]
[Full-width: Site Settings]
Brief description of each page.

## Setup
### Local (recommended)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r backend/requirements.txt -r frontend/requirements.txt
camoufox fetch
apt start          # starts backend + frontend
```
Open http://127.0.0.1:8501

### Docker
```bash
cp .env.example .env   # fill in OPENROUTER_API_KEY etc.
docker compose up -d
```

## apt CLI
start / stop / status / restart / logs — table of subcommands

## CLI (scraper)
Existing CLI reference table (trimmed) + single-listing detail + dump

## MCP Server
Existing MCP section (unchanged, already accurate)

## Environment Variables
Table: OPENROUTER_API_KEY, OPENROUTER_MODEL, NOTION_API_KEY, NOTION_DATABASE_ID, DB_PATH, PREFERENCES_FILE, BACKEND_URL

## Plugin System — Adding a New Site
(Keep existing content, already good)

## SiteConfig Reference
(Keep existing content)

## Supported Sites
(Keep existing table)

## Contributing
(Keep existing content)
```

---

## Screenshot Filenames

All 5 screenshots live in `docs/screenshots/`:

| Filename | Page |
|----------|------|
| `docs/screenshots/search-configs.png` | Search Configurations |
| `docs/screenshots/monitor.png` | Job Monitor |
| `docs/screenshots/listings.png` | Listings (AI scored) |
| `docs/screenshots/stats.png` | Statistics |
| `docs/screenshots/site-settings.png` | Site Settings (full-width) |

The user will drop real PNGs there before merging. The implementation must create `docs/screenshots/.gitkeep` so the directory is tracked and the README image links resolve (they will show broken images until PNGs are added, which is acceptable pre-merge).

## Files to Change

| File | Change |
|------|--------|
| `README.md` | Full rewrite per structure above |
| `docs/running-locally.md` | Add `apt` CLI section, env vars table, Notion/AI setup |
| `docs/screenshots/.gitkeep` | New file — tracks the empty directory in git |

## Files to Leave Unchanged

- `docs/2026-03-14-dashboard-improvements-implementation.md` — internal planning doc, not user-facing
- All backend/frontend source files
- Shell scripts and site adapters

---

## `running-locally.md` Updates

Add the following sections:

1. **`apt` CLI** — consolidate and expand the existing `./apt logs` mention into a full `apt` CLI section covering `start`, `stop`, `status`, `restart`, `logs [backend|frontend] [-n N] [-f]` with a command table. Include the `-n/--lines` and `-f/--follow` flags for `logs`. Remove the standalone `./apt logs` mention to avoid duplication.
2. **Environment variables** — table with the following rows:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | no | `data/app.db` | SQLite database path |
| `PREFERENCES_FILE` | no | `preferences.txt` (repo root) | Plain-text file used for AI scoring; `apt` CLI defaults to repo root, scripts default to `data/preferences.txt` |
| `BACKEND_URL` | no | `http://127.0.0.1:8000` | URL the frontend uses to reach the backend |
| `OPENROUTER_API_KEY` | for AI scoring | — | OpenRouter API key |
| `OPENROUTER_MODEL` | no | `google/gemini-2.0-flash-lite` (`.env.example`) | Model slug passed to OpenRouter; code fallback is `google/gemini-3.1-flash-lite-preview` |
| `ANALYSIS_CONCURRENCY` | no | `5` | Max parallel AI scoring calls |
| `NOTION_API_KEY` | for Notion push | — | Notion integration token |
| `NOTION_APARTMENTS_DB_ID` | for Notion push | — | Notion database ID for apartment listings |
| `NOTION_AREAS_DB_ID` | for Notion push | — | Notion database ID for areas |
| `NOTION_AGENCIES_DB_ID` | for Notion push | — | Notion database ID for agencies |
| `NORDVPN_USER` | for proxy rotation | — | NordVPN service username (not account login) |
| `NORDVPN_PASS` | for proxy rotation | — | NordVPN service password |
| `NORDVPN_SERVERS` | for proxy rotation | — | Comma-separated SOCKS5 hostnames |
| `PROXY_ROTATE_EVERY` | no | `15` | Requests before rotating proxy |

3. **AI scoring setup** — set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`; point `PREFERENCES_FILE` at a plain-text file describing preferences
4. **Notion integration** — set `NOTION_API_KEY` and `NOTION_DATABASE_ID`; duplicate detection runs automatically on push

---

## Success Criteria

- [ ] README renders correctly on GitHub (no broken image links once PNGs are added)
- [ ] All 5 PNG files confirmed present at the named paths in `docs/screenshots/` before merging
- [ ] `docs/screenshots/.gitkeep` committed so the directory exists in the PR
- [ ] `apt start` / Docker setup instructions are accurate
- [ ] Environment variable table covers all 12 variables defined in spec
- [ ] `running-locally.md` covers `apt` CLI (with `-n`/`-f` flags) and all env vars
- [ ] Branch merged to main via PR
