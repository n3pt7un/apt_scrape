# Phase 4: Notion Fail-Fast - Research

**Researched:** 2026-03-16
**Domain:** Python exception handling, notion-client error types, pytest-asyncio mocking
**Confidence:** HIGH

## Summary

Phase 4 is a surgical one-file fix to `src/backend/runner.py`. The current Notion pre-check
block (lines 178–187) wraps `mark_notion_duplicates()` in a broad `try/except Exception` that
logs a warning and continues silently. The fix is to remove that try/except (or re-raise) so
that any `APIResponseError` or other exception from `mark_notion_duplicates()` propagates up
into the outer `try/except` in `run_config_job`, which already marks the job `status="failed"`
and persists the error via `_log()` in the `finally` block.

The unit test mirrors the pattern from Phase 2's `test_log_persists_on_mid_job_exception`: mock
`mark_notion_duplicates` to raise an exception, then assert the job ends in `"failed"` status
and that `push_listings` was never called.

**Primary recommendation:** Remove the inner try/except around the Notion pre-check in
`runner.py`; let the exception fall through to the outer handler. Add one `pytest.mark.asyncio`
test in `tests/backend/test_runner.py`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| NOTION-01 | Notion pre-check API errors cause the job to fail fast rather than silently continuing to push potential duplicates | Remove the `except Exception` swallower around `mark_notion_duplicates()`; outer handler in `run_config_job` already marks job failed and logs the error |
| NOTION-02 | Unit test verifies that a Notion API error during pre-check raises an exception (not a warning) | Mock `mark_notion_duplicates` to raise, assert job status is `"failed"` and `push_listings` never called |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| notion-client | 2.2.1 (pinned in pyproject.toml) | Async Notion API; raises `notion_client.errors.APIResponseError` on API failures | Already in project; `APIResponseError` is the canonical error type |
| pytest | (dev dep) | Test runner | Already in project |
| pytest-asyncio | >=0.23 (dev dep) | `asyncio_mode = auto` in pytest.ini | Already in project; existing async tests use this pattern |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| unittest.mock | stdlib | `AsyncMock`, `patch`, `patch.dict` | Mock `mark_notion_duplicates` and `push_listings` in test |

**Installation:** No new dependencies required.

## Architecture Patterns

### Relevant Project Structure
```
src/
├── apt_scrape/
│   └── notion_push.py        # mark_notion_duplicates(), push_listings()
└── backend/
    └── runner.py             # run_config_job() — the target file

tests/
└── backend/
    └── test_runner.py        # Target test file (existing, append new test)
```

### Pattern 1: Remove the inner try/except (fail-fast)
**What:** Delete the `try/except Exception` wrapper around the Notion pre-check block.
**When to use:** Any time a failure should halt the pipeline, not be swallowed.
**Current code (lines 178–187 of runner.py):**
```python
# CURRENT — swallows the error
if auto_notion_push:
    _log("Checking Notion for already-pushed listings to skip enrichment...")
    try:
        from apt_scrape.notion_push import mark_notion_duplicates
        num_skipped = await mark_notion_duplicates(deduped)
        if num_skipped > 0:
            _log(f"Found {num_skipped} listings already in Notion. Skipping heavy enrichment for them.")
        to_enrich = [L for L in deduped if not L.get("notion_skipped")]
    except Exception as e:
        _log(f"[warn] Failed to do Notion pre-check: {e}")
```
**Fixed code:**
```python
# FIXED — exception propagates to outer handler → job marked "failed"
if auto_notion_push:
    _log("Checking Notion for already-pushed listings to skip enrichment...")
    from apt_scrape.notion_push import mark_notion_duplicates
    num_skipped = await mark_notion_duplicates(deduped)
    if num_skipped > 0:
        _log(f"Found {num_skipped} listings already in Notion. Skipping heavy enrichment for them.")
    to_enrich = [L for L in deduped if not L.get("notion_skipped")]
```

### Pattern 2: Existing outer exception handler (no change needed)
The outer `except Exception as exc` block in `run_config_job` already:
1. Calls `logger.exception("Job %d failed", job_id)`
2. Calls `_log(f"[ERROR] {exc}")` — writes to job log
3. Sets `job.status = "failed"` in the DB
4. The `finally` block flushes the log buffer

This means zero additional code is needed for error propagation — the fix is purely subtractive.

### Pattern 3: Test structure (mirrors Phase 2 test)
**Source:** `tests/backend/test_runner.py::test_log_persists_on_mid_job_exception`
```python
# Pattern for new test — mock mark_notion_duplicates to raise, assert job fails
@pytest.mark.asyncio  # or no decorator since asyncio_mode = auto
async def test_notion_precheck_error_fails_job():
    config_id = _make_config(auto_notion_push=True)
    logs = []

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides") as mock_get_adapter,
        patch("backend.runner.enrich_with_details", new_callable=AsyncMock),
        patch("backend.runner.enrich_post_dates", new_callable=AsyncMock),
        patch("apt_scrape.notion_push.mark_notion_duplicates",
              new=AsyncMock(side_effect=Exception("Notion API error"))),
        patch("apt_scrape.notion_push.push_listings",
              new=AsyncMock()) as mock_push,
    ):
        mock_browser.fetch_page = AsyncMock(return_value="<html></html>")
        mock_adapter = MagicMock()
        mock_adapter.build_search_url.return_value = "https://example.com/search"
        mock_adapter.parse_search.return_value = [_make_fake_listing()]
        mock_adapter.config.search_wait_selector = None
        mock_adapter.config.page_load_wait = "domcontentloaded"
        mock_adapter.config.search_wait_timeout = 15000
        mock_get_adapter.return_value = mock_adapter

        job_id = await run_config_job(config_id, logs.append)

    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job.status == "failed"
    mock_push.assert_not_called()
```

**Key detail:** `asyncio_mode = auto` in pytest.ini means `asyncio.run()` is NOT used in
async tests — `await` is used directly. Existing async tests in `test_notion_push.py` confirm
this. However, `test_runner.py` currently uses `asyncio.run()` (synchronous test functions) —
new async tests should be consistent with the file's existing style OR be `async def` since
`asyncio_mode = auto` supports both.

### Anti-Patterns to Avoid
- **Wrapping the fix in a new custom exception:** Don't create a `NotionPreCheckError` class; the plain `Exception` from `notion_client` is sufficient and the outer handler catches all exceptions.
- **Calling `push_listings` check with `mock_push.assert_not_called()`:** The patch target must be `apt_scrape.notion_push.push_listings` to match the import in runner.py (`from apt_scrape.notion_push import push_listings`).
- **Using `pytest.raises` instead of asserting job status:** The function does NOT re-raise — it returns `job_id` after setting status to `"failed"`. Use DB assertion, not exception assertion.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Detecting Notion API errors | Custom HTTP status checking | Let `notion_client.AsyncClient` raise `APIResponseError` naturally | notion-client already wraps all 4xx/5xx responses |
| Propagating errors to job status | Custom error state machine | The existing outer `except Exception` handler | It already sets `status="failed"` and logs |
| Async test infrastructure | New conftest fixtures | `pytest-asyncio` with `asyncio_mode = auto` + existing `_make_config()` helper | Already in test_runner.py |

**Key insight:** The fix is removing code (the inner try/except), not adding it. The error handling infrastructure is already correct — it was just being bypassed.

## Common Pitfalls

### Pitfall 1: Patch target mismatch
**What goes wrong:** Test patches `backend.runner.mark_notion_duplicates` but the import in runner.py is `from apt_scrape.notion_push import mark_notion_duplicates`, so the name is bound locally.
**Why it happens:** Python's mock patching requires targeting the name in the module where it is used, not where it is defined.
**How to avoid:** Patch `apt_scrape.notion_push.mark_notion_duplicates` OR patch it before the import happens. Checking the actual import statement in runner.py (line 181) shows it is a deferred import inside the `if auto_notion_push:` block — patch `apt_scrape.notion_push.mark_notion_duplicates` directly.
**Warning signs:** Test passes but `mock_push` gets called unexpectedly.

### Pitfall 2: _make_config does not set auto_notion_push=True
**What goes wrong:** The test creates a config with `auto_notion_push=False` (the default in the helper), so the pre-check block is never entered.
**How to avoid:** Call `_make_config(auto_notion_push=True)` — or update `_make_config` to accept kwargs.
**Warning signs:** `mark_notion_duplicates` mock is never called; test passes vacuously.

### Pitfall 3: Mixing asyncio.run() and async def tests
**What goes wrong:** `test_runner.py` existing tests use `asyncio.run()` (sync functions). New test using `async def` also works under `asyncio_mode = auto`, but mixing styles in the same file causes confusion.
**How to avoid:** Use `asyncio.run()` + sync def to stay consistent with existing test style, OR add `async def` — both work. Recommend matching existing style.

### Pitfall 4: push_listings patch target
**What goes wrong:** runner.py's notion push call at line 228 (`from apt_scrape.notion_push import push_listings`) is also a deferred import. Must patch `apt_scrape.notion_push.push_listings`.
**How to avoid:** Always patch at the definition site for deferred imports.

## Code Examples

### Deferred import patching (confirmed from existing tests)
```python
# Source: tests/test_notion_push.py — confirms deferred import patch style
with patch("apt_scrape.notion_push.AsyncClient") as MockClient:
    ...
```

### Existing _make_config signature
```python
# Source: tests/backend/test_runner.py lines 12-24
def _make_config():
    with Session(engine) as s:
        cfg = SearchConfig(
            ...,
            auto_notion_push=False,   # <-- must pass True for NOTION tests
        )
```
The `_make_config` helper must be called with `auto_notion_push=True` or extended with a parameter.

### asyncio_mode = auto confirmed
```ini
# Source: pytest.ini
[pytest]
asyncio_mode = auto
pythonpath = src
```
Both sync (`asyncio.run()`) and async def tests work. Existing `test_notion_push.py` uses `async def` with `@pytest.mark.asyncio` decorators, confirming both patterns coexist.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Swallow pre-check errors with `[warn]` log | Raise — outer handler marks job failed | Phase 4 (this phase) | Pre-check failures are visible as job failures, not silent warnings |

## Open Questions

1. **Should `mark_notion_duplicates` itself catch and re-raise with a richer message?**
   - What we know: It currently makes raw `client.databases.query()` calls that raise `APIResponseError` on failure.
   - What's unclear: Whether wrapping with a more descriptive exception (e.g., `RuntimeError("Notion pre-check failed: ...")`) would improve log clarity.
   - Recommendation: Keep it simple — let `APIResponseError` propagate with its existing message. The outer `_log(f"[ERROR] {exc}")` will record the Notion API error message verbatim.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio >= 0.23 |
| Config file | pytest.ini |
| Quick run command | `python -m pytest tests/backend/test_runner.py -q` |
| Full suite command | `python -m pytest -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NOTION-01 | Notion pre-check error halts job (status="failed"), push_listings not called | unit | `python -m pytest tests/backend/test_runner.py::test_notion_precheck_error_fails_job -x` | Wave 0 |
| NOTION-02 | Same test: asserts exception path taken, not warning path | unit (same test) | `python -m pytest tests/backend/test_runner.py::test_notion_precheck_error_fails_job -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/backend/test_runner.py -q`
- **Per wave merge:** `python -m pytest -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/backend/test_runner.py::test_notion_precheck_error_fails_job` — covers NOTION-01 + NOTION-02 (new test function in existing file)

*(Existing test file and infrastructure are in place. Only the new test function is missing.)*

## Sources

### Primary (HIGH confidence)
- Direct code inspection of `src/backend/runner.py` — lines 176–188 (the pre-check block), lines 286–299 (outer exception handler + finally)
- Direct code inspection of `src/apt_scrape/notion_push.py` — `mark_notion_duplicates()` implementation
- Direct code inspection of `tests/backend/test_runner.py` — `_make_config()` helper, test patterns
- Direct code inspection of `tests/test_notion_push.py` — async mock patterns, deferred import patching
- `pytest.ini` — `asyncio_mode = auto`, `pythonpath = src`
- `pyproject.toml` — `notion-client==2.2.1` pinned, `pytest-asyncio>=0.23`

### Secondary (MEDIUM confidence)
- notion-client 2.2.1 raises `notion_client.errors.APIResponseError` on HTTP errors — standard behavior of the library consistent with its README

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new dependencies; everything already in project
- Architecture: HIGH — fix is subtractive (remove inner try/except); outer handler already correct
- Pitfalls: HIGH — patch target issue is a well-known pytest-mock pattern; confirmed by reading actual import statements

**Research date:** 2026-03-16
**Valid until:** 2026-04-16 (stable codebase, no external API dependency changes expected)
