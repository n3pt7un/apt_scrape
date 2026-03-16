# Testing Patterns

**Analysis Date:** 2026-03-16

## Test Framework

**Runner:**
- pytest [latest from requirements.txt]
- Config: `pytest.ini` located at `/Users/tarasivaniv/Downloads/apt_scrape/pytest.ini`

**Configuration:**
```ini
[pytest]
asyncio_mode = auto
```

**Assertion Library:**
- pytest's built-in assertions (no explicit assertion library installed)
- `unittest.mock` for mocking

**Run Commands:**
```bash
pytest tests/                          # Run all tests
pytest tests/ -v                       # Verbose output
pytest tests/test_analysis.py          # Run specific test file
pytest -k "test_score_to_stars"        # Run tests matching pattern
pytest --asyncio-mode=auto             # Async test mode
```

## Test File Organization

**Location:**
- Co-located with test-specific fixture files
- Top-level tests directory: `/Users/tarasivaniv/Downloads/apt_scrape/tests/`
- Backend tests sub-directory: `tests/backend/`
- Test files do NOT co-locate with source files

**Naming:**
- Test modules: `test_*.py` (pytest convention)
- Test functions: `test_<function_or_feature>_<behavior>()`
- Test classes: Not used; flat function organization preferred

**Structure:**
```
tests/
├── __init__.py                          # Empty marker file
├── test_analysis.py                     # Tests for apt_scrape.analysis
├── test_cli_push.py                     # Tests for CLI push subcommand
├── test_immobiliare.py                  # Integration tests for Immobiliare adapter
├── test_notion_push.py                  # Tests for apt_scrape.notion_push
└── backend/
    ├── __init__.py
    ├── test_configs.py                  # Backend config router tests
    ├── test_db.py                       # Database model tests
    ├── test_listings.py                 # Backend listings router tests
    ├── test_preferences.py              # Backend preferences router tests
    └── test_sites.py                    # Backend sites router tests
```

## Test Structure

**Suite Organization:**
```python
# Example from test_analysis.py

# 1. Module-level docstring
"""Tests for apt_scrape.analysis — LangGraph listing scorer."""

# 2. Imports
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

# 3. Test fixtures/constants at module level
LISTING = {
    "title": "Bilocale luminoso",
    "price": "€ 900/mese",
    "sqm": "55 m²",
    # ...
}

# 4. Test functions
def test_score_to_stars():
    """score_to_stars() maps 0–100 integers to emoji strings."""
    from apt_scrape.analysis import score_to_stars
    assert score_to_stars(0) == "⭐"
    # ...

@pytest.mark.asyncio
async def test_analyse_listings_adds_ai_fields():
    """analyse_listings() stamps ai_score, ai_stars... onto each listing."""
    # ...
```

**Patterns:**
- Imports done at test function level when testing imports: `from apt_scrape.analysis import score_to_stars`
- Module-level test data constants (LISTING, ENVELOPE) for re-use across tests
- No setup/teardown methods; fixtures preferred (when used)
- Async tests marked with `@pytest.mark.asyncio`

## Mocking

**Framework:**
- `unittest.mock.AsyncMock` for async functions
- `unittest.mock.MagicMock` for sync functions
- `unittest.mock.patch` as context manager

**Patterns:**
```python
# Example from test_analysis.py
with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
    mock_app = AsyncMock()
    mock_app.ainvoke.return_value = {"result": fake_result}
    mock_get_graph.return_value = mock_app

    listings = [dict(LISTING), dict(LISTING)]
    await analyse_listings(listings, preferences="I want a bright apartment.")

# Verify mocks were called appropriately
# No explicit assertions on mock.call_count; rely on side effects
```

**Side effects for fallback testing:**
```python
mock_app.ainvoke.side_effect = Exception("network error")
# Tests that exception handling logic works correctly
```

**What to Mock:**
- External services (LLMs, Notion API): `patch("apt_scrape.analysis._get_llm")`
- HTTP calls: `patch("httpx.AsyncClient")`
- Environment-dependent functions: `patch("apt_scrape.analysis.load_preferences")`
- File I/O (when appropriate): Use `tmp_path` fixture instead

**What NOT to Mock:**
- Core parsing logic: Test with real HTML or data samples
- Data structure manipulation: Use real dicts/dataclasses
- Simple helpers: `score_to_stars()`, `_parse_price_numeric()`
- Async semaphores/locks: Test with real concurrency if possible

## Fixtures and Factories

**Test Data:**
```python
# Example from test_notion_push.py
LISTING = {
    "title": "Bilocale luminoso",
    "url": "https://www.immobiliare.it/annunci/12345/",
    "price": "€ 900/mese",
    "sqm": "55 m²",
    "rooms": "2 locali",
    "address": "Milano, Bicocca",
    "source": "Immobiliare.it",
    "detail": {
        "title": "Bilocale luminoso con balcone",
        "size": "55 m²",
        "floor": "3",
    },
    "notion_fields": {
        "title": "Bilocale luminoso con balcone",
        "rent_per_month": 900.0,
        "size_sqm": 55.0,
        # ... complete mock listing structure
    },
}
```

**Factories:**
- No factory pattern used; module-level dicts modified via `dict(LISTING)` to create independent copies
- Test functions document their input requirements in docstrings

**Location:**
- Test data constants defined at module level in test files
- No separate `conftest.py` or fixtures file (minimal fixture usage)
- `tmp_path` fixture from pytest used for file I/O tests

## Coverage

**Requirements:**
- No enforced coverage threshold detected
- Coverage not configured in pytest.ini
- Tests focus on high-value functionality

**View Coverage:**
```bash
pytest --cov=apt_scrape tests/      # Generate coverage report (if pytest-cov installed)
pytest --cov=apt_scrape --cov-report=html tests/  # HTML report
```

## Test Types

**Unit Tests:**
- Scope: Individual functions/methods in isolation
- Approach: Mock external dependencies, test input→output transformation
- Examples: `test_score_to_stars()`, `test_parse_price_numeric()`, `test_deslugify_area()`
- No database, no network, no file I/O (except via tmp_path)

**Integration Tests:**
- Scope: Multiple components working together (but not full system)
- Approach: Real database (SQLite in-memory or temp), mocked external APIs
- Examples: `test_analyse_listings_adds_ai_fields()` (mocks LLM but tests full analysis flow)
- File I/O via `tmp_path` fixture: `test_load_preferences_from_file(tmp_path)`

**Live Integration Tests:**
- Scope: Full flow including browser automation and real site parsing
- Framework: Custom test runner in `test_immobiliare.py`
- Approach: Direct network calls (Immobiliare.it, etc.), no mocking
- Execution: Manual or separate CI step, exits early if no listings found
- Usage: `python tests/test_immobiliare.py` or `python tests/test_immobiliare.py --live-only`

**E2E Tests:**
- Framework: Not used for automated E2E; manual testing via CLI and Streamlit app
- Manual verification: Run scrape commands, verify outputs in Notion

## Common Patterns

**Async Testing:**
```python
@pytest.mark.asyncio
async def test_analyse_listings_adds_ai_fields():
    """Test async function that runs with mocked graph."""
    from apt_scrape.analysis import NotionApartmentFields, analyse_listings

    fake_result = NotionApartmentFields(...)

    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.return_value = {"result": fake_result}
        mock_get_graph.return_value = mock_app

        listings = [dict(LISTING), dict(LISTING)]
        await analyse_listings(listings, preferences="...")

    # Assertions on modified listings
    for listing in listings:
        assert listing["ai_score"] == 72
```

**Error Testing:**
```python
@pytest.mark.asyncio
async def test_analyse_listings_handles_error_gracefully():
    """Verify fallback behavior when LLM raises."""
    from apt_scrape.analysis import analyse_listings

    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = Exception("network error")
        mock_get_graph.return_value = mock_app

        listings = [dict(LISTING)]
        await analyse_listings(listings, preferences="...")

    # Verify graceful fallback
    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    assert "network error" in listings[0]["ai_reason"]
```

**File I/O Testing:**
```python
def test_load_preferences_from_file(tmp_path):
    """load_preferences() reads a plain-text file and returns its content."""
    from apt_scrape.analysis import load_preferences

    prefs_file = tmp_path / "preferences.txt"
    prefs_file.write_text("I want a balcony.\nNo ground floor.", encoding="utf-8")

    content = load_preferences(str(prefs_file))
    assert "balcony" in content
    assert "ground floor" in content
```

**CLI Testing:**
```python
def test_push_injects_area_and_city_into_listings(tmp_path):
    """push subcommand stamps _area and _city onto each listing."""
    from click.testing import CliRunner
    from apt_scrape.cli import cli

    json_path = _write_json(tmp_path, ENVELOPE)

    with patch("apt_scrape.analysis.analyse_listings", new_callable=AsyncMock) as mock_analyse:
        runner = CliRunner()
        runner.invoke(cli, ["push", json_path, "--analyse"],
                      env={"OPENROUTER_API_KEY": "fake"})

    call_args = mock_analyse.call_args
    listings_passed = call_args[0][0] if call_args else []
    for listing in listings_passed:
        assert listing.get("_area") == "bicocca"
```

## Test Data Patterns

**Minimal but Complete:**
- Test data includes all required fields for the function being tested
- Optional fields included only when testing optional behavior
- Nested structures (detail, notion_fields) included when parsing is tested

**Deterministic Values:**
- Use realistic but fixed values: "€ 900/mese", "55 m²", "2 locali"
- Test with Italian text: "Bicocca", "Via Tal dei Tali 10"
- Emoji and special characters included: "⭐⭐⭐⭐"

**Re-use via Copying:**
- `dict(LISTING)` creates independent copy for each test
- Lists modified in place via `listings = [dict(LISTING), dict(LISTING)]`
- No shared mutable state between tests
