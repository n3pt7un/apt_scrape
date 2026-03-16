# Phase 03: LLM Scoring Observability - Research

**Researched:** 2026-03-16
**Domain:** Python exception handling, stdlib logging, unit testing with unittest.mock
**Confidence:** HIGH

## Summary

The LLM scoring module (`src/apt_scrape/analysis.py`) currently has two levels of silent failure. First, `_analyse_node` has a two-tier fallback: the outer `except Exception` block retries with a raw-JSON prompt, and the inner `except Exception as e2` creates a minimal error result. Neither level logs anything, neither distinguishes API failures (network, auth, HTTP errors from `langchain_openai`) from parse failures (JSON decode errors, `NotionApartmentFields` construction failures), and neither records the listing ID. Second, `analyse_listings._score_one` has its own `except Exception` that also silently produces a fallback result without logging.

The fix requires three coordinated changes: (1) introduce two custom exception classes (`LLMAPIError`, `LLMParseError`) to make failure modes distinguishable at the type level, (2) add `import logging` and emit a `logger.warning` with the listing URL or title on every skip, and (3) re-structure `_analyse_node` so that the outer exception is re-classified as `LLMAPIError` and the inner JSON parse exception as `LLMParseError` before logging. The public `analyse_listings` function should catch these typed exceptions and emit the listing-ID log. No new libraries are required — Python `logging` is stdlib.

The test infrastructure is already established: `tests/test_analysis.py` uses `pytest-asyncio` with `asyncio_mode = auto` and patches `apt_scrape.analysis._get_graph` and `apt_scrape.analysis._get_llm`. Two new focused tests are needed: one that injects an API-level exception and asserts `LLMAPIError` type and its log message, one that injects a JSON parse failure and asserts `LLMParseError` type and its log message.

**Primary recommendation:** Add `LLMAPIError` and `LLMParseError` exception classes in `analysis.py`, add a module-level `logger = logging.getLogger(__name__)`, restructure the fallback path in `_analyse_node` to raise typed exceptions with listing ID context, and write two unit tests using `caplog` to assert distinct log messages.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LLM-01 | LLM fallback path distinguishes parse failures from API failures with distinct log messages and exception types | Confirmed: current code has no exception typing and no logging; adding `LLMAPIError`/`LLMParseError` + `logger.warning` calls achieves this with zero new dependencies |
| LLM-02 | Listings that fail AI scoring are logged by listing ID so users can identify which ones were skipped | Confirmed: listing dicts carry `"url"` and `"title"` keys (visible in `_score_one` fallback); logging `listing.get("url") or listing.get("title")` gives the identifier |
| LLM-03 | Unit test covers parse failure path and API failure path separately | Confirmed: existing `tests/test_analysis.py` uses `patch("apt_scrape.analysis._get_graph")` and `AsyncMock`; same pattern supports injecting typed exceptions; `caplog` fixture asserts log content |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `logging` | N/A | Emit structured warning/error messages with module context | Language standard; already used in `src/backend/runner.py`; zero new dependencies |
| Python stdlib `try/except` | N/A | Catch and re-classify exceptions into typed error hierarchy | Language primitive |
| `pytest` | latest (dev dep) | Test runner | Project standard — `pytest.ini` present |
| `pytest-asyncio` | >=0.23 | Async test support | Already installed; `asyncio_mode = auto` in `pytest.ini` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` `caplog` fixture | stdlib pytest | Assert log messages in unit tests | For LLM-03 tests asserting distinct warning messages |
| `unittest.mock.AsyncMock` | stdlib | Mock async LLM calls | Already used in `test_analysis.py` |
| `unittest.mock.patch` | stdlib | Patch `_get_graph` and `_get_llm` | Already used in `test_analysis.py` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `logging.getLogger(__name__)` | `click.echo(..., err=True)` | `click.echo` is already used for progress; `logging` is more appropriate for error/warning paths and is testable via `caplog`; keep both — progress via `click`, errors via `logging` |
| Custom exception classes | Sentinel strings in `ai_verdict` field | String-based sentinels are already present (`"Error"`) but cannot be caught by type; typed exceptions enable structured error handling by callers |
| Logging in `_analyse_node` | Logging in `_score_one` | `_score_one` has the listing dict with ID; logging belongs there or in the node after typed re-raise; logging at `_score_one` level is cleanest because it has the listing context |

**Installation:** No new dependencies required.

## Architecture Patterns

### Current Error Flow (analysis.py)

```
_analyse_node(state)
├── try:
│   └── structured_llm.ainvoke(...)        ← API call (HTTP, auth, timeout)
│       raises Exception on failure
└── except Exception:                       ← catches ALL — API AND parse errors
    ├── try:
    │   ├── _get_llm().ainvoke(...)         ← fallback API call
    │   ├── json.loads(text[start:end])     ← parse step
    │   └── NotionApartmentFields(**data)   ← construction step
    └── except Exception as e2:             ← catches ALL — no distinction
        └── result = NotionApartmentFields(ai_verdict="Error", ...)
                                            ← no log, no listing ID

_score_one(listing)
├── try:
│   └── graph.ainvoke(...)
└── except Exception as e:                  ← catches typed or generic
    └── result = fallback(...)              ← no log, no listing ID
```

### Target Error Flow After Fix

```
_analyse_node(state)
├── try:
│   └── structured_llm.ainvoke(...)
└── except Exception as e:
    └── raise LLMAPIError(str(e)) from e    ← typed re-raise (API failure)

    [separate fallback block or restructure:]
    ├── try (fallback JSON parse):
    │   ├── raw_response = await _get_llm().ainvoke(...)
    │   ├── json.loads(...)
    │   └── NotionApartmentFields(**data)
    └── except (json.JSONDecodeError, ValidationError, ...) as e2:
        └── raise LLMParseError(str(e2)) from e2   ← typed re-raise (parse failure)

_score_one(listing)
├── try:
│   └── graph.ainvoke(...)
├── except LLMAPIError as e:
│   ├── logger.warning("Listing %s skipped: API failure — %s", listing_id, e)
│   └── result = fallback(...)
└── except LLMParseError as e:
    ├── logger.warning("Listing %s skipped: parse failure — %s", listing_id, e)
    └── result = fallback(...)
```

### Pattern 1: Custom Exception Hierarchy for Observability

**What:** Define narrow exception classes that signal the failure mode by type, not just message content.
**When to use:** Whenever callers need to react differently to different failure modes, or when tests need to assert specific failure types.
**Example:**
```python
# Source: Python docs — User-defined exceptions
# https://docs.python.org/3/tutorial/errors.html#user-defined-exceptions

class LLMError(Exception):
    """Base class for LLM scoring failures."""

class LLMAPIError(LLMError):
    """Raised when the LLM API call fails (network, auth, HTTP error)."""

class LLMParseError(LLMError):
    """Raised when the LLM response cannot be parsed into NotionApartmentFields."""
```

### Pattern 2: Module Logger + caplog Testing

**What:** Add `logger = logging.getLogger(__name__)` at module level; emit `logger.warning(...)` on skips; assert log output in tests via `caplog`.
**When to use:** Whenever you need testable log output without touching stdout/stderr directly.
**Example:**
```python
# Source: pytest docs — caplog fixture
# https://docs.pytest.org/en/stable/how-to/logging.html

import logging
import pytest

def test_api_failure_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="apt_scrape.analysis"):
        # inject API failure ...
        pass
    assert "API failure" in caplog.text
    assert "listing-url-or-title" in caplog.text
```

### Pattern 3: Catching Typed Exceptions to Assert in Tests

**What:** Side-effect mocks that raise specific exception types; assert both the exception type and the log message.
**When to use:** LLM-03 requires that API and parse paths are tested SEPARATELY with DISTINCT assertions.
**Example:**
```python
# Source: unittest.mock docs + existing test_analysis.py pattern
from unittest.mock import AsyncMock, patch
from apt_scrape.analysis import LLMAPIError, LLMParseError

@pytest.mark.asyncio
async def test_api_failure_path(caplog):
    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = LLMAPIError("connection timeout")
        mock_get_graph.return_value = mock_app

        with caplog.at_level(logging.WARNING, logger="apt_scrape.analysis"):
            listings = [{"url": "https://example.com/1", "title": "Test apt"}]
            await analyse_listings(listings, preferences="want bright apt")

    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    # Distinct message for API failure
    assert any("API failure" in r.message for r in caplog.records)
    assert any("https://example.com/1" in r.message for r in caplog.records)
```

### Anti-Patterns to Avoid

- **Catching `Exception` and re-raising as the same generic type:** defeats the purpose of typed errors; always re-raise as `LLMAPIError` or `LLMParseError`.
- **Logging inside `_analyse_node`:** The node does not have easy access to the listing ID in a clean way; log at `_score_one` level where the full listing dict is in scope.
- **Using `caplog` without `at_level`:** By default `caplog` only captures WARNING and above; set `caplog.at_level(logging.WARNING, logger="apt_scrape.analysis")` explicitly to avoid silent test misses.
- **Relying on `ai_verdict == "Error"` for test assertions:** String equality on `ai_verdict` is already tested by the existing `test_analyse_listings_handles_error_gracefully`; LLM-03 requires NEW tests that assert on log messages and exception types, not just verdict strings.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Testable log output | Custom log capture fixture | `pytest` `caplog` fixture | Built-in, reliable, no setup needed |
| Error classification | String parsing of exception messages | Typed exception hierarchy (`LLMAPIError`, `LLMParseError`) | Type-based dispatch is Python-idiomatic, testable with `isinstance` |
| Listing identifier lookup | Parse URLs from AI output | `listing.get("url") or listing.get("title", "unknown")` | Listing dict always has these keys at `_score_one` call site |

**Key insight:** The entire phase requires zero new dependencies. The gap is purely missing `logging` calls and missing exception typing in code that already handles errors gracefully.

## Common Pitfalls

### Pitfall 1: Restructuring fallback logic breaks the happy path
**What goes wrong:** Moving the `except Exception` blocks around accidentally swallows exceptions that should propagate, or produces `None` result objects.
**Why it happens:** `_analyse_node` returns `{**state, "result": result}` — if `result` is never assigned on a code path, a `NameError` or `None` propagates to `_score_one`.
**How to avoid:** Ensure every code path in `_analyse_node` either assigns `result` or raises a typed exception. The existing final fallback (`NotionApartmentFields(ai_verdict="Error", ...)`) should remain as the catch-all at the `_score_one` level, not inside `_analyse_node`.

### Pitfall 2: caplog not capturing at the right logger name
**What goes wrong:** `caplog.text` is empty even though the code does emit a warning.
**Why it happens:** `logging.getLogger(__name__)` uses the module's `__name__` = `"apt_scrape.analysis"`. Without specifying the logger name in `caplog.at_level(...)`, pytest may use a different root logger level.
**How to avoid:** Always use `caplog.at_level(logging.WARNING, logger="apt_scrape.analysis")` in the test context manager, or set `log_cli_level = WARNING` in `pytest.ini`.
**Warning signs:** Test passes with `caplog.text == ""` rather than `AssertionError`.

### Pitfall 3: LLMAPIError raised inside _analyse_node not caught by _score_one
**What goes wrong:** If `_score_one` only catches `Exception` (not the specific typed subclasses), the typed distinction is lost before the log call.
**Why it happens:** `LLMAPIError` and `LLMParseError` are both `Exception` subclasses, so a broad `except Exception` will catch them — but won't branch by type.
**How to avoid:** In `_score_one`, use two separate `except` clauses in order: `except LLMAPIError`, then `except LLMParseError`, each with its own `logger.warning` call with a distinct message.

### Pitfall 4: Existing test_analyse_listings_handles_error_gracefully breaks
**What goes wrong:** The existing test patches `_get_graph` to raise a plain `Exception("network error")`. After the refactor, `_score_one` may only catch `LLMAPIError`/`LLMParseError`, causing plain `Exception` to propagate.
**Why it happens:** If `_score_one` is narrowed to only catch typed exceptions, untyped exceptions from `_get_graph` (like in the existing test) will not be caught.
**How to avoid:** Keep a final `except Exception` in `_score_one` as a safety net (after the typed handlers), or ensure the test raises `LLMAPIError` rather than plain `Exception`. Update the existing test to raise a typed exception so it remains meaningful.

### Pitfall 5: Module-level `_llm_instance` singleton interferes with test isolation
**What goes wrong:** A previous test that calls `_get_llm()` caches a `ChatOpenAI` instance; later tests that patch `_get_llm` are affected.
**Why it happens:** `_llm_instance` is a module-level singleton. Patching `_get_llm` in tests bypasses the singleton; patching `_make_llm` may not.
**How to avoid:** Patch `apt_scrape.analysis._get_llm` (not `_make_llm`) as already done in the existing test. After tests, reset `apt_scrape.analysis._llm_instance = None` in a `teardown` or use `autouse` fixture if needed.

## Code Examples

### Exception Class Definitions
```python
# Source: Python docs — User-defined exceptions
# https://docs.python.org/3/tutorial/errors.html#user-defined-exceptions

class LLMError(Exception):
    """Base class for all LLM scoring failures."""

class LLMAPIError(LLMError):
    """Raised when the LLM API call itself fails (network, HTTP, auth error)."""

class LLMParseError(LLMError):
    """Raised when the LLM response cannot be parsed into structured output."""
```

### Module Logger Setup
```python
# Source: Python logging docs
# https://docs.python.org/3/library/logging.html#logger-objects

import logging

logger = logging.getLogger(__name__)
# __name__ == "apt_scrape.analysis" — matches caplog logger name in tests
```

### _score_one Logging Pattern
```python
# Source: Python logging docs + existing analysis.py structure

async def _score_one(listing: dict) -> None:
    listing_id = listing.get("url") or listing.get("title", "unknown")
    async with semaphore:
        try:
            output = await graph.ainvoke(
                {"listing": listing, "preferences": preferences, "result": None}
            )
            result: NotionApartmentFields = output["result"]
        except LLMAPIError as e:
            logger.warning("Listing %s skipped: LLM API failure — %s", listing_id, e)
            result = NotionApartmentFields(
                title=listing.get("title", "Untitled"),
                ai_score=0,
                ai_verdict="Error",
                ai_reason=str(e),
            )
        except LLMParseError as e:
            logger.warning("Listing %s skipped: LLM parse failure — %s", listing_id, e)
            result = NotionApartmentFields(
                title=listing.get("title", "Untitled"),
                ai_score=0,
                ai_verdict="Error",
                ai_reason=str(e),
            )
        except Exception as e:
            # Safety net for unexpected errors
            logger.warning("Listing %s skipped: unexpected error — %s", listing_id, e)
            result = NotionApartmentFields(
                title=listing.get("title", "Untitled"),
                ai_score=0,
                ai_verdict="Error",
                ai_reason=str(e),
            )
        # ... rest unchanged
```

### Test: API Failure Path
```python
# Source: pytest caplog docs + existing test_analysis.py pattern
# https://docs.pytest.org/en/stable/how-to/logging.html

import logging
import pytest
from unittest.mock import AsyncMock, patch
from apt_scrape.analysis import LLMAPIError, analyse_listings

LISTING = {"url": "https://example.com/apt/1", "title": "Test apt", "price": "€900"}

@pytest.mark.asyncio
async def test_api_failure_logs_distinct_message(caplog):
    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = LLMAPIError("connection timeout")
        mock_get_graph.return_value = mock_app

        with caplog.at_level(logging.WARNING, logger="apt_scrape.analysis"):
            listings = [dict(LISTING)]
            await analyse_listings(listings, preferences="want bright apt")

    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    assert any("API failure" in r.message for r in caplog.records)
    assert any("https://example.com/apt/1" in r.message for r in caplog.records)
```

### Test: Parse Failure Path
```python
@pytest.mark.asyncio
async def test_parse_failure_logs_distinct_message(caplog):
    with patch("apt_scrape.analysis._get_graph") as mock_get_graph:
        mock_app = AsyncMock()
        mock_app.ainvoke.side_effect = LLMParseError("invalid JSON")
        mock_get_graph.return_value = mock_app

        with caplog.at_level(logging.WARNING, logger="apt_scrape.analysis"):
            listings = [dict(LISTING)]
            await analyse_listings(listings, preferences="want bright apt")

    assert listings[0]["ai_score"] == 0
    assert listings[0]["ai_verdict"] == "Error"
    # Distinct message — "parse failure" not "API failure"
    assert any("parse failure" in r.message for r in caplog.records)
    assert not any("API failure" in r.message for r in caplog.records)
    assert any("https://example.com/apt/1" in r.message for r in caplog.records)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Bare `except Exception` swallowing all LLM errors | Typed `LLMAPIError` / `LLMParseError` + `logger.warning` | This phase | Users can identify skipped listings and diagnose failure mode from logs |
| No logging in analysis.py | `logging.getLogger(__name__)` + `logger.warning` per skip | This phase | Testable, structured warning messages visible in server logs |

**Deprecated/outdated:**
- `except Exception as e2: result = NotionApartmentFields(ai_verdict="Error", ...)` without logging: Replace with typed raise + logging at `_score_one` level.

## Open Questions

1. **Should `_analyse_node` raise typed exceptions or should `_score_one` classify them?**
   - What we know: `_analyse_node` is the LangGraph node; raising from inside it lets the graph propagate the typed exception to `_score_one`. Alternatively, `_score_one` can catch all exceptions and classify by heuristic (e.g., `isinstance(e, httpx.HTTPError)` = API, otherwise parse).
   - What's unclear: Whether LangGraph wraps exceptions or re-raises them transparently.
   - Recommendation: Raise typed exceptions from inside `_analyse_node` (the inner `try/except` blocks already distinguish the two failure modes structurally); this is the cleanest approach and matches the requirement's framing of "distinct exception types."

2. **Should the fallback path (raw-JSON retry) be preserved?**
   - What we know: The current outer `except Exception` triggers a second LLM call with a simpler prompt. This is a useful reliability mechanism.
   - What's unclear: Whether the fallback should count as an "API failure" or be transparent.
   - Recommendation: Keep the fallback. If the fallback API call fails, raise `LLMAPIError`. If the fallback JSON parse fails, raise `LLMParseError`. The fallback's existence is orthogonal to the observability requirement.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio >= 0.23 |
| Config file | `pytest.ini` (asyncio_mode = auto, pythonpath = src) |
| Quick run command | `pytest tests/test_analysis.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LLM-01 | API failure emits a log message containing "API failure"; parse failure emits a message containing "parse failure" | unit | `pytest tests/test_analysis.py::test_api_failure_logs_distinct_message tests/test_analysis.py::test_parse_failure_logs_distinct_message -x` | No — Wave 0 gap |
| LLM-02 | Listing URL or title appears in the warning log message when a listing is skipped | unit | `pytest tests/test_analysis.py::test_api_failure_logs_distinct_message tests/test_analysis.py::test_parse_failure_logs_distinct_message -x` | No — Wave 0 gap (same tests as LLM-01) |
| LLM-03 | Two separate tests, one for each failure path, asserting distinct exception types and log messages | unit | `pytest tests/test_analysis.py -x` | Partial — file exists, two new test functions needed |

### Sampling Rate
- **Per task commit:** `pytest tests/test_analysis.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_analysis.py::test_api_failure_logs_distinct_message` — covers LLM-01 (API path) and LLM-02
- [ ] `tests/test_analysis.py::test_parse_failure_logs_distinct_message` — covers LLM-01 (parse path) and LLM-02

*(Framework and shared fixtures already exist — `pytest.ini`, `LISTING` fixture in test_analysis.py, `asyncio_mode = auto`)*

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `src/apt_scrape/analysis.py` — full file read; error handling structure confirmed
- Direct code inspection: `tests/test_analysis.py` — existing test patterns confirmed; `caplog` not yet used
- Direct code inspection: `pytest.ini` — asyncio_mode = auto, pythonpath = src confirmed
- Direct code inspection: `pyproject.toml` — no new dependencies required; `pytest-asyncio >= 0.23` already installed
- Python Language Reference — User-defined exceptions: https://docs.python.org/3/tutorial/errors.html#user-defined-exceptions
- Python `logging` module docs: https://docs.python.org/3/library/logging.html
- pytest `caplog` fixture docs: https://docs.pytest.org/en/stable/how-to/logging.html

### Secondary (MEDIUM confidence)
- N/A — all findings derived from direct code inspection and stdlib docs

### Tertiary (LOW confidence)
- N/A

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project; fix uses only stdlib constructs
- Architecture: HIGH — `analysis.py` read in full; error paths traced line by line; listing dict keys confirmed
- Pitfalls: HIGH — derived from direct analysis of current code, existing test patterns, and Python logging/caplog semantics

**Research date:** 2026-03-16
**Valid until:** Stable — Python `logging`, `try/except`, and `caplog` semantics do not change; valid until `analysis.py` is substantially refactored
