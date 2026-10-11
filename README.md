# 🏠 MilHouse

Scrape and monitor Italian real estate listings. Plugin architecture — one config file per site.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.x-FF4B4B?logo=streamlit&logoColor=white)
![Camoufox](https://img.shields.io/badge/Camoufox-stealth_Firefox-FF7139?logo=firefox&logoColor=white)
![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9?logo=astral&logoColor=white)
![MCP](https://img.shields.io/badge/MCP-server-8A2BE2)
![License](https://img.shields.io/badge/License-MIT-green)

---

## What it does

- **Scrape** Immobiliare.it, Casa.it, and Idealista.it with price, size, room, and location filters
- **Schedule** recurring scrape jobs via a cron-style dashboard (powered by APScheduler)
- **AI score** each listing against a plain-text preferences file using LangGraph + Anthropic (or OpenRouter)
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
│  captcha/block detection,           │
│  optional NordVPN SOCKS5 rotation   │
└─────────────────────────────────────┘
```

---

## Web app (React)

The main interface is **MilHouse**, a React app in `src/web` (Vite + TypeScript + Tailwind + shadcn/ui) in Italian. Every listing's AI match score sits on a ten-rung ladder modelled on the Italian APE energy label, and the AI speaks as Milhouse. AI scoring and chat default to Claude Sonnet 5.5 (`ANTHROPIC_MODEL`, `ANALYSIS_EFFORT=low`).

| Section | What it does |
|---|---|
| **Annunci** | Feed of every listing ranked by match, with new ones flagged. Filter by search, ladder rung, triage state or text. The detail sheet shows price, size, €/m², the ladder with the AI's reason, listing data, and triage (preferito / contattato / scartato + note). Keys: `J`/`K` move, `P`/`C`/`X` triage, `O` opens the portal, `/` search, `⌘K` command palette |
| **Chiedi a Milhouse** | Claude-style chat about one listing, streamed as events: what Milhouse is doing, his reasoning (with **Pensaci bene**, a higher-effort mode), then the answer. Answers come from the listing data and your criteria, and requirements are marked soddisfatto / non soddisfatto / non verificabile. The conversation is not saved |
| **Mappa** | Listings on OpenStreetMap; pin size and colour follow the score. **Localizza** geocodes addresses with Nominatim (1 request/second) |
| **Confronta** | Up to three listings side by side, with the best value marked on each row |
| **Ricerche** | Create, edit, duplicate, pause and launch search configs |
| **Run** | Live log over SSE, pipeline phases, counters and per-area stats; a toast and a system notification when a run ends |
| **Criteri** | Edit `preferences.txt` and re-score existing listings |

```bash
cd src/web && npm install     # once
apt start                     # backend :8000, Streamlit :8501, web :5173
```

Open **http://localhost:5173**. In development Vite proxies `/api` to the backend. For a single-process setup, run `npm run build` in `src/web`: FastAPI then serves `src/web/dist` at **http://localhost:8000** (override the location with `WEB_DIST_DIR`). The backend exposes every route under `/api/...` as well as at the root paths Streamlit uses.

---

## Dashboard (Streamlit)

The original Streamlit dashboard (port 8501) still runs alongside. It has six pages:

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

### Local — uv (recommended)

```bash
git clone https://github.com/tarasivaniv/rent-fetch.git
cd rent-fetch

uv sync --all-extras              # installs deps, registers apt / scr-apt CLI
uv run camoufox fetch             # downloads browser binary (~100 MB, one-time)

cp .env.example .env              # fill in API keys (see Environment Variables)
mkdir -p data && touch preferences.txt

apt start                         # backend :8000, Streamlit :8501, React web app :5173
```

Open **http://localhost:5173** for the React app (run `cd src/web && npm install` once first), or **http://127.0.0.1:8501** for the Streamlit dashboard.

See [docs/running-locally.md](docs/running-locally.md) for conda and pip alternatives.

### Docker

> **Not currently supported.** `Dockerfile`s and `docker-compose.yml` are preserved for future use but are not tested and may not work out of the box.

---

## apt CLI

The `apt` CLI manages backend and frontend processes locally.

```bash
apt <command> [service]
```

| Command | Description |
|---------|-------------|
| `apt start` | Start backend, Streamlit frontend and React web app |
| `apt start web` | Start the React web app only (Vite, port 5173) |
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
scr-apt search \
  --city bologna \
  --area murri-massarenti \
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
| `--city` | City slug, e.g. `bologna`, `milano`, `roma` |
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
scr-apt detail --url "https://www.immobiliare.it/annunci/123456/"
```

Auto-detects the site from the URL. Returns full JSON with all available fields.

### Dump raw HTML

```bash
scr-apt dump --url "https://www.immobiliare.it/affitto-case/milano/" -o debug.html
```

Useful for inspecting HTML when adjusting CSS selectors.

### List registered sites

```bash
scr-apt sites
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
    "milhouse": {
      "command": "python",
      "args": ["-m", "apt_scrape.server"],
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
| `PREFERENCES_FILE` | no | `preferences.txt` (repo root) | Plain-text criteria for AI scoring; the **Criteri** page edits the same file |
| `BACKEND_URL` | no | `http://localhost:8000` | URL Streamlit and the Vite dev proxy use to reach the backend |
| `WEB_DIST_DIR` | no | `src/web/dist` | Built React app that FastAPI serves at `/` |
| `ANTHROPIC_API_KEY` | for AI scoring (either this or `OPENROUTER_API_KEY`) | — | Anthropic API key; takes precedence over OpenRouter when set |
| `ANTHROPIC_MODEL` | no | `claude-sonnet-5-5` | Anthropic model ID |
| `OPENROUTER_API_KEY` | for AI scoring (if no Anthropic key) | — | OpenRouter API key |
| `OPENROUTER_MODEL` | no | `google/gemini-3.1-flash-lite-preview` | Model slug passed to OpenRouter |
| `ANALYSIS_EFFORT` | no | `low` | Scoring reasoning effort: `low`, `medium` or `high` (ignored by models without effort support) |
| `ANALYSIS_CONCURRENCY` | no | `5` | Max parallel AI scoring calls (runs and bulk rescores; a single-listing rescore does not wait for them) |
| `NOTION_API_KEY` | for Notion push | — | Notion integration token |
| `NOTION_APARTMENTS_DB_ID` | for Notion push | — | Notion database ID for apartment listings |
| `NOTION_AREAS_DB_ID` | for Notion push | — | Notion database ID for areas |
| `NOTION_AGENCIES_DB_ID` | for Notion push | — | Notion database ID for agencies |
| `NORDVPN_USER` | for proxy rotation | — | NordVPN service username (not your account login — see `.env.example`) |
| `NORDVPN_PASS` | for proxy rotation | — | NordVPN service password |
| `NORDVPN_SERVERS` | for proxy rotation | — | Comma-separated SOCKS5 hostnames, e.g. `socks-nl1.nordvpn.com,socks-us28.nordvpn.com` |
| `PROXY_ROTATE_EVERY` | no | `15` | Requests before rotating to next proxy |
| `DETAIL_CONCURRENCY` | no | `5` | Parallel detail-page fetches for the CLI and MCP server (scheduled runs use the search config's value) |
| `VPN_ROTATE_EVERY_BATCHES` | no | `3` | Detail-fetch batches between VPN rotations for the CLI and MCP server |
| `BROWSER_HEADLESS` | no | `true` | Set to `false` to watch the Camoufox window |
| `BLOCK_ASSETS` | no | off | Set to `1` to skip image downloads (faster, but can look more bot-like to DataDome) |
| `SQLITE_JOURNAL_MODE` | no | `WAL` | SQLite journal mode; use `DELETE` or `TRUNCATE` on Docker bind mounts |

---

## Batch Scraping

`scrape_multiple_areas.sh` scrapes multiple neighbourhoods in one run.

```bash
chmod +x scrape_multiple_areas.sh
./scrape_multiple_areas.sh
```

Edit the variables at the top of the script:

```bash
AREAS=("san-donato-pilastro" "san-vitale-mazzini" "murri-massarenti")
CITY="bologna"
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
scr-apt dump --url "https://www.idealista.it/affitto-case/bologna/" -o idealista_search.html
scr-apt dump --url "https://www.idealista.it/immobile/12345/" -o idealista_detail.html
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
scr-apt search --city bologna --source idealista --max-price 900
scr-apt dump --url "https://www.idealista.it/affitto-case/bologna/" -o debug.html
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

- **Rate limiting**: each search config's "Pausa tra richieste" (default 2 s) spaces every page load, search and detail pages alike; a site's `requests_per_minute` override can only make it slower
- **One run at a time**: a search that is already running is not started twice (the API answers 409), and runs of different searches queue up because they share one browser. A scheduled run missed while the machine slept fires on wake if it is less than 6 h late. Jobs left `running` by a backend restart are marked failed at the next start
- **Blocked pages**: every fetch is checked for anti-bot/captcha pages (DataDome), with or without a proxy. With `NORDVPN_*` set in `.env` the scraper first switches server and retries. If the page stays blocked, or there is no proxy, the listing keeps its search-page data, is marked `detail_status: blocked` (the listing sheet says so) and the next run retries it. After 3 blocks in a row a run stops fetching detail pages, and a blocked search page skips that area with a `[warn]` line instead of failing the run
- **Incremental runs**: a re-run fetches a listing's detail page again only if it is new, its last read was not `ok` (`blocked`, `error`, `empty`) or its price changed, and re-scores only those listings plus any without a valid score. A failed fetch or scoring never overwrites good stored data. `scraped_at`/`job_id` mark the run that first found a listing, `last_seen_at`/`last_job_id` the latest run that saw it
- **Selectors will break**: sites change HTML regularly. Use `dump` → fix selectors → re-test
- **Camoufox binary**: `camoufox fetch` downloads ~100 MB on first run, cached after that
- **Personal use**: be respectful of sites' servers and their terms of service

---

## Contributing

PRs welcome. When adding a new site adapter, include at least one working search command in the PR description to confirm it resolves results.
