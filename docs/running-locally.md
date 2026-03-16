# Running the Dashboard Locally

This describes how to run the **Streamlit dashboard** and **FastAPI backend** on your machine.

> **Docker:** Docker support is not currently maintained. `Dockerfile`s and `docker-compose.yml` are preserved for future use but may not work out of the box.

## One-time setup

### Option A: uv (recommended)

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# From the repo root — installs everything and registers the apt / scr-apt CLI
uv sync --all-extras

# Optional: browser for scraping
uv run camoufox fetch
```

Ensure the data directory exists:

```bash
mkdir -p data
touch data/preferences.txt
```

### Option B: conda

```bash
conda create -n apt-scrape python=3.11
conda activate apt-scrape
pip install -e ".[backend,frontend]"
uv run camoufox fetch   # or: python -m camoufox fetch
```

### Option C: plain pip / venv

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[backend,frontend]"
python -m camoufox fetch
```

---

## Start the services

### With uv (recommended)

```bash
apt start   # starts backend (port 8000) + frontend (port 8501)
```

`apt` is a uv console script entry point registered by `uv sync`. If it isn't on your PATH yet, run `source ~/.local/bin/env` or restart your shell.

### Manually (all install methods)

Start the backend in one terminal:

```bash
export PYTHONPATH=src
export DB_PATH=data/app.db
export PREFERENCES_FILE=data/preferences.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Start the frontend in a second terminal (with backend already running):

```bash
export BACKEND_URL=http://127.0.0.1:8000
streamlit run src/frontend/app.py --server.port 8501 --server.address 0.0.0.0
```

Backend: **http://127.0.0.1:8000** — health check: `curl http://127.0.0.1:8000/health`
Dashboard: **http://127.0.0.1:8501** — use the sidebar to navigate.

---

## apt CLI

The `apt` entry point manages backend and frontend processes from any directory.

```bash
apt <command> [service]
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

---

## Dashboard features

- **Search Configs:** Choose site (immobiliare, casa, idealista), set rate limits (request delay, page delay), and pick area from the list (managed in Site settings).
- **Site settings:** View full config (base, overrides, effective) and edit overrides as YAML. **Per-site rate limit:** set "Max requests per minute" (e.g. 15 for immobiliare). **Save as test variant** to create a copy for testing. The **default area list** is per-site: **config/default_areas_immobiliare.txt**, **config/default_areas_casa.txt**, **config/default_areas_idealista.txt** (fallback: **config/default_areas.txt**).

## Avoiding the 404 on Search Configs

If you see a browser 404 for `Search_Configs/_stcore/host-config`:

- **Open the app from the root URL:** http://127.0.0.1:8501 (not a direct link to a page like `/Search_Configs`).
- Use the **sidebar** to go to "Search Configs", "Monitor", "Preferences", or "Listings".

---

## If the backend won't start

- **"No module named 'fastapi'"** — Install backend deps:
  `uv sync --extra backend`
  (pip: `pip install -e ".[backend]"`)
- **"No module named 'backend'"** — Run from repo root with `PYTHONPATH=.` set.
- **DB or preferences errors** — Set `DB_PATH` and `PREFERENCES_FILE` to writable paths (e.g. `data/app.db` and `data/preferences.txt`) and ensure `data/` exists.

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values. All are optional unless marked required.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | no | `data/app.db` | SQLite database path |
| `PREFERENCES_FILE` | no | `preferences.txt` (repo root) | Used for AI scoring. `apt` CLI defaults to repo root |
| `BACKEND_URL` | no | `http://127.0.0.1:8000` | URL the frontend uses to reach the backend |
| `OPENROUTER_API_KEY` | for AI scoring | — | OpenRouter API key |
| `OPENROUTER_MODEL` | no | `google/gemini-2.0-flash-lite` | Model slug passed to OpenRouter |
| `ANALYSIS_CONCURRENCY` | no | `5` | Max parallel AI scoring calls |
| `NOTION_API_KEY` | for Notion push | — | Notion integration token |
| `NOTION_APARTMENTS_DB_ID` | for Notion push | — | Notion database ID for apartment listings |
| `NOTION_AREAS_DB_ID` | for Notion push | — | Notion database ID for areas |
| `NOTION_AGENCIES_DB_ID` | for Notion push | — | Notion database ID for agencies |
| `NORDVPN_USER` | for proxy rotation | — | NordVPN service username (see `.env.example`) |
| `NORDVPN_PASS` | for proxy rotation | — | NordVPN service password |
| `NORDVPN_SERVERS` | for proxy rotation | — | Comma-separated SOCKS5 hostnames |
| `PROXY_ROTATE_EVERY` | no | `15` | Requests before rotating proxy |

---

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

---

## Notion Integration

1. Create a Notion integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and copy the token to `NOTION_API_KEY`
2. Create three Notion databases (or duplicate the template) and share each with your integration
3. Copy each database ID to `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID`
4. Enable "Push to Notion" per Search Config in the dashboard — duplicate detection runs automatically on each push
