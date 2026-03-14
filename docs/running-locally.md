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

## Checking logs

From the repo root you can tail backend or frontend logs:

```bash
./apt logs backend
./apt logs frontend
```

Use this to debug API errors, startup issues, or Streamlit output.

## If the backend won’t start

- **"No module named 'fastapi'"** — Install backend deps:  
  `pip install -r backend/requirements.txt`
- **"No module named 'backend'"** — Run from repo root with:  
  `PYTHONPATH=.` (or use `./scripts/run_backend.sh`).
- **DB or preferences errors** — Set `DB_PATH` and `PREFERENCES_FILE` to writable paths (e.g. `data/app.db` and `data/preferences.txt`) and ensure `data/` exists.
