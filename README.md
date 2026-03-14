# 🏠 rent-fetch

Scrape and monitor Italian real estate listings. Plugin architecture — one config file per site.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.x-FF4B4B?logo=streamlit&logoColor=white)
![Camoufox](https://img.shields.io/badge/Camoufox-stealth_Firefox-FF7139?logo=firefox&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)
![License](https://img.shields.io/badge/License-MIT-green)

---

## What it does

- **Scrape** Immobiliare.it, Casa.it, and Idealista.it with price, size, room, and location filters
- **Schedule** recurring scrape jobs via a cron-style dashboard (powered by APScheduler)
- **AI score** each listing against a plain-text preferences file using LangGraph + OpenRouter
- **Push to Notion** with automatic duplicate detection across three databases (apartments, areas, agencies)
- **MCP server** — expose scraping tools to Claude Desktop or any MCP-compatible client
- **CLI** — run one-off searches, fetch detail pages, dump raw HTML for selector debugging

```
┌──────────────────────────────────────┐
│  Claude Desktop / CLI / MCP Client   │
└──────────┬───────────────────────────┘
           │ MCP stdio / direct call
┌──────────▼───────────────────────────┐
│  FastAPI backend (port 8000)         │
│  • /configs  • /jobs  • /listings    │
│  • /sites    • /preferences          │
│  APScheduler — cron per search config│
└──────┬───────────────┬───────────────┘
       │ scrape        │ score + push
┌──────▼──────┐  ┌─────▼──────────────┐
│ sites/      │  │ apt_scrape/        │
│ registry    │  │ analysis.py        │
│ immobiliare │  │ (LangGraph+OR)     │
│ casa        │  │ notion_push.py     │
│ idealista   │  └────────────────────┘
└──────┬──────┘
       │ fetches via
┌──────▼──────────────────────────────┐
│  BrowserManager (Camoufox)          │
│  Stealth Firefox, rate-limit,       │
│  optional NordVPN SOCKS5 rotation   │
└─────────────────────────────────────┘
```

---

## Dashboard

The Streamlit dashboard (port 8501) has six pages:

| | |
|---|---|
| ![Search Configs](docs/screenshots/search-configs.png) | ![Monitor](docs/screenshots/monitor.png) |
| **Search Configs** — create and manage scrape configs: site, areas, price/size filters, cron schedule, rate limits | **Job Monitor** — live and historical job runs with status, listing count, and expandable logs |
| ![Listings](docs/screenshots/listings.png) | ![Stats](docs/screenshots/stats.png) |
| **Listings** — filterable table with AI scores, area, price, sqm; filter by config, min score, or keyword | **Stats** — total runs, listings per area chart, avg price, AI token usage and cost |

![Site Settings](docs/screenshots/site-settings.png)

**Site Settings** — view effective areas and full config per site; edit overrides as YAML; save as test variant.

**Preferences** — edit the plain-text preferences file used for AI scoring directly in the browser, without leaving the dashboard.

---

## Setup

### Local (recommended)

```bash
git clone https://github.com/tarasivaniv/rent-fetch.git
cd rent-fetch

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt -r backend/requirements.txt -r frontend/requirements.txt
camoufox fetch                  # downloads browser binary (~100 MB, one-time)

cp .env.example .env            # fill in API keys (see Environment Variables)
mkdir -p data && touch preferences.txt

apt start                       # starts backend (port 8000) + frontend (port 8501)
```

Open **http://127.0.0.1:8501** — use the sidebar to navigate.

### Docker

```bash
cp .env.example .env            # fill in API keys
docker compose up -d
```

Backend at **http://localhost:8000**, frontend at **http://localhost:8501**.

---

## apt CLI

The `apt` script manages backend and frontend processes locally.

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
| `apt status` | Show running PIDs and URLs |
| `apt restart` | Restart all services |
| `apt restart frontend` | Restart frontend only |
| `apt logs backend` | Show last 50 lines of backend log |
| `apt logs frontend -f` | Follow frontend log (like `tail -f`) |
| `apt logs backend -n 200` | Show last 200 lines |

`apt logs` flags: `-n N` / `--lines N` — number of lines to show (default: 50); `-f` / `--follow` — stream output continuously.

Logs are written to `.logs/backend.log` and `.logs/frontend.log` in the repo root.

---

## CLI Usage

### Search

```bash
python -m apt_scrape.cli search \
  --city milano \
  --area niguarda \
  --operation affitto \
  --property-type appartamenti,attici \
  --min-price 500 --max-price 1200 \
  --min-sqm 55 --min-rooms 2 \
  --sort piu-recenti \
  --start-page 1 --end-page 5 \
  -o results.json
```

| Flag | Description |
|------|-------------|
| `--city` | City slug, e.g. `milano`, `roma` |
| `--area` | Neighbourhood within the city |
| `--operation` | `affitto` (rent) or `vendita` (sale) |
| `--property-type` | e.g. `appartamenti`, `attici`, or comma-separated for OR |
| `--min-price` / `--max-price` | Monthly rent or sale price in € |
| `--min-sqm` / `--max-sqm` | Floor area in m² |
| `--min-rooms` | Minimum number of rooms |
| `--sort` | `piu-recenti` (most recent), or site-specific sort key |
| `--source` | Site adapter: `immobiliare` (default), `casa`, `idealista` |
| `--start-page` / `--end-page` | Page range to scrape |
| `--include-details` | Fetch detail page for every listing |
| `--detail-limit N` | Cap detail fetches at N (default: all) |
| `--include-csv` | Also write a `.csv` alongside the JSON |
| `--include-table` | Print a markdown table to stdout |
| `--table-max-rows N` | Truncate table output at N rows |
| `-o FILE` | Write output to file (default: stdout) |

### Get a single listing

```bash
python -m apt_scrape.cli detail --url "https://www.immobiliare.it/annunci/123456/"
```

Auto-detects the site from the URL. Returns full JSON with all available fields.

### Dump raw HTML

```bash
python -m apt_scrape.cli dump --url "https://www.immobiliare.it/affitto-case/milano/" -o debug.html
```

Useful for inspecting HTML when adjusting CSS selectors.

### List registered sites

```bash
python -m apt_scrape.cli sites
```

---

## MCP Server

Start the server for use with Claude Desktop or any MCP client:

```bash
python -m apt_scrape.server
```

Copy `mcp_config_example.json`, update `cwd` to your local path, and add it to your Claude Desktop config:

```json
{
  "mcpServers": {
    "rent-fetch": {
      "command": "python",
      "args": ["server.py"],
      "cwd": "/path/to/rent-fetch"
    }
  }
}
```

### MCP Tools

| Tool | Description |
|------|-------------|
| `rental_search_listings` | Search with filters, returns structured listing list |
| `rental_get_listing_detail` | Full detail for one listing URL |
| `rental_list_sites` | Show all registered site adapters |
| `rental_dump_page` | Raw HTML for selector debugging |

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values. All variables are optional unless marked required.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | no | `data/app.db` | SQLite database path |
| `PREFERENCES_FILE` | no | `preferences.txt` (repo root) | Plain-text file for AI scoring. `apt` defaults to repo root; shell scripts default to `data/preferences.txt` |
| `BACKEND_URL` | no | `http://127.0.0.1:8000` | URL the frontend uses to reach the backend |
| `OPENROUTER_API_KEY` | for AI scoring | — | OpenRouter API key |
| `OPENROUTER_MODEL` | no | `google/gemini-2.0-flash-lite` (`.env.example`); code fallback: `google/gemini-3.1-flash-lite-preview` | Model slug passed to OpenRouter |
| `ANALYSIS_CONCURRENCY` | no | `5` | Max parallel AI scoring calls |
| `NOTION_API_KEY` | for Notion push | — | Notion integration token |
| `NOTION_APARTMENTS_DB_ID` | for Notion push | — | Notion database ID for apartment listings |
| `NOTION_AREAS_DB_ID` | for Notion push | — | Notion database ID for areas |
| `NOTION_AGENCIES_DB_ID` | for Notion push | — | Notion database ID for agencies |
| `NORDVPN_USER` | for proxy rotation | — | NordVPN service username (not your account login — see `.env.example`) |
| `NORDVPN_PASS` | for proxy rotation | — | NordVPN service password |
| `NORDVPN_SERVERS` | for proxy rotation | — | Comma-separated SOCKS5 hostnames, e.g. `socks-nl1.nordvpn.com,socks-us28.nordvpn.com` |
| `PROXY_ROTATE_EVERY` | no | `15` | Requests before rotating to next proxy |

---

## Batch Scraping

`scrape_multiple_areas.sh` scrapes multiple neighbourhoods in one run.

```bash
chmod +x scrape_multiple_areas.sh
./scrape_multiple_areas.sh
```

Edit the variables at the top of the script:

```bash
AREAS=("bicocca" "niguarda" "precotto")
CITY="milano"
OPERATION="affitto"
PROPERTY_TYPES="appartamenti,attici"
MAX_PRICE=1200
MIN_SQM=55
START_PAGE=1
END_PAGE=5
```

Output:
- **JSON per area**: `results/latest/batch/{city}_{area}_{types}_pages{N}_{M}_recent.json`
- **Log file**: `results/latest/batch/scrape_log_YYYYMMDD_HHMMSS.txt`

```bash
nohup ./scrape_multiple_areas.sh &          # run in background
tail -f results/latest/batch/scrape_log_*.txt  # monitor progress
```

---

## Plugin System — Adding a New Site

### Step 1: Dump the HTML

```bash
python -m apt_scrape.cli dump --url "https://www.idealista.it/affitto-case/bologna/" -o idealista_search.html
python -m apt_scrape.cli dump --url "https://www.idealista.it/immobile/12345/" -o idealista_detail.html
```

Open in a browser and use DevTools to identify CSS selectors.

### Step 2: Create the adapter

```bash
cp sites/_template.py sites/idealista.py
```

Edit `sites/idealista.py` — fill in `SiteConfig`:

```python
from .base import (
    DetailSelectors, SearchSelectors, SelectorGroup,
    SiteAdapter, SiteConfig,
)

CONFIG = SiteConfig(
    site_id="idealista",
    display_name="Idealista.it",
    base_url="https://www.idealista.it",
    domain_pattern=r"idealista\.it",
    search_path_template="/{operation}-{property_type}/{city}/",
    query_param_map={
        "min_price": "minPrice",
        "max_price": "maxPrice",
        "min_sqm": "minSize",
        "max_sqm": "maxSize",
    },
    page_param="pagina",
    search_wait_selector="article.item",
    detail_wait_selector="h1",
    property_type_map={"case": "case", "appartamenti": "case"},
    operation_map={"affitto": "affitto", "vendita": "vendita"},
    search_selectors=SearchSelectors(
        listing_card=SelectorGroup(["article.item", "div.item-info"]),
        title=SelectorGroup(["a.item-link", "a[class*='title']"]),
        price=SelectorGroup(["span.item-price", "[class*='price']"]),
        features=SelectorGroup(["span.item-detail", "[class*='feature']"]),
        address=SelectorGroup(["span.item-location", "[class*='address']"]),
        thumbnail=SelectorGroup(["img[data-src]", "img"]),
        description=SelectorGroup(["p.item-description", "[class*='desc']"]),
    ),
    detail_selectors=DetailSelectors(
        title=SelectorGroup(["h1"]),
        price=SelectorGroup(["span.info-data-price"]),
        description=SelectorGroup(["div.comment"]),
        features_keys=SelectorGroup(["div.details-property dt"]),
        features_values=SelectorGroup(["div.details-property dd"]),
        address=SelectorGroup(["span[class*='location']"]),
        photos=SelectorGroup(["div.gallery img"]),
        energy_class=SelectorGroup(["[class*='energy']"]),
        agency=SelectorGroup(["div.professional-name"]),
        costs_keys=SelectorGroup(["[class*='cost'] dt"]),
        costs_values=SelectorGroup(["[class*='cost'] dd"]),
    ),
)

class IdealistaAdapter(SiteAdapter):
    def __init__(self):
        super().__init__(CONFIG)
```

### Step 3: Register it

In `sites/__init__.py`, add two lines:

```python
from .idealista import IdealistaAdapter

ADAPTERS: list[SiteAdapter] = [
    ImmobiliareAdapter(),
    CasaAdapter(),
    IdealistaAdapter(),   # ← new
]
```

### Step 4: Test and refine selectors

```bash
python -m apt_scrape.cli search --city bologna --source idealista --max-price 900
python -m apt_scrape.cli dump --url "https://www.idealista.it/affitto-case/bologna/" -o debug.html
```

### When to Override

Override `parse_search` or `parse_detail` in your adapter class when:
- The site embeds data in `<script>` tags / JSON-LD instead of visible HTML
- Features are in a single string that needs regex splitting
- Pagination uses infinite scroll instead of URL parameters

---

## SiteConfig Reference

```python
@dataclass
class SiteConfig:
    site_id: str              # "immobiliare" — used as --source value
    display_name: str         # "Immobiliare.it" — shown in output
    base_url: str             # "https://www.immobiliare.it"
    domain_pattern: str       # regex for URL matching in detail()

    search_path_template: str # "/{operation}-{property_type}/{city}/"
    query_param_map: dict     # {"min_price": "prezzoMinimo", ...}
    page_param: str           # "pag"

    search_wait_selector: str # CSS selector Camoufox waits for before parsing
    detail_wait_selector: str

    search_selectors: SearchSelectors  # CSS selectors for search results
    detail_selectors: DetailSelectors  # CSS selectors for detail pages

    property_type_map: dict   # {"appartamenti": "appartamenti", ...}
    operation_map: dict       # {"affitto": "affitto", "vendita": "vendita"}
```

Each selector field takes a `SelectorGroup` — an ordered list tried until one matches:

```python
SelectorGroup([
    "li.in-feat__item--main",   # most specific — try first
    "div[class*='price']",      # fallback
    "[class*='Price']",         # broadest fallback
])
```

---

## Supported Sites

| Site | `--source` | Notes |
|------|-----------|-------|
| Immobiliare.it | `immobiliare` | Default |
| Casa.it | `casa` | |
| Idealista.it | `idealista` | |

---

## Notes

- **Rate limiting**: configurable per-site delay in Search Configs; default 2 s between requests
- **Proxy rotation**: optional NordVPN SOCKS5 rotation — set `NORDVPN_*` vars in `.env`
- **Selectors will break**: sites change HTML regularly. Use `dump` → fix selectors → re-test
- **Camoufox binary**: `camoufox fetch` downloads ~100 MB on first run, cached after that
- **Personal use**: be respectful of sites' servers and their terms of service

---

## Contributing

PRs welcome. When adding a new site adapter, include at least one working search command in the PR description to confirm it resolves results.
