# Design: README & Documentation Update

**Date:** 2026-03-14
**Branch:** feat/streamlit-docker-platform
**Goal:** Rewrite README and update setup docs to reflect the full platform (dashboard, `apt` CLI, Docker, Notion, AI scoring) with real screenshots and a polished developer-focused structure, then merge to main.

---

## Context

The current README describes the original CLI/MCP tool but is significantly out of date. Since then the project has grown into a full platform:

- **Streamlit dashboard** with 6 pages (Search Configs, Monitor, Listings, Site Settings, Stats, Preferences)
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

## Files to Change

| File | Change |
|------|--------|
| `README.md` | Full rewrite per structure above |
| `docs/running-locally.md` | Add `apt` CLI section, env vars table, Notion/AI setup |
| `docs/screenshots/` | New directory — user drops 5 PNGs here |
| `.gitignore` | Add `.superpowers/` if not present |

## Files to Leave Unchanged

- `docs/2026-03-14-dashboard-improvements-implementation.md` — internal planning doc, not user-facing
- All backend/frontend source files
- Shell scripts and site adapters

---

## `running-locally.md` Updates

Add the following sections:

1. **`apt` CLI** — `apt start`, `apt stop`, `apt status`, `apt restart`, `apt logs [backend|frontend]`
2. **Environment variables** — table of all required/optional env vars with descriptions and defaults
3. **AI scoring setup** — set `OPENROUTER_API_KEY` and `OPENROUTER_MODEL`; point `PREFERENCES_FILE` at a plain-text file describing what you want in a flat
4. **Notion integration** — set `NOTION_API_KEY` and `NOTION_DATABASE_ID`; mark duplicates via the Search Configs UI

---

## Success Criteria

- [ ] README renders cleanly on GitHub with no broken image links (screenshots at correct paths)
- [ ] All 5 screenshots referenced match files in `docs/screenshots/`
- [ ] `apt start` / Docker setup instructions are accurate and tested
- [ ] Environment variable table is complete
- [ ] `running-locally.md` covers `apt` CLI and all env vars
- [ ] `.superpowers/` is in `.gitignore`
- [ ] Branch merged to main via PR
