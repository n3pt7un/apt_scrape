# Design: LangGraph Listing Analysis + Notion Push

**Date:** 2026-03-14
**Status:** Approved

---

## Context

The existing `apt_scrape` pipeline scrapes Italian property listings from Immobiliare.it, Casa.it, and Idealista.it, enriches them with detail-page data, and exports to JSON/CSV. The user wants two additions:

1. **AI analysis**: a LangGraph agent that scores each listing (0–100) against a user-defined preferences file, outputting a star rating, verdict, and brief reason.
2. **Notion ingestion**: automatic creation of pages in an existing Notion Apartments database, with relational links to the Areas and Agencies databases.

The outcome is a fully automated pipeline: scrape → analyse → push to Notion, where each Notion page arrives pre-scored and ready to review.

---

## Architecture Overview

```
search command
  → scrape pages                  (existing)
  → enrich details                (existing, if --include-details)
  → [AI analysis]                 (NEW, if --analyse)
  → [Notion push]                 (NEW, if --push-notion)
  → JSON output                   (existing, now includes ai_* fields)

push subcommand (for existing JSON files)
  → load JSON file
  → [AI analysis]                 (NEW, if --analyse)
  → [Notion push]                 (NEW, if --push-notion)
```

### New files

| File | Purpose |
|---|---|
| `apt_scrape/analysis.py` | LangGraph agent — scores listings against preferences |
| `apt_scrape/notion_push.py` | Notion API client — maps listings to DB pages |
| `preferences.txt` | Plain-text user preferences file (project root) |

### Modified files

| File | Change |
|---|---|
| `apt_scrape/cli.py` | New `--analyse` / `--push-notion` flags on `search`; new `push` subcommand |
| `requirements.txt` | Add `langgraph`, `langchain-openai`, `notion-client` |

---

## Module 1: analysis.py — LangGraph Agent

### Why LangGraph

A LangGraph `StateGraph` is used instead of a plain async function because the graph interface makes it straightforward to extend later (e.g., add a retry node on low confidence, a web-search node to verify transport times, or a second LLM pass for deal-breakers). For now the graph has a single node, but the boundary is already drawn correctly for future extension.

### LLM configuration

- Provider: **OpenRouter** via LangChain's `ChatOpenAI` with `base_url="https://openrouter.ai/api/v1"`
- Default model: `google/gemini-3.1-flash-lite-preview` (verify slug on https://openrouter.ai/models before first use; override via env var if needed)
- Env vars:
  ```
  OPENROUTER_API_KEY=...
  OPENROUTER_MODEL=google/gemini-3.1-flash-lite-preview   # overridable
  ANALYSIS_CONCURRENCY=5
  ```

### Preferences file

Loaded from `preferences.txt` at the project root (or `PREFERENCES_FILE` env var). Plain-text, free-form. Injected verbatim into the system prompt.

### LangGraph graph

```
START → analyse_listing → END
```

State:

```python
class AnalysisState(TypedDict):
    listing: dict
    result: AnalysisResult | None
```

Structured output model (used with `.with_structured_output()`):

```python
class AnalysisResult(BaseModel):
    score: int       # 0–100
    verdict: str     # e.g. "Strong match", "Skip", "Potential"
    reason: str      # 1–2 sentence explanation
```

If `.with_structured_output()` fails (e.g., model does not support tool calling), fall back to asking the model to respond with a JSON block and parse it manually with `json.loads()`. If that also fails, default to `score=0, verdict="Error", reason=<error message>` so the listing still reaches Notion.

### Listing context fed to the LLM

The node formats these fields from the listing dict (all accesses use `.get()` with empty-string defaults):
- `listing.get("detail", {}).get("title") or listing.get("title")` — apartment name
- `listing.get("price")`
- `listing.get("detail", {}).get("size") or listing.get("sqm")` — size in m²
- `listing.get("rooms")`
- `listing.get("detail", {}).get("floor")`
- `listing.get("detail_address") or listing.get("address")`
- `listing.get("detail_description", "")` — full description (not truncated)
- `listing.get("detail_features", {})` — key-value feature pairs
- `listing.get("detail_costs", {})` — cost breakdown
- `listing.get("detail_energy_class")`

### Score → stars mapping

| Score | Stars |
|---|---|
| 0–19 | ⭐ |
| 20–39 | ⭐⭐ |
| 40–59 | ⭐⭐⭐ |
| 60–79 | ⭐⭐⭐⭐ |
| 80–100 | ⭐⭐⭐⭐⭐ |

### Output fields added to each listing dict

```
ai_score    int        0–100 numeric score
ai_stars    str        ⭐ to ⭐⭐⭐⭐⭐  (JSON serialized with ensure_ascii=False)
ai_verdict  str        short label
ai_reason   str        1–2 sentence explanation
```

### Concurrency

Listings are analysed with `asyncio.gather()` behind a semaphore capped at `ANALYSIS_CONCURRENCY` (default 5). Each wave is bounded by one LLM round-trip (latency depends on model and load).

---

## Module 2: notion_push.py — Notion Integration

### Client

Uses `notion-client` Python library (async `AsyncClient`). Must be used as an async context manager (`async with AsyncClient(...) as client`) or explicitly closed after use to avoid resource leaks. Integration token set via `NOTION_API_KEY`.

### Env vars

```
NOTION_API_KEY=...
NOTION_APARTMENTS_DB_ID=0790f76c-2f79-4c89-9028-ba075db0490c
NOTION_AREAS_DB_ID=700f985e-a354-41da-80fc-79a666f10c49
NOTION_AGENCIES_DB_ID=26db1f66-8cc1-428a-bb71-3787038a8c7e
```

### Deduplication

Before creating a page, query the Apartments DB for an existing page where `Listing URL` equals the listing's `url`. If found, skip and record as `notion_skipped=True` in the listing dict.

### Area field injection

The `area` slug lives in the top-level JSON envelope, not on each listing dict. Before calling `notion_push` (or `analysis`), the `search` command and `push` subcommand both stamp `_area` and `_city` onto every listing dict:

```python
for listing in listings:
    listing["_area"] = area   # slug from search params / JSON envelope
    listing["_city"] = city
```

This makes each listing self-contained for relation lookups.

### Area relation lookup

Query the Areas DB for a page whose `Area Name` matches `listing["_area"]` (de-slugified: hyphens → spaces, title-cased, e.g. `"porta-venezia"` → `"Porta Venezia"`). Results cached in memory per push session. If no match, leave the Area relation empty and log a warning. The Areas DB page names must use the same canonical form as the de-slugified area slugs; maintaining that alignment is the user's responsibility.

### Agency relation lookup / create

Look up the Agencies DB for a page whose `Agency Name` matches `listing.get("detail_agency")`. If not found, create a new Agency page with:
- `Agency Name` = `detail_agency`
- `Status` = `"⚪ Not Yet Contacted"`

If `detail_agency` is absent or empty (e.g. listing was scraped without `--include-details`), skip the agency relation entirely — leave it unlinked. Results cached in memory per push session.

### New Notion properties to add to the Apartments DB

These extend the existing schema (user confirmed extensibility):

| Property name | Type | Purpose |
|---|---|---|
| `Source` | select | Scraping site (Immobiliare.it / Casa.it / Idealista.it) |
| `AI Score` | number | Raw 0–100 numeric score (for formula-based sorting) |
| `AI Reason` | text | Full reasoning from the LLM |
| `Energy Class` | select | A–G energy efficiency rating |
| `Scraped At` | date | ISO-8601 datetime when the listing was scraped |

**Important:** The Notion API does NOT auto-create database properties from page creation requests — unknown properties are silently ignored or return a 400 error. `notion_push.py` must include a `_ensure_schema()` helper that calls `PATCH /v1/databases/{db_id}` to create any missing properties before the first page is written. This runs once per push session, not per listing. See the Notion API reference at https://developers.notion.com/reference/update-a-database for the exact payload shape per property type (e.g., `select` requires an `options` list, `number` requires a `format` field).

### Field mapping (listing dict → Apartments DB)

| Notion property | Source | Notes |
|---|---|---|
| `Apartment` (title) | `listing.get("detail", {}).get("title") or listing.get("title")` | Prefer detail page title |
| `Status` | — | Always `"👀 To Visit"` |
| `Score` | `ai_stars` | select property — emoji string (⭐–⭐⭐⭐⭐⭐); only set if `--analyse` was used |
| `Rent (€/mo)` | `price` | Extract numeric with regex (e.g. `€ 1.200/mese` → `1200`) |
| `Size (m²)` | `listing.get("detail", {}).get("size") or listing.get("sqm")` | Extract numeric |
| `Rooms` | `rooms` | Text as-is |
| `Floor` | `listing.get("detail", {}).get("floor")` | — |
| `Address` | `detail_address` or `address` | Prefer detail address |
| `Listing URL` | `url` | Used for deduplication |
| `Notes` | `ai_verdict + ": " + ai_reason` | Only set if `--analyse` was used |
| `Area` | `listing["_area"]` | Relation lookup in Areas DB (injected field) |
| `Agency` | `detail_agency` | Relation lookup/create in Agencies DB |
| `Source` | `source` | NEW property |
| `AI Score` | `ai_score` | NEW number property (int 0–100), only if `--analyse` |
| `AI Reason` | `ai_reason` | NEW property, only if `--analyse` |
| `Energy Class` | `detail_energy_class` | NEW property |
| `Scraped At` | current ISO-8601 datetime | NEW property |

### Output fields added to each listing dict

```
notion_page_id    str    Notion page ID (if created)
notion_page_url   str    Notion page URL
notion_skipped    bool   True if page already existed
```

---

## CLI Integration

### Modified: `search` command

Two new flags appended to the existing options:

```bash
python -m apt_scrape.cli search \
  --city milano --area bicocca --source immobiliare \
  --include-details --max-pages 3 \
  --analyse \          # run AI scoring after scraping
  --push-notion        # push results to Notion after analysis
```

Both flags are independent — `--push-notion` can run without `--analyse` (pages will be created without AI scores).

### New: `push` subcommand

Post-processes an existing JSON file:

```bash
python -m apt_scrape.cli push results/xyz.json --analyse --push-notion
```

Reads the JSON file, optionally runs analysis, optionally pushes to Notion, writes the updated JSON atomically (write to `.tmp` file then rename) back to the original path with `ai_*` and `notion_*` fields appended. The `_area` and `_city` fields are injected from the JSON envelope's `area` and `city` keys.

### Preferences file

`preferences.txt` at project root, loaded automatically when `--analyse` is used. Override path with `PREFERENCES_FILE` env var. Example content:

```
I am looking for a 2-3 bedroom apartment to rent in Milan.

MUST HAVE:
- At least 60 sqm
- Private outdoor space (balcony, terrace, or garden)
- Available by June 2025

NICE TO HAVE:
- Bright / south-facing
- Elevator
- Close to metro

DEAL BREAKERS:
- Ground floor with no garden
- Price above €1,400/month
```

---

## Dependencies to add

```
langgraph>=0.2
langchain-openai>=0.2
langchain-core>=0.3
notion-client>=2.2
```

Add to `requirements.txt`.

---

## Verification

### End-to-end test

1. Set env vars: `OPENROUTER_API_KEY`, `NOTION_API_KEY`, `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID`
2. Create a `preferences.txt` with sample criteria
3. Run a small search with `--analyse --push-notion`:
   ```bash
   python -m apt_scrape.cli search \
     --city milano --area bicocca --source immobiliare \
     --max-pages 1 --include-details \
     --analyse --push-notion -o test_result.json
   ```
4. Confirm `test_result.json` contains `ai_score`, `ai_stars`, `ai_verdict`, `ai_reason`, `notion_page_url` fields on each listing
5. Open Notion Apartments DB — verify new pages were created with correct field mapping and star scores
6. Run the same command again — verify listings are skipped (dedup by URL)

### Push subcommand test

```bash
python -m apt_scrape.cli push test_result.json --push-notion
```

Verify pages already in Notion are skipped; new JSON includes `notion_skipped=True`.

### Analysis-only test

```bash
python -m apt_scrape.cli push test_result.json --analyse
```

Verify `ai_*` fields updated without touching Notion.
