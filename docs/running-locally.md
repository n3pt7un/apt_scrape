# Running the Dashboard Locally (No Docker)

This describes how to run the **Streamlit dashboard** and **FastAPI backend** on your machine without Docker.

## One-time setup

From the repo root:

```bash
# Create and activate a venv (recommended)
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install all dependencies (CLI + backend + frontend)
pip install -r requirements.txt -r backend/requirements.txt -r frontend/requirements.txt

# Optional: browser for scraping
camoufox fetch
```

Ensure the `data` directory exists (scripts create it if missing):

```bash
mkdir -p data
touch data/preferences.txt
```

## Start backend

In a **first terminal**:

```bash
./scripts/run_backend.sh
```

Or manually:

```bash
export PYTHONPATH=.
export DB_PATH=data/app.db
export PREFERENCES_FILE=data/preferences.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Backend will be at **http://127.0.0.1:8000**. Health check: `curl http://127.0.0.1:8000/health`

## Start frontend

In a **second terminal** (with backend already running):

```bash
./scripts/run_frontend.sh
```

Or manually:

```bash
export BACKEND_URL=http://127.0.0.1:8000
streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0
```

Dashboard will be at **http://127.0.0.1:8501**. The **home page** lists the app’s purpose and links to Search Configs, Monitor, Listings, Site Settings, and Preferences.

## Dashboard features

- **Search Configs:** Choose site (immobiliare, casa, idealista), set rate limits (request delay, page delay), and pick area from the list (managed in Site settings).
- **Site settings:** View full config (base, overrides, effective) and edit overrides as YAML. **Per-site rate limit:** set "Max requests per minute" (e.g. 15 for immobiliare); the runner caps search requests so they never exceed that rate. **Save as test variant** (e.g. `immobiliare-test1`) to create a copy for testing. The **default area list** is per-site: **config/default_areas_immobiliare.txt**, **config/default_areas_casa.txt**, **config/default_areas_idealista.txt** (fallback: **config/default_areas.txt**). Keep these in sync with the AREAS in each shell script.

## Avoiding the 404 on Search Configs

If you see a browser 404 for `Search_Configs/_stcore/host-config`:

- **Open the app from the root URL:** http://127.0.0.1:8501 (not a direct link to a page like `/Search_Configs`).
- Use the **sidebar** to go to "Search Configs", "Monitor", "Preferences", or "Listings".

Opening a page URL directly can trigger that 404; starting from the home page avoids it.

## apt CLI

The `apt` script manages backend and frontend processes from the repo root.

```bash
./apt <command> [service]
```

| Command | Description |
|---------|-------------|
| `apt start` | Start backend and frontend |
| `apt start backend` | Start backend only |
| `apt start frontend` | Start frontend only |
| `apt stop` | Stop all services |
| `apt stop backend` | Stop backend only |
| `apt status` | Show running PIDs and health URLs |
| `apt restart` | Restart all services |
| `apt restart frontend` | Restart frontend only |
| `apt logs backend` | Show last 50 lines of backend log |
| `apt logs frontend -f` | Follow frontend log output (like `tail -f`) |
| `apt logs backend -n 200` | Show last 200 lines |

`apt logs` flags: `-n N` / `--lines N` — number of lines to show (default: 50); `-f` / `--follow` — stream output continuously.

Logs are written to `.logs/backend.log` and `.logs/frontend.log`.

## If the backend won’t start

- **"No module named 'fastapi'"** — Install backend deps:  
  `pip install -r backend/requirements.txt`
- **"No module named 'backend'"** — Run from repo root with:  
  `PYTHONPATH=.` (or use `./scripts/run_backend.sh`).
- **DB or preferences errors** — Set `DB_PATH` and `PREFERENCES_FILE` to writable paths (e.g. `data/app.db` and `data/preferences.txt`) and ensure `data/` exists.

## Environment Variables

Copy `.env.example` to `.env` and fill in values. All are optional unless marked required.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | no | `data/app.db` | SQLite database path |
| `PREFERENCES_FILE` | no | `preferences.txt` (repo root) | Used for AI scoring. `apt` CLI defaults to repo root; shell scripts default to `data/preferences.txt` |
| `BACKEND_URL` | no | `http://127.0.0.1:8000` | URL the frontend uses to reach the backend |
| `OPENROUTER_API_KEY` | for AI scoring | — | OpenRouter API key |
| `OPENROUTER_MODEL` | no | `google/gemini-2.0-flash-lite` (`.env.example`); code fallback: `google/gemini-3.1-flash-lite-preview` | Model slug passed to OpenRouter |
| `ANALYSIS_CONCURRENCY` | no | `5` | Max parallel AI scoring calls |
| `NOTION_API_KEY` | for Notion push | — | Notion integration token |
| `NOTION_APARTMENTS_DB_ID` | for Notion push | — | Notion database ID for apartment listings |
| `NOTION_AREAS_DB_ID` | for Notion push | — | Notion database ID for areas |
| `NOTION_AGENCIES_DB_ID` | for Notion push | — | Notion database ID for agencies |
| `NORDVPN_USER` | for proxy rotation | — | NordVPN service username (see `.env.example` for how to get this) |
| `NORDVPN_PASS` | for proxy rotation | — | NordVPN service password |
| `NORDVPN_SERVERS` | for proxy rotation | — | Comma-separated SOCKS5 hostnames |
| `PROXY_ROTATE_EVERY` | no | `15` | Requests before rotating proxy |

## AI Scoring Setup

1. Set `OPENROUTER_API_KEY` in `.env`
2. Optionally set `OPENROUTER_MODEL` (default: `google/gemini-2.0-flash-lite`)
3. Edit `preferences.txt` in the repo root — plain text, one preference per line, e.g.:
   ```
   I want at least 2 bedrooms
   Prefer quiet streets, not main roads
   Max 1000 EUR/month including utilities
   Close to a metro stop
   ```
4. In the dashboard, enable AI scoring per Search Config — scores appear in the Listings page (0–100)

## Notion Integration

1. Create a Notion integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and copy the token to `NOTION_API_KEY`
2. Create three Notion databases (or duplicate the template) and share each with your integration
3. Copy each database ID to `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID`
4. Enable "Push to Notion" per Search Config in the dashboard — duplicate detection runs automatically on each push
