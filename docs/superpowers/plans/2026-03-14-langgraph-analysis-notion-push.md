# LangGraph Analysis + Notion Push Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-listing AI scoring via a LangGraph agent (OpenRouter) and automatic ingestion into a Notion Apartments database, both exposed as CLI flags on the existing `search` command plus a new `push` subcommand.

**Architecture:** Two new independent modules (`analysis.py`, `notion_push.py`) are integrated into the existing `cli.py` as optional post-processing steps. The `search` command gains `--analyse` and `--push-notion` flags; a new `push` subcommand post-processes existing JSON files. Each listing dict is stamped with `_area`/`_city` before being handed off to either module.

**Tech Stack:** `langgraph>=0.2`, `langchain-openai>=0.2`, `langchain-core>=0.3`, `notion-client>=2.2`, OpenRouter API, Notion API v1.

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `apt_scrape/analysis.py` | LangGraph agent — scores listings 0–100 against `preferences.txt` |
| Create | `apt_scrape/notion_push.py` | Notion API client — maps listings → Apartments DB pages |
| Create | `preferences.txt` | User's plain-text apartment preferences (project root) |
| Create | `tests/test_analysis.py` | Unit tests for analysis module |
| Create | `tests/test_notion_push.py` | Unit tests for notion_push module |
| Modify | `apt_scrape/cli.py` | Add `--analyse`, `--push-notion` to `search`; add `push` subcommand |
| Create | `pytest.ini` | pytest-asyncio auto mode config |
| Modify | `requirements.txt` | Add 5 new dependencies (incl. pytest-asyncio) |

---

## Chunk 1: Dependencies + analysis.py

### Task 1: Add dependencies

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: Add new dependencies**

Open `requirements.txt` and append these five lines:

```
langgraph>=0.2
langchain-openai>=0.2
langchain-core>=0.3
notion-client>=2.2
pytest-asyncio>=0.23
```

- [ ] **Step 2: Install them**

```bash
pip install "langgraph>=0.2" "langchain-openai>=0.2" "langchain-core>=0.3" "notion-client>=2.2" "pytest-asyncio>=0.23"
```

Expected: all packages install without error.

- [ ] **Step 3: Create pytest.ini to enable asyncio auto mode**

Create `pytest.ini` at the project root:

```ini
[pytest]
asyncio_mode = auto
```

This is required so `@pytest.mark.asyncio` tests are actually awaited by the test runner. Without it, async tests silently pass without executing.

- [ ] **Step 4: Commit**

```bash
git add requirements.txt pytest.ini
git commit -m "feat: add langgraph, langchain-openai, langchain-core, notion-client, pytest-asyncio deps"
```

---

### Task 2: Write failing tests for analysis.py

**Files:**
- Create: `tests/test_analysis.py`

The tests mock the LangGraph compiled graph so no real API calls are made.

- [ ] **Step 1: Create the test file**

```python
"""Tests for apt_scrape.analysis — LangGraph listing scorer."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Minimal listing dict (detail-enriched)
LISTING = {
    "title": "Bilocale luminoso",
    "price": "€ 900/mese",
    "sqm": "55 m²",
    "rooms": "2 locali",
    "address": "Milano, Bicocca",
    "detail": {
        "title": "Bilocale luminoso con balcone",
        "size": "55 m²",
        "floor": "3",
    },
    "detail_address": "Via Tal dei Tali 10, Bicocca, Milano",
    "detail_description": "Appartamento luminoso con balcone e vista verde.",
    "detail_features": {"Riscaldamento": "autonomo", "Piano": "3"},
    "detail_costs": {"Spese condominiali": "50€/mese"},
    "detail_energy_class": "C",
}


def test_score_to_stars():
    """score_to_stars() maps 0–100 integers to emoji strings."""
    from apt_scrape.analysis import score_to_stars

    assert score_to_stars(0) == "⭐"
    assert score_to_stars(19) == "⭐"
    assert score_to_stars(20) == "⭐⭐"
    assert score_to_stars(39) == "⭐⭐"
    assert score_to_stars(40) == "⭐⭐⭐"
    assert score_to_stars(59) == "⭐⭐⭐"
    assert score_to_stars(60) == "⭐⭐⭐⭐"
    assert score_to_stars(79) == "⭐⭐⭐⭐"
    assert score_to_stars(80) == "⭐⭐⭐⭐⭐"
    assert score_to_stars(100) == "⭐⭐⭐⭐⭐"


def test_format_listing_context_includes_key_fields():
    """_format_listing_context() returns a string containing all key fields."""
    from apt_scrape.analysis import _format_listing_context

    ctx = _format_listing_context(LISTING)
    assert "Bilocale luminoso con balcone" in ctx  # detail.title preferred
    assert "900" in ctx                             # price
    assert "55" in ctx                              # size
    assert "3 locali" in ctx or "2 locali" in ctx   # rooms
    assert "Bicocca" in ctx                          # address
    assert "luminoso con balcone" in ctx             # full description, not truncated
    assert "autonomo" in ctx                         # features
    assert "50€/mese" in ctx                         # costs
    assert "C" in ctx                                # energy class


@pytest.mark.asyncio
async def test_analyse_listings_adds_ai_fields():
    """analyse_listings() stamps ai_score, ai_stars, ai_verdict, ai_reason onto each listing."""
    from apt_scrape.analysis import AnalysisResult, analyse_listings

    fake_result = AnalysisResult(score=72, verdict="Good match", reason="Has balcony and good size.")

    # Patch the compiled LangGraph app invoke
    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.return_value = {"result": fake_result}
        mock_get_graph.return_value = mock_app

        listings = [dict(LISTING), dict(LISTING)]
        await analyse_listings(listings, preferences="I want a bright apartment.")

    for listing in listings:
        assert listing["ai_score"] == 72
        assert listing["ai_stars"] == "⭐⭐⭐⭐"
        assert listing["ai_verdict"] == "Good match"
        assert listing["ai_reason"] == "Has balcony and good size."


@pytest.mark.asyncio
async def test_analyse_listings_handles_error_gracefully():
    """analyse_listings() falls back to score=0/Error when LLM raises."""
    from apt_scrape.analysis import analyse_listings

    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = Exception("network error")
        mock_get_graph.return_value = mock_app

        listings = [dict(LISTING)]
        await analyse_listings(listings, preferences="I want a bright apartment.")

    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    assert "network error" in listings[0]["ai_reason"]


def test_load_preferences_from_file(tmp_path):
    """load_preferences() reads a plain-text file and returns its content."""
    from apt_scrape.analysis import load_preferences

    prefs_file = tmp_path / "preferences.txt"
    prefs_file.write_text("I want a balcony.\nNo ground floor.", encoding="utf-8")

    content = load_preferences(str(prefs_file))
    assert "balcony" in content
    assert "ground floor" in content


def test_load_preferences_missing_file_raises():
    """load_preferences() raises FileNotFoundError for missing files."""
    from apt_scrape.analysis import load_preferences

    with pytest.raises(FileNotFoundError):
        load_preferences("/nonexistent/path/preferences.txt")
```

- [ ] **Step 2: Run tests — verify they all fail with ImportError**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m pytest tests/test_analysis.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'apt_scrape.analysis'`

---

### Task 3: Implement analysis.py

**Files:**
- Create: `apt_scrape/analysis.py`

- [ ] **Step 1: Create the module**

```python
"""apt_scrape.analysis — LangGraph agent for per-listing AI scoring.

Scores each listing dict against a plain-text preferences file using a
single-node LangGraph StateGraph backed by OpenRouter. The graph is
designed with a single node now but structured for future extension
(e.g. retry-on-low-confidence, web-lookup nodes).

Required env vars:
    OPENROUTER_API_KEY  — OpenRouter API key
    OPENROUTER_MODEL    — OpenRouter model slug (default: google/gemini-3.1-flash-lite-preview)
    ANALYSIS_CONCURRENCY — max parallel LLM calls (default: 5)
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import TypedDict

import click
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Structured output model
# ---------------------------------------------------------------------------


class AnalysisResult(BaseModel):
    score: int      # 0–100
    verdict: str    # e.g. "Strong match", "Skip", "Potential"
    reason: str     # 1–2 sentence explanation


# ---------------------------------------------------------------------------
# Graph state
# ---------------------------------------------------------------------------


class AnalysisState(TypedDict):
    listing: dict
    preferences: str
    result: AnalysisResult | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def score_to_stars(score: int) -> str:
    """Map a 0–100 integer score to a star-emoji string."""
    if score < 20:
        return "⭐"
    if score < 40:
        return "⭐⭐"
    if score < 60:
        return "⭐⭐⭐"
    if score < 80:
        return "⭐⭐⭐⭐"
    return "⭐⭐⭐⭐⭐"


def load_preferences(path: str | None = None) -> str:
    """Load preferences from *path* (or PREFERENCES_FILE env var, or preferences.txt).

    Raises:
        FileNotFoundError: if the resolved path does not exist.
    """
    resolved = path or os.environ.get("PREFERENCES_FILE") or "preferences.txt"
    p = Path(resolved)
    if not p.exists():
        raise FileNotFoundError(f"Preferences file not found: {resolved}")
    return p.read_text(encoding="utf-8").strip()


def _format_listing_context(listing: dict) -> str:
    """Format key listing fields into a structured prompt context string."""
    detail = listing.get("detail") or {}
    title = detail.get("title") or listing.get("title", "")
    size = detail.get("size") or listing.get("sqm", "")
    floor = detail.get("floor", "")
    price = listing.get("price", "")
    rooms = listing.get("rooms", "")
    address = listing.get("detail_address") or listing.get("address", "")
    description = listing.get("detail_description", "")
    features = listing.get("detail_features") or {}
    costs = listing.get("detail_costs") or {}
    energy = listing.get("detail_energy_class", "")

    features_str = "\n".join(f"  {k}: {v}" for k, v in features.items()) if features else "  (none)"
    costs_str = "\n".join(f"  {k}: {v}" for k, v in costs.items()) if costs else "  (none)"

    return f"""Apartment: {title}
Price: {price}
Size: {size}
Rooms: {rooms}
Floor: {floor}
Address: {address}
Energy class: {energy}

Description:
{description}

Features:
{features_str}

Costs:
{costs_str}"""


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def _make_llm() -> ChatOpenAI:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL", "google/gemini-3.1-flash-lite-preview")
    return ChatOpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        model=model,
    )


# Module-level LLM instance (created lazily on first use via _get_llm())
_llm_instance: ChatOpenAI | None = None


def _get_llm() -> ChatOpenAI:
    """Return a shared LLM instance, creating it on first call."""
    global _llm_instance
    if _llm_instance is None:
        _llm_instance = _make_llm()
    return _llm_instance


async def _analyse_node(state: AnalysisState) -> AnalysisState:
    """Single graph node: score a listing against preferences."""
    llm = _get_llm()
    structured_llm = llm.with_structured_output(AnalysisResult)

    system_prompt = (
        "You are an apartment-hunting assistant. "
        "Given a user's preferences and an apartment listing, score the listing "
        "from 0 (terrible fit) to 100 (perfect fit) and give a short verdict and reason.\n\n"
        f"USER PREFERENCES:\n{state['preferences']}"
    )
    human_prompt = f"LISTING:\n{_format_listing_context(state['listing'])}"

    try:
        result: AnalysisResult = await structured_llm.ainvoke(
            [{"role": "system", "content": system_prompt},
             {"role": "user", "content": human_prompt}]
        )
    except Exception:
        # Fallback: ask for raw JSON block
        fallback_prompt = (
            system_prompt
            + "\n\nRespond ONLY with a JSON object: "
              '{"score": <int 0-100>, "verdict": "<short label>", "reason": "<1-2 sentences>"}'
        )
        try:
            raw_response = await _get_llm().ainvoke(
                [{"role": "system", "content": fallback_prompt},
                 {"role": "user", "content": human_prompt}]
            )
            text = raw_response.content if hasattr(raw_response, "content") else str(raw_response)
            start = text.find("{")
            end = text.rfind("}") + 1
            data = json.loads(text[start:end])
            result = AnalysisResult(**data)
        except Exception as e2:
            result = AnalysisResult(score=0, verdict="Error", reason=str(e2))

    return {**state, "result": result}


# ---------------------------------------------------------------------------
# Compiled graph (cached singleton)
# ---------------------------------------------------------------------------

_graph_instance = None


def _get_graph():
    global _graph_instance
    if _graph_instance is None:
        builder = StateGraph(AnalysisState)
        builder.add_node("analyse_listing", _analyse_node)
        builder.add_edge(START, "analyse_listing")
        builder.add_edge("analyse_listing", END)
        _graph_instance = builder.compile()
    return _graph_instance


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def analyse_listings(listings: list[dict], preferences: str) -> None:
    """Score each listing in-place against *preferences*.

    Adds ai_score, ai_stars, ai_verdict, ai_reason to each listing dict.
    Runs with bounded concurrency (ANALYSIS_CONCURRENCY env var, default 5).
    """
    concurrency = int(os.environ.get("ANALYSIS_CONCURRENCY", "5"))
    semaphore = asyncio.Semaphore(concurrency)
    graph = _get_graph()

    async def _score_one(listing: dict) -> None:
        async with semaphore:
            try:
                output = await graph.ainvoke(
                    {"listing": listing, "preferences": preferences, "result": None}
                )
                result: AnalysisResult = output["result"]
            except Exception as e:
                result = AnalysisResult(score=0, verdict="Error", reason=str(e))

            listing["ai_score"] = result.score
            listing["ai_stars"] = score_to_stars(result.score)
            listing["ai_verdict"] = result.verdict
            listing["ai_reason"] = result.reason

    total = len(listings)
    click.echo(f"Analysing {total} listings with AI...", err=True)
    await asyncio.gather(*(_score_one(l) for l in listings))
    click.echo(f"Analysis complete.", err=True)
```

- [ ] **Step 2: Run the tests**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m pytest tests/test_analysis.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add apt_scrape/analysis.py tests/test_analysis.py
git commit -m "feat: add LangGraph listing analysis agent (analysis.py)"
```

---

### Task 4: Create preferences.txt

**Files:**
- Create: `preferences.txt` (project root)

- [ ] **Step 1: Create the file**

```
I am looking for a 2-3 bedroom apartment to rent in Milan.

MUST HAVE:
- At least 60 sqm
- Private outdoor space (balcony, terrace, or garden)
- Heating included or autonomous gas heating
- Available by June 2025

NICE TO HAVE:
- Bright / south-facing
- Elevator
- Close to metro (≤10 min walk)
- Furnished or semi-furnished

DEAL BREAKERS:
- Ground floor with no garden access
- Shared bathroom
- Price above €1,400/month including fees
```

- [ ] **Step 2: Commit**

```bash
git add preferences.txt
git commit -m "feat: add initial preferences.txt for AI listing analysis"
```

---

## Chunk 2: notion_push.py

### Task 5: Write failing tests for notion_push.py

**Files:**
- Create: `tests/test_notion_push.py`

All Notion API calls are mocked — no real network calls.

- [ ] **Step 1: Create the test file**

```python
"""Tests for apt_scrape.notion_push — Notion Apartments DB ingestion."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
    "detail_address": "Via Tal dei Tali 10, Bicocca, Milano",
    "detail_agency": "Agenzia Rossi",
    "detail_energy_class": "C",
    "ai_score": 72,
    "ai_stars": "⭐⭐⭐⭐",
    "ai_verdict": "Good match",
    "ai_reason": "Has balcony and good size.",
    "_area": "bicocca",
    "_city": "milano",
}


def test_parse_price_numeric():
    """_parse_price_numeric() extracts the first integer from a price string."""
    from apt_scrape.notion_push import _parse_price_numeric

    assert _parse_price_numeric("€ 1.200/mese") == 1200.0
    assert _parse_price_numeric("900 €/mese") == 900.0
    assert _parse_price_numeric("€ 1,500") == 1500.0
    assert _parse_price_numeric("non disponibile") is None
    assert _parse_price_numeric("") is None


def test_parse_sqm_numeric():
    """_parse_sqm_numeric() extracts the numeric size from a sqm string."""
    from apt_scrape.notion_push import _parse_sqm_numeric

    assert _parse_sqm_numeric("65 m²") == 65.0
    assert _parse_sqm_numeric("120m²") == 120.0
    assert _parse_sqm_numeric("n.d.") is None
    assert _parse_sqm_numeric("") is None


def test_deslugify_area():
    """_deslugify_area() converts a hyphenated slug to a title-cased string."""
    from apt_scrape.notion_push import _deslugify_area

    assert _deslugify_area("bicocca") == "Bicocca"
    assert _deslugify_area("porta-venezia") == "Porta Venezia"
    assert _deslugify_area("niguarda-ca-granda") == "Niguarda Ca Granda"


@pytest.mark.asyncio
async def test_push_listings_creates_page_for_new_listing():
    """push_listings() creates a Notion page when listing URL is not already in DB."""
    from apt_scrape.notion_push import push_listings

    with patch("apt_scrape.notion_push.AsyncClient") as MockClient:
        client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        # _ensure_schema: retrieve returns empty properties dict
        client.databases.retrieve = AsyncMock(return_value={"properties": {}})
        client.databases.update = AsyncMock(return_value={})
        # Dedup: new listing; area match found; agency match found
        client.databases.query = AsyncMock(side_effect=[
            {"results": []},                         # dedup: no existing page
            {"results": [{"id": "area-page-id"}]},   # area lookup
            {"results": [{"id": "agency-page-id"}]}, # agency lookup
        ])
        client.pages.create = AsyncMock(return_value={
            "id": "new-page-id",
            "url": "https://www.notion.so/new-page-id",
        })

        listings = [dict(LISTING)]
        await push_listings(listings)

    assert listings[0]["notion_page_id"] == "new-page-id"
    assert listings[0]["notion_skipped"] is False
    client.pages.create.assert_called_once()


@pytest.mark.asyncio
async def test_push_listings_skips_duplicate():
    """push_listings() skips a listing whose URL already exists in Notion."""
    from apt_scrape.notion_push import push_listings

    with patch("apt_scrape.notion_push.AsyncClient") as MockClient:
        client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        client.databases.retrieve = AsyncMock(return_value={"properties": {}})
        client.databases.update = AsyncMock(return_value={})
        # Dedup query returns an existing page
        client.databases.query = AsyncMock(return_value={
            "results": [{"id": "existing-id", "url": "https://www.notion.so/existing-id"}]
        })

        listings = [dict(LISTING)]
        await push_listings(listings)

    assert listings[0]["notion_skipped"] is True
    assert listings[0].get("notion_page_id") == "existing-id"


@pytest.mark.asyncio
async def test_push_listings_creates_agency_when_missing():
    """push_listings() creates a new Agency page when agency is not found."""
    from apt_scrape.notion_push import push_listings

    with patch("apt_scrape.notion_push.AsyncClient") as MockClient:
        client = AsyncMock()
        MockClient.return_value.__aenter__ = AsyncMock(return_value=client)
        MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

        client.databases.retrieve = AsyncMock(return_value={"properties": {}})
        client.databases.update = AsyncMock(return_value={})
        # Dedup: new listing; area: no match; agency: no match
        client.databases.query = AsyncMock(side_effect=[
            {"results": []},   # dedup
            {"results": []},   # area lookup (no match)
            {"results": []},   # agency lookup (no match)
        ])
        client.pages.create = AsyncMock(side_effect=[
            {"id": "new-agency-id", "url": "https://www.notion.so/new-agency-id"},  # agency
            {"id": "new-apt-id", "url": "https://www.notion.so/new-apt-id"},         # apartment
        ])

        listings = [dict(LISTING)]
        await push_listings(listings)

    # Two pages created: agency first, then apartment
    assert client.pages.create.call_count == 2
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m pytest tests/test_notion_push.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'apt_scrape.notion_push'`

---

### Task 6: Implement notion_push.py

**Files:**
- Create: `apt_scrape/notion_push.py`

- [ ] **Step 1: Create the module**

```python
"""apt_scrape.notion_push — Push scraped listings into a Notion Apartments database.

Creates pages in the Apartments DB with relational links to Areas and Agencies.
Deduplicates by Listing URL. Adds new schema properties on first run via
_ensure_schema().

Required env vars:
    NOTION_API_KEY              — Notion integration token
    NOTION_APARTMENTS_DB_ID     — Apartments database ID
    NOTION_AREAS_DB_ID          — Areas database ID
    NOTION_AGENCIES_DB_ID       — Agencies database ID
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

import click
from notion_client import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_price_numeric(price_str: str) -> Optional[float]:
    """Extract the first numeric value from a price string (handles dots/commas as thousands sep)."""
    if not price_str:
        return None
    # Remove thousands separators (. or ,) then find digits
    cleaned = re.sub(r"[.,](?=\d{3})", "", price_str)
    m = re.search(r"(\d+(?:[.,]\d+)?)", cleaned)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_sqm_numeric(sqm_str: str) -> Optional[float]:
    """Extract the numeric value from a sqm string like '65 m²'."""
    if not sqm_str:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)", sqm_str)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _deslugify_area(slug: str) -> str:
    """Convert 'porta-venezia' → 'Porta Venezia'."""
    return " ".join(word.capitalize() for word in slug.split("-"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Schema setup
# ---------------------------------------------------------------------------

_NEW_PROPERTIES = {
    "Source": {"select": {}},
    "AI Score": {"number": {"format": "number"}},
    "AI Reason": {"rich_text": {}},
    "Energy Class": {"select": {}},
    "Scraped At": {"date": {}},
}


async def _ensure_schema(client: AsyncClient, db_id: str) -> None:
    """Add new properties to the Apartments DB if they don't already exist."""
    db = await client.databases.retrieve(database_id=db_id)
    existing = set(db.get("properties", {}).keys())
    missing = {k: v for k, v in _NEW_PROPERTIES.items() if k not in existing}
    if missing:
        await client.databases.update(database_id=db_id, properties=missing)
        click.echo(f"Added {len(missing)} new properties to Apartments DB: {list(missing)}", err=True)


# ---------------------------------------------------------------------------
# Relation lookups
# ---------------------------------------------------------------------------


async def _find_area_page_id(
    client: AsyncClient,
    areas_db_id: str,
    area_slug: str,
    cache: dict,
) -> Optional[str]:
    """Return the Notion page ID for the given area slug, or None."""
    if area_slug in cache:
        return cache[area_slug]
    area_name = _deslugify_area(area_slug)
    resp = await client.databases.query(
        database_id=areas_db_id,
        filter={"property": "Area Name", "title": {"equals": area_name}},
    )
    page_id = resp["results"][0]["id"] if resp["results"] else None
    if not page_id:
        click.echo(f"  [warn] No Areas page found for '{area_name}'", err=True)
    cache[area_slug] = page_id
    return page_id


async def _find_or_create_agency_page_id(
    client: AsyncClient,
    agencies_db_id: str,
    agency_name: str,
    cache: dict,
) -> Optional[str]:
    """Return the Notion page ID for the agency, creating it if necessary."""
    if not agency_name:
        return None
    if agency_name in cache:
        return cache[agency_name]
    resp = await client.databases.query(
        database_id=agencies_db_id,
        filter={"property": "Agency Name", "title": {"equals": agency_name}},
    )
    if resp["results"]:
        page_id = resp["results"][0]["id"]
    else:
        new_page = await client.pages.create(
            parent={"database_id": agencies_db_id},
            properties={
                "Agency Name": {"title": [{"text": {"content": agency_name}}]},
                "Status": {"select": {"name": "⚪ Not Yet Contacted"}},
            },
        )
        page_id = new_page["id"]
        click.echo(f"  Created new Agency page: {agency_name}", err=True)
    cache[agency_name] = page_id
    return page_id


async def _is_duplicate(client: AsyncClient, apartments_db_id: str, listing_url: str) -> Optional[str]:
    """Return existing page ID if listing URL already in DB, else None."""
    resp = await client.databases.query(
        database_id=apartments_db_id,
        filter={"property": "Listing URL", "url": {"equals": listing_url}},
    )
    if resp["results"]:
        return resp["results"][0]["id"]
    return None


# ---------------------------------------------------------------------------
# Property builder
# ---------------------------------------------------------------------------


def _build_properties(listing: dict, area_page_id: Optional[str], agency_page_id: Optional[str]) -> dict:
    """Build the Notion page properties dict from a listing dict."""
    detail = listing.get("detail") or {}

    title = detail.get("title") or listing.get("title") or "Untitled"
    price = _parse_price_numeric(listing.get("price", ""))
    size_str = detail.get("size") or listing.get("sqm", "")
    size = _parse_sqm_numeric(size_str)
    floor_val = detail.get("floor", "")
    address = listing.get("detail_address") or listing.get("address", "")
    rooms = listing.get("rooms", "")
    url = listing.get("url", "")
    source = listing.get("source", "")
    energy = listing.get("detail_energy_class", "")

    props: dict = {
        "Apartment": {"title": [{"text": {"content": title}}]},
        "Status": {"select": {"name": "👀 To Visit"}},
        "Listing URL": {"url": url} if url else {"url": None},
        "Scraped At": {"date": {"start": _now_iso()}},
    }

    if price is not None:
        props["Rent (€/mo)"] = {"number": price}
    if size is not None:
        props["Size (m²)"] = {"number": size}
    if rooms:
        props["Rooms"] = {"rich_text": [{"text": {"content": rooms}}]}
    if floor_val:
        props["Floor"] = {"rich_text": [{"text": {"content": floor_val}}]}
    if address:
        props["Address"] = {"rich_text": [{"text": {"content": address}}]}
    if source:
        props["Source"] = {"select": {"name": source}}
    if energy:
        props["Energy Class"] = {"select": {"name": energy}}

    # AI analysis fields (only if present)
    ai_stars = listing.get("ai_stars")
    if ai_stars:
        props["Score"] = {"select": {"name": ai_stars}}
    ai_score = listing.get("ai_score")
    if ai_score is not None:
        props["AI Score"] = {"number": ai_score}
    ai_verdict = listing.get("ai_verdict", "")
    ai_reason = listing.get("ai_reason", "")
    if ai_verdict or ai_reason:
        notes = f"{ai_verdict}: {ai_reason}" if ai_verdict else ai_reason
        props["Notes"] = {"rich_text": [{"text": {"content": notes[:2000]}}]}
    if ai_reason:
        props["AI Reason"] = {"rich_text": [{"text": {"content": ai_reason[:2000]}}]}

    # Relations
    if area_page_id:
        props["Area"] = {"relation": [{"id": area_page_id}]}
    if agency_page_id:
        props["Agency"] = {"relation": [{"id": agency_page_id}]}

    return props


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def push_listings(listings: list[dict]) -> None:
    """Create Notion Apartments pages for each listing in-place.

    Adds notion_page_id, notion_page_url, notion_skipped to each listing dict.
    Reads DB IDs from env vars. Deduplicates by Listing URL.
    """
    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    areas_db_id = os.environ.get("NOTION_AREAS_DB_ID", "")
    agencies_db_id = os.environ.get("NOTION_AGENCIES_DB_ID", "")

    if not api_key or not apartments_db_id:
        raise ValueError("NOTION_API_KEY and NOTION_APARTMENTS_DB_ID must be set.")

    area_cache: dict[str, Optional[str]] = {}
    agency_cache: dict[str, Optional[str]] = {}

    async with AsyncClient(auth=api_key) as client:
        await _ensure_schema(client, apartments_db_id)

        created = skipped = 0
        for listing in listings:
            url = listing.get("url", "")
            existing_id = await _is_duplicate(client, apartments_db_id, url)

            if existing_id:
                listing["notion_skipped"] = True
                listing["notion_page_id"] = existing_id
                listing["notion_page_url"] = f"https://www.notion.so/{existing_id.replace('-', '')}"
                skipped += 1
                continue

            area_slug = listing.get("_area", "")
            area_page_id = None
            if area_slug and areas_db_id:
                area_page_id = await _find_area_page_id(client, areas_db_id, area_slug, area_cache)

            agency_name = listing.get("detail_agency", "")
            agency_page_id = None
            if agency_name and agencies_db_id:
                agency_page_id = await _find_or_create_agency_page_id(
                    client, agencies_db_id, agency_name, agency_cache
                )

            props = _build_properties(listing, area_page_id, agency_page_id)
            page = await client.pages.create(
                parent={"database_id": apartments_db_id},
                properties=props,
            )
            listing["notion_page_id"] = page["id"]
            listing["notion_page_url"] = page.get("url", "")
            listing["notion_skipped"] = False
            created += 1

        click.echo(f"Notion push: {created} created, {skipped} skipped.", err=True)
```

- [ ] **Step 2: Run the tests**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m pytest tests/test_notion_push.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add apt_scrape/notion_push.py tests/test_notion_push.py
git commit -m "feat: add Notion push module (notion_push.py)"
```

---

## Chunk 3: CLI Integration

### Task 7: Write failing tests for the push subcommand and new search flags

**Files:**
- Create: `tests/test_cli_push.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for the new CLI push subcommand and --analyse / --push-notion flags on search."""
import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from apt_scrape.cli import cli


ENVELOPE = {
    "count": 1,
    "city": "milano",
    "area": "bicocca",
    "source": "Immobiliare.it",
    "listings": [
        {
            "title": "Bilocale",
            "url": "https://www.immobiliare.it/annunci/99/",
            "price": "€ 900/mese",
            "sqm": "55 m²",
            "rooms": "2 locali",
            "address": "Bicocca",
            "source": "Immobiliare.it",
        }
    ],
}


def _write_json(tmp_path, data):
    p = tmp_path / "result.json"
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(p)


def test_push_subcommand_exists():
    """The 'push' subcommand is registered on the CLI."""
    runner = CliRunner()
    result = runner.invoke(cli, ["push", "--help"])
    assert result.exit_code == 0
    assert "push" in result.output.lower() or "json" in result.output.lower()


def test_push_injects_area_and_city_into_listings(tmp_path):
    """push subcommand stamps _area and _city onto each listing before processing."""
    json_path = _write_json(tmp_path, ENVELOPE)

    # Because analysis and notion_push are lazy-imported inside _run_push,
    # we patch their module-level symbols directly.
    with patch("apt_scrape.analysis.analyse_listings", new_callable=AsyncMock) as mock_analyse, \
         patch("apt_scrape.notion_push.push_listings", new_callable=AsyncMock) as mock_push, \
         patch("apt_scrape.analysis.load_preferences", return_value="I want a nice place."):

        runner = CliRunner()
        runner.invoke(cli, ["push", json_path, "--analyse", "--push-notion"],
                      env={
                          "OPENROUTER_API_KEY": "fake",
                          "NOTION_API_KEY": "fake",
                          "NOTION_APARTMENTS_DB_ID": "fake-db-id",
                      })

    call_args = mock_analyse.call_args
    listings_passed = call_args[0][0] if call_args else []
    for listing in listings_passed:
        assert listing.get("_area") == "bicocca"
        assert listing.get("_city") == "milano"


def test_push_writes_updated_json_atomically(tmp_path):
    """push subcommand writes back updated JSON (with ai_* fields) to the original file."""
    envelope = dict(ENVELOPE)
    json_path = _write_json(tmp_path, envelope)

    async def fake_analyse(listings, preferences):
        for l in listings:
            l["ai_score"] = 75
            l["ai_stars"] = "⭐⭐⭐⭐"
            l["ai_verdict"] = "Good"
            l["ai_reason"] = "Nice place."

    with patch("apt_scrape.analysis.analyse_listings", side_effect=fake_analyse), \
         patch("apt_scrape.analysis.load_preferences", return_value="I want a nice place."):

        runner = CliRunner()
        runner.invoke(cli, ["push", json_path, "--analyse"],
                      env={"OPENROUTER_API_KEY": "fake"})

    updated = json.loads(Path(json_path).read_text(encoding="utf-8"))
    assert updated["listings"][0]["ai_score"] == 75
    assert updated["listings"][0]["ai_stars"] == "⭐⭐⭐⭐"


def test_search_command_accepts_analyse_flag():
    """--analyse flag is a valid option on the search command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["search", "--help"])
    assert "--analyse" in result.output


def test_search_command_accepts_push_notion_flag():
    """--push-notion flag is a valid option on the search command."""
    runner = CliRunner()
    result = runner.invoke(cli, ["search", "--help"])
    assert "--push-notion" in result.output
```

- [ ] **Step 2: Run tests — verify they fail**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m pytest tests/test_cli_push.py -v 2>&1 | head -30
```

Expected: tests fail because the `push` subcommand doesn't exist and the flags are missing.

---

### Task 8: Integrate into cli.py

**Files:**
- Modify: `apt_scrape/cli.py`

- [ ] **Step 1: Add imports at the top of cli.py**

Add `import os` to the standard library imports at the top of [cli.py](apt_scrape/cli.py) (it is not currently present). Place it after `import json`:

```python
import os
```

The `analyse_listings`, `load_preferences`, and `push_listings` symbols are imported **lazily inside each function** (not at module level) to avoid import failures if the optional dependencies are not installed. The lazy import lines will be added in the steps below where each function is modified.

- [ ] **Step 2: Add --analyse and --push-notion flags to the search command**

In [cli.py](apt_scrape/cli.py), add these two options after the `--table-max-rows` option (before `--output`):

```python
@click.option("--analyse", is_flag=True, help="Score each listing with AI against preferences.txt.")
@click.option("--push-notion", "push_notion", is_flag=True, help="Push listings to Notion Apartments DB.")
```

Add `analyse: bool` and `push_notion: bool` to the `search()` function signature, and pass them through to `_run_search()`.

In `_run_search()`, add the same two parameters to the signature and call site. Insert the following block **between the `enrich_post_dates(...)` call and the `return json.dumps(...)` call** (i.e., after post-date enrichment, before the JSON serialisation):

```python
        # Stamp area/city onto each listing for analysis and Notion push
        for listing in deduped:
            listing["_area"] = area_slug or ""
            listing["_city"] = city_slug

        if analyse and deduped:
            from apt_scrape.analysis import analyse_listings, load_preferences
            try:
                prefs = load_preferences()
            except FileNotFoundError as e:
                click.echo(f"[warn] {e} — skipping AI analysis.", err=True)
            else:
                await analyse_listings(deduped, prefs)

        if push_notion and deduped:
            from apt_scrape.notion_push import push_listings
            await push_listings(deduped)
```

- [ ] **Step 3: Add the push subcommand**

Add this new command after the `search` section in [cli.py](apt_scrape/cli.py) (before the `detail` section):

```python
# ---------------------------------------------------------------------------
# push
# ---------------------------------------------------------------------------


@cli.command("push")
@click.argument("json_file", type=click.Path(exists=True))
@click.option("--analyse", is_flag=True, help="Score each listing with AI against preferences.txt.")
@click.option("--push-notion", "push_notion", is_flag=True, help="Push listings to Notion Apartments DB.")
def push(json_file: str, analyse: bool, push_notion: bool) -> None:
    """Post-process an existing JSON result file: re-run analysis and/or push to Notion.

    JSON_FILE is the path to a previously saved search result JSON file.
    The file is updated in-place (atomically) with any new ai_* or notion_* fields.
    """
    asyncio.run(_run_push(json_file, analyse, push_notion))


async def _run_push(json_file: str, analyse: bool, push_notion: bool) -> None:
    """Async implementation of the push command."""
    import tempfile

    path = Path(json_file)
    envelope = json.loads(path.read_text(encoding="utf-8"))
    listings = envelope.get("listings", [])
    area_slug = envelope.get("area") or ""
    city_slug = envelope.get("city") or ""

    # Stamp area/city onto each listing
    for listing in listings:
        listing["_area"] = area_slug
        listing["_city"] = city_slug

    if analyse and listings:
        from apt_scrape.analysis import analyse_listings, load_preferences
        try:
            prefs = load_preferences()
        except FileNotFoundError as e:
            click.echo(f"[warn] {e} — skipping AI analysis.", err=True)
        else:
            await analyse_listings(listings, prefs)

    if push_notion and listings:
        from apt_scrape.notion_push import push_listings
        await push_listings(listings)

    # Atomic write back (write to .tmp then rename to avoid corruption on failure)
    envelope["listings"] = listings
    tmp_fd, tmp_path = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(envelope, f, indent=2, ensure_ascii=False)
        Path(tmp_path).replace(path)
        click.echo(f"Updated {json_file}", err=True)
    except Exception:
        os.unlink(tmp_path)
        raise
```

- [ ] **Step 4: Run all tests**

```bash
cd /Users/tarasivaniv/Downloads/apt_scrape && python -m pytest tests/ -v
```

Expected: all tests PASS. If `test_search_command_accepts_*` fail, double-check that the flags were added to the `search` command decorator.

- [ ] **Step 5: Smoke-test the help output**

```bash
python -m apt_scrape.cli search --help | grep -E "analyse|push-notion"
python -m apt_scrape.cli push --help
```

Expected: `--analyse` and `--push-notion` appear in search help; `push` help shows `JSON_FILE`, `--analyse`, `--push-notion`.

- [ ] **Step 6: Commit**

```bash
git add apt_scrape/cli.py tests/test_cli_push.py
git commit -m "feat: add --analyse, --push-notion to search and new push subcommand"
```

---

## Verification

### End-to-end test (requires real API keys)

Set env vars in `.env`:

```bash
OPENROUTER_API_KEY=...
OPENROUTER_MODEL=google/gemini-3.1-flash-lite-preview   # verify slug on openrouter.ai/models
NOTION_API_KEY=...
NOTION_APARTMENTS_DB_ID=0790f76c-2f79-4c89-9028-ba075db0490c
NOTION_AREAS_DB_ID=700f985e-a354-41da-80fc-79a666f10c49
NOTION_AGENCIES_DB_ID=26db1f66-8cc1-428a-bb71-3787038a8c7e
```

Run a small search:

```bash
python -m apt_scrape.cli search \
  --city milano --area bicocca --source immobiliare \
  --max-pages 1 --include-details \
  --analyse --push-notion \
  -o test_result.json
```

Verify:
1. `test_result.json` listings each have `ai_score`, `ai_stars`, `ai_verdict`, `ai_reason`, `notion_page_url`
2. Notion Apartments DB has new pages with correct field values and star scores
3. Re-run same command → listings show `notion_skipped: true` in output

Test push on existing file:

```bash
python -m apt_scrape.cli push test_result.json --push-notion
```

Verify all listings are skipped (already in Notion).

Test analysis-only:

```bash
python -m apt_scrape.cli push test_result.json --analyse
```

Verify `ai_*` fields updated in `test_result.json`, Notion untouched.
