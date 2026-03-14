# rent-fetch

A local MCP server and CLI tool for scraping Italian real estate listings. Built with a plugin architecture — adding a new site means dropping in one config file.

**Tech stack**: [Camoufox](https://camoufox.com) (stealth Firefox) · BeautifulSoup · FastMCP · Python 3.11+

## What It Does

- Searches Immobiliare.it and Casa.it with price, size, room, and location filters
- Fetches full listing detail pages (features, energy class, agency, photos, costs)
- Accepts comma-separated property types for OR queries (`appartamenti,attici`)
- Exports to JSON, CSV, or a compact markdown table
- Enriches listings with `post_date` from detail pages when not present in cards
- Runs as an MCP server for use with Claude Desktop or any MCP-compatible client

## Prerequisites

- Python 3.11+
- pip / venv

## Installation

```bash
git clone https://github.com/tarasivaniv/rent-fetch.git
cd rent-fetch

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt
camoufox fetch                  # downloads browser binary on first run (~100 MB)
```

## Dashboard (Streamlit + Backend)

The app can run a **Streamlit UI** and **FastAPI backend** locally (no Docker).

**One-time:** install backend and frontend deps, then start both processes:

```bash
pip install -r requirements.txt -r backend/requirements.txt -r frontend/requirements.txt
```

**Terminal 1 — Backend:**
```bash
./scripts/run_backend.sh
```

**Terminal 2 — Frontend:**
```bash
./scripts/run_frontend.sh
```

Open **http://127.0.0.1:8501** in the browser (use the sidebar to navigate; opening a sub-page URL directly can cause a 404). See [docs/running-locally.md](docs/running-locally.md) for details and troubleshooting.

## CLI Usage

### Search

```bash
python cli.py search \
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
| `--source` | Site adapter: `immobiliare` (default), `casa` |
| `--start-page` / `--end-page` | Page range to scrape |
| `--include-details` | Fetch detail page for every listing |
| `--detail-limit N` | Cap detail fetches at N (default: all) |
| `--include-csv` | Also write a `.csv` alongside the JSON |
| `--include-table` | Print a markdown table to stdout |
| `--table-max-rows N` | Truncate table output at N rows |
| `-o FILE` | Write output to file (default: stdout) |

### Get a single listing

```bash
python cli.py detail --url "https://www.immobiliare.it/annunci/123456/"
```

Auto-detects the site from the URL. Returns full JSON with all available fields.

### Dump raw HTML

```bash
python cli.py dump --url "https://www.immobiliare.it/affitto-case/milano/" -o debug.html
```

Useful for inspecting HTML structure when adjusting or debugging CSS selectors.

### List registered sites

```bash
python cli.py sites
```

## MCP Server

Start the server for use with Claude Desktop or any MCP client:

```bash
python server.py
```

The server uses stdio transport. Copy `mcp_config_example.json` and update the `cwd` to your local path, then add it to your Claude Desktop config:

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

## Batch Scraping

`scrape_multiple_areas.sh` scrapes multiple neighbourhoods in one run with the same criteria.

```bash
chmod +x scrape_multiple_areas.sh
./scrape_multiple_areas.sh
```

### Configuration

Edit the variables at the top of the script:

```bash
AREAS=("bicocca" "niguarda" "precotto")   # add/remove neighbourhoods

CITY="milano"
OPERATION="affitto"
PROPERTY_TYPES="appartamenti,attici"
MAX_PRICE=1200
MIN_SQM=55
START_PAGE=1
END_PAGE=5
```

### Output

- **JSON per area**: `results/latest/batch/{city}_{area}_{types}_pages{N}_{M}_recent.json`
- **Log file**: `results/latest/batch/scrape_log_YYYYMMDD_HHMMSS.txt`

### Tips

```bash
# Run in background
nohup ./scrape_multiple_areas.sh &

# Monitor live progress
tail -f results/latest/batch/scrape_log_*.txt
```

Uncomment the `# sleep 5` line in the loop to add a 5-second pause between areas.

## Architecture

```
┌──────────────────────────────┐
│  Claude / CLI / MCP Client   │
└──────────┬───────────────────┘
           │ MCP stdio / direct
┌──────────▼───────────────────┐
│  server.py (FastMCP shell)   │
│  • search_listings           │
│  • get_listing_detail        │
│  • list_sites                │
│  • dump_page                 │
└──────────┬───────────────────┘
           │ delegates to
┌──────────▼───────────────────┐
│  sites/ registry             │
│  ├── immobiliare.py          │  Each adapter defines:
│  ├── casa.py                 │  • URL template + param map
│  └── (your_site.py)          │  • CSS selector chains
└──────────┬───────────────────┘  • Property/operation mappings
           │ fetches via
┌──────────▼───────────────────┐
│  BrowserManager (Camoufox)   │
│  Stealth Firefox, rate-limit │
└──────────────────────────────┘
```

## Plugin System — Adding a New Site

### Step 1: Dump the HTML

```bash
# Fetch a search results page
python cli.py dump --url "https://www.idealista.it/affitto-case/bologna/" -o idealista_search.html

# Also grab a detail page
python cli.py dump --url "https://www.idealista.it/immobile/12345/" -o idealista_detail.html
```

Open the HTML in a browser and use DevTools to identify CSS selectors for listing cards, titles, prices, etc.

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

    # How the search URL is built
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

That's it. The MCP tools and CLI automatically pick up the new site.

### Step 4: Test and refine selectors

```bash
# Test search
python cli.py search --city bologna --source idealista --max-price 900

# If results are empty, dump HTML and adjust selectors
python cli.py dump --url "https://www.idealista.it/affitto-case/bologna/" -o debug.html
```

### When to Override

The default config-driven parsing handles most sites. Override `parse_search` or `parse_detail` in your adapter class when:

- The site embeds data in `<script>` tags / JSON-LD instead of visible HTML
- Features are in a single string that needs regex splitting
- Pagination uses infinite scroll instead of URL parameters

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

### SelectorGroup

Each selector field takes a `SelectorGroup` — an ordered list tried until one matches:

```python
SelectorGroup([
    "li.in-feat__item--main",   # most specific — try first
    "div[class*='price']",      # fallback
    "[class*='Price']",         # broadest fallback
])
```

When a site updates its CSS classes, add the new selector at the top without removing the old ones.

## Supported Sites

| Site | `--source` | Notes |
|------|-----------|-------|
| Immobiliare.it | `immobiliare` | Default |
| Casa.it | `casa` | |

## Notes

- **Rate limiting**: 2-second delay between requests, enforced globally in `BrowserManager`
- **Selectors will break**: Sites change HTML regularly. Use `dump` → fix selectors → re-test
- **Camoufox binary**: `camoufox fetch` downloads ~100 MB on first run, cached after that
- **Personal use**: Be respectful of sites' servers and their terms of service

## Contributing

PRs welcome. When adding a new site adapter, include at least one working search command in the PR description to confirm it resolves results.

