# Coding Conventions

**Analysis Date:** 2026-03-16

## Naming Patterns

**Files:**
- Modules use lowercase with underscores: `analysis.py`, `notion_push.py`, `sites/base.py`
- Test files follow pytest convention: `test_analysis.py`, `test_notion_push.py`
- Backend routers grouped in `backend/routers/` directory: `configs.py`, `listings.py`, `preferences.py`, `jobs.py`, `sites.py`
- Frontend pages use numbered prefix: `1_Search_Configs.py`, `2_Monitor.py`, `3_Preferences.py` (Streamlit convention)

**Functions:**
- Standard camelCase-like snake_case: `analyse_listings()`, `parse_search()`, `build_search_url()`
- Private/internal functions prefixed with underscore: `_format_listing_context()`, `_parse_price_numeric()`, `_ensure_schema()`
- Helper functions follow descriptive names: `score_to_stars()`, `load_preferences()`, `extract_text()`
- Async functions use `async def`: `analyse_listings()`, `_analyse_node()`, `_geocode_address()`

**Variables:**
- Snake_case throughout: `listing_card`, `feature_texts`, `min_price`, `max_sqm`
- Type-hinted with modern Python syntax: `listings: list[dict]`, `filters: SearchFilters`, `config: SiteConfig`
- Constants in UPPER_SNAKE_CASE: `_NOMINATIM_URL`, `_NEW_PROPERTIES`, `DB_PATH`
- Module-level cache variables: `_geocode_cache`, `_llm_instance`, `_graph_instance`

**Types:**
- Custom types defined with `dataclass` or `TypedDict`: `SearchFilters`, `ListingSummary`, `ListingDetail`, `AnalysisState`
- Pydantic models for API/LLM output: `NotionApartmentFields`, `SearchConfig` (SQLModel)
- Type aliases explicitly documented: `ClassifyResult = tuple[str, str]`
- Union types use modern syntax: `Tag | None` instead of `Optional[Tag]`

## Code Style

**Formatting:**
- No explicit formatter configured (check for `.prettierrc` absent)
- Python follows PEP 8 conventions implicitly
- Line length appears to be ~100 characters (observed in most modules)
- Indentation: 4 spaces

**Linting:**
- No explicit eslint/flake8 config files detected
- Code appears to follow standard Python conventions
- Type hints are consistently used throughout the codebase

## Import Organization

**Order:**
1. Standard library imports: `asyncio`, `json`, `os`, `re`, `logging`, `datetime`
2. Third-party imports: `click`, `pydantic`, `langchain_openai`, `bs4`, `sqlmodel`, `fastapi`
3. Local imports: `from apt_scrape.X import Y`, `from backend.X import Y`

**Path Aliases:**
- No explicit path aliases configured
- Relative imports used within packages: `from .sites import SearchFilters`
- Absolute imports for cross-package: `from apt_scrape.sites import SearchFilters`, `from backend.db import create_db_and_tables`

**Special patterns:**
- Module-level imports sometimes deferred inside functions for lazy loading: `import yaml` inside `load_config_from_yaml()`
- Local module imports sometimes aliased to avoid conflicts: `import json as _json_mod` in `backend/routers/listings.py`

## Error Handling

**Patterns:**
- Broad exception catching with fallback behavior in LLM operations: `except Exception:` → fallback to JSON parsing
- Specific exception catching for expected failures: `except FileNotFoundError`, `except ValueError`
- Click library exceptions for CLI: `raise click.BadParameter()`, `raise click.UsageError()`
- HTTPException for API errors: `raise HTTPException(status_code=400, detail="...")`
- Graceful degradation in async operations: `try/except` with fallback result construction
- Exception messages captured and embedded in results: `ai_reason=str(e)` when LLM call fails

**Logging patterns:**
- Exceptions logged at WARNING level: `logger.warning("Failed to enrich detail for %s: %s", url, exc)`
- Info-level logging for progress: `logger.info("Enriching %d listings with detail...", total)`
- No exception re-raising after logging; failures soft-fail with default values

## Logging

**Framework:** Python's standard `logging` module

**Module-level setup:**
```python
import logging
logger = logging.getLogger(__name__)
```

**Patterns:**
- Central setup in `apt_scrape/server.py`: `logging.basicConfig(level=logging.INFO, ...)`
- Named loggers per module: `logging.getLogger("apt_scrape.server")`
- Click's error output via `click.echo(..., err=True)` for stderr messages
- Progress messages to stderr: `click.echo("Analysing 100 listings...", err=True)`
- Diagnostic logging with structured context: `logger.warning("DIAG [%s] 0 cards with selector %r", site_id, selector_list)`

## Comments

**When to Comment:**
- Module-level docstrings required: Every `.py` file starts with `"""Module description..."""`
- Class docstrings provided: `ListingSummary`, `SearchFilters` have full docstrings
- Function docstrings for public APIs: Required with Args, Returns, Raises sections
- Inline comments for non-obvious logic: Regex patterns, fallback behavior, workarounds
- Section dividers used for major logical groups: `# --------------- Helpers --------` style

**JSDoc/TSDoc:**
- Python docstrings follow standard format:
```python
def extract_text(element: Tag | None, default: str = "") -> str:
    """Safely extract stripped text from a BeautifulSoup element.

    Args:
        element: A ``Tag`` or ``None``.
        default: Value returned when *element* is ``None``.

    Returns:
        Stripped text content, or *default*.
    """
```
- Private functions have lighter docstrings
- Pydantic Field descriptions used for structured output: `Field(description="...")`

## Function Design

**Size:**
- Helper functions are intentionally short (5–15 lines): `_parse_price_numeric()`, `score_to_stars()`
- Parsing methods are medium-length (20–50 lines): `_parse_one_card()`, `parse_detail()`
- Complex orchestration methods longer (50–100 lines): `analyse_listings()`, `_analyse_node()`

**Parameters:**
- Dataclass objects preferred over multiple primitives: `def build_search_url(filters: SearchFilters)`
- Limited to 4–5 positional parameters; rest use dataclasses
- Optional parameters typed explicitly: `path: str | None = None`, `default: str = ""`

**Return Values:**
- Explicit return types always specified: `-> str`, `-> list[dict]`, `-> Optional[float]`
- Compound returns use dataclasses or dicts: `return ListingDetail(...)`
- Async functions return awaitable results: `async def _analyse_node(...) -> AnalysisState`
- Fallback/error values returned, never raised silently: `return None` for missing data, `ai_reason=str(e)` for errors

## Module Design

**Exports:**
- `__all__` lists defined explicitly: `__all__ = ["SiteAdapter", "SearchFilters", "ListingDetail", ...]`
- Public API surface intentionally minimal: `apt_scrape/__init__.py` delegates to submodules
- Re-exports documented in module docstrings

**Barrel Files:**
- `apt_scrape/sites/__init__.py` re-exports adapters and base types
- Backend routers registered via `app.include_router()` in `backend/main.py`
- Avoids deep nesting; top-level imports sufficient

## Patterns by Domain

**Web Scraping (apt_scrape/sites/):**
- Config-driven parsing via `SiteConfig` dataclass: CSS selectors stored in YAML, not hardcoded
- SelectorGroup pattern for fallback chains: Multiple selectors tried in order for resilience
- Per-adapter overrides: `SiteAdapter` subclass only overrides methods that differ from defaults
- BeautifulSoup + lxml parser throughout: `soup = BeautifulSoup(html, "lxml")`

**LLM/Analysis (apt_scrape/analysis.py):**
- LangGraph state machine pattern: Single node initially, structured for future extension
- Lazy initialization: `_get_llm()` creates singleton on first call, cached in `_llm_instance`
- Fallback parsing: Structured output attempted first, falls back to raw JSON extraction
- Concurrency controlled via Semaphore: `asyncio.Semaphore(concurrency)` with configurable limit

**Notion Integration (apt_scrape/notion_push.py):**
- Geocoding cache: `_geocode_cache` avoids duplicate HTTP requests
- Async client pattern: `AsyncClient` from `notion_client` and `httpx`
- Deduplication by URL: Schema ensures unique constraint on Listing URL field

**Backend APIs (backend/routers/):**
- FastAPI router pattern: Each domain (listings, configs, jobs) has its own router
- SQLModel for ORM: Single Session dependency injected via `Depends(get_session)`
- JSON serialization: `model.model_dump()` for SQLModel → dict conversion

**Frontend (frontend/):**
- Streamlit convention: Multi-page app with `pages/1_*.py`, `pages/2_*.py` naming
- Session state management: `st.session_state` for page-to-page communication
- Direct API calls: Frontend pages call backend endpoints directly via `httpx` or requests
