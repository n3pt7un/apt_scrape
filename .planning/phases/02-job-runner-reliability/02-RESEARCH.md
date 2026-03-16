# Phase 02: Job Runner Reliability - Research

**Researched:** 2026-03-16
**Domain:** Python exception handling, try/except/finally semantics, SQLModel session management
**Confidence:** HIGH

## Summary

The job runner (`src/backend/runner.py`) currently calls `_flush_log()` in two places: at the end of the `try` block (happy path, line 284) and inside the `except Exception as exc` handler (line 290). This means the flush is NOT guaranteed to run in all failure scenarios. Specifically: if an exception is raised inside the `except` block itself (the DB write for `job.status = "failed"` at lines 291–297 fails), `_flush_log()` would have already run — but if a `BaseException` subclass (e.g., `KeyboardInterrupt`, `asyncio.CancelledError`) is raised inside the `try` block, the `except Exception` clause will not catch it, so the flush never runs and log lines are lost.

The fix is minimal and surgical: remove `_flush_log()` from both the `try` and `except` branches and place one `_flush_log()` call inside a `finally` block. A `finally` block runs regardless of whether the code path exits via normal return, `Exception`, or `BaseException`. No new libraries, no architectural changes.

The unit test pattern is already established in `tests/backend/test_runner.py`: create an in-memory DB config, mock adapters, run the job via `asyncio.run()`, then query the DB. The new test injects a mid-job exception and asserts that log lines written before the exception appear in `job.log`.

**Primary recommendation:** Add a `finally:` block to `run_config_job` that calls `_flush_log()`, and remove the duplicate calls from `try` and `except` branches. Write one focused test.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RUNNER-01 | Job log buffer is flushed in a `finally` block so final error messages always persist to the database even if an exception occurs mid-job | Confirmed: current code has `_flush_log()` in `try` and `except` but not `finally`; moving it to `finally` is the correct fix |
| RUNNER-02 | Unit test verifies that log messages written before an exception are present in the Job record | Confirmed: existing test infrastructure in `tests/backend/test_runner.py` uses in-memory DB + mocks; same pattern works for the new test |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib `try/finally` | N/A (language construct) | Guarantee cleanup code runs regardless of exception path | Language-level guarantee; no library needed |
| `sqlmodel` | 0.0.21 | ORM for DB writes in `_flush_log()` | Already used throughout runner; no change needed |
| `pytest` | latest (dev dep) | Test runner | Project standard (pytest.ini present) |
| `pytest-asyncio` | >=0.23 | Async test support | Already installed; `asyncio_mode = auto` set in pytest.ini |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `unittest.mock.AsyncMock` | stdlib | Mock async browser/adapter in tests | Already used in test_runner.py |
| `unittest.mock.patch` | stdlib | Patch module-level dependencies | Already used in test_runner.py |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `finally` block | Context manager / decorator | `finally` is idiomatic Python, zero complexity, no new abstractions needed |
| Single `_flush_log()` in `finally` | Keep duplicate calls + add finally | Duplicate calls are harmless but add noise; single call in `finally` is cleaner |

**Installation:** No new dependencies required.

## Architecture Patterns

### Current Control Flow (runner.py)

```
run_config_job()
├── try:
│   ├── ... all job work ...
│   ├── _flush_log()          ← line 284 (happy path only)
│   └── return job_id
└── except Exception as exc:
    ├── _log("[ERROR] {exc}")
    ├── _flush_log()           ← line 290 (Exception path only)
    ├── ... mark job failed ...
    └── return job_id
                               ← BaseException paths (CancelledError, etc.) skip flush entirely
```

### Target Control Flow After Fix

```
run_config_job()
├── try:
│   ├── ... all job work ...
│   └── return job_id         ← no flush here
├── except Exception as exc:
│   ├── _log("[ERROR] {exc}")
│   ├── ... mark job failed ...
│   └── return job_id         ← no flush here
└── finally:
    └── _flush_log()           ← runs on ALL exit paths
```

### Pattern: `finally` for Resource/State Cleanup

**What:** Place any cleanup that must always execute in a `finally` block.
**When to use:** Log flushing, file handle closing, releasing locks — anything where "if I forget to call this, data is lost or resources leak."
**Example:**
```python
# Source: Python Language Reference — The try statement
# https://docs.python.org/3/reference/compound_stmts.html#the-try-statement
try:
    result = do_work()
    return result
except Exception as exc:
    logger.exception("Work failed: %s", exc)
    raise
finally:
    flush_logs()   # always runs, even on re-raise or BaseException
```

### Pattern: Testing Exception-Mid-Run with Mock Side Effects

**What:** Use `side_effect` on a mock to raise an exception at a specific point in execution, then assert state after the exception is caught.
**When to use:** Simulating mid-job failures to verify cleanup/persistence paths.
**Example:**
```python
# Pattern used in existing test_runner.py + unittest.mock docs
from unittest.mock import AsyncMock, patch

def test_log_persists_on_exception():
    config_id = _make_config()
    logs = []

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides") as mock_get_adapter,
        patch("backend.runner.enrich_with_details", new_callable=AsyncMock) as mock_enrich,
        patch("backend.runner.enrich_post_dates", new_callable=AsyncMock) as mock_post_dates,
    ):
        mock_browser.fetch_page = AsyncMock(side_effect=RuntimeError("network failure"))
        mock_adapter = MagicMock()
        mock_adapter.build_search_url.return_value = "https://example.com/search"
        mock_adapter.config.search_wait_selector = None
        mock_adapter.config.page_load_wait = "domcontentloaded"
        mock_adapter.config.search_wait_timeout = 15000
        mock_get_adapter.return_value = mock_adapter

        job_id = asyncio.run(backend_runner_run(config_id, logs.append))

    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job.status == "failed"
        assert "network failure" in job.log   # pre-exception log must be persisted
```

### Anti-Patterns to Avoid

- **Duplicate `_flush_log()` calls in multiple branches:** When a `finally` block exists, redundant flush calls in `try`/`except` can cause double-writes to `job.log` (since `_flush_log` reads then appends). Remove them from `try` and `except` when moving to `finally`.
- **Placing non-idempotent cleanup in `finally` without guard:** `_flush_log()` checks `if not _log_buffer: return` so it is already safe to call multiple times — the guard prevents double-append.
- **Re-raising inside `finally`:** Do not raise inside `finally`; it suppresses the original exception. The current `except` block does not re-raise (it returns `job_id`), which is fine.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Guaranteed cleanup on all exit paths | Custom exception wrapper, decorator, context manager | `finally` block | Language primitive; no abstraction needed for a single function |
| Test injection of mid-run exceptions | Custom exception-injecting harness | `mock.side_effect = Exception(...)` | stdlib; already used in this test file |

**Key insight:** `finally` blocks are the Python-idiomatic solution for "this must always run." Any other mechanism adds indirection with no benefit here.

## Common Pitfalls

### Pitfall 1: Forgetting `mock_adapter.config` attributes
**What goes wrong:** `AttributeError: Mock object has no attribute 'page_load_wait'` when the new test tries to access `adapter.config.page_load_wait` or `adapter.config.search_wait_timeout`.
**Why it happens:** `MagicMock()` auto-creates attributes, but `runner.py` accesses `getattr(adapter.config, "page_load_wait", "domcontentloaded")` — this is safe since `MagicMock` returns a mock object for any attribute. However, explicit assignment (`mock_adapter.config.page_load_wait = "domcontentloaded"`) makes test intent clear.
**How to avoid:** Mirror the mock setup from `test_run_config_job_creates_job_record`, which already handles the `search_wait_selector = None` pattern. Add `mock_adapter.config.page_load_wait` and `mock_adapter.config.search_wait_timeout` assignments.
**Warning signs:** Test fails with `AssertionError` rather than `AttributeError` — MagicMock silently returns truthy mock objects.

### Pitfall 2: `_flush_log` called before `_log("[ERROR] ...")` in finally
**What goes wrong:** The `[ERROR]` line added in the `except` block is not flushed if `_flush_log()` runs in `finally` before `_log` appends the error.
**Why it happens:** `finally` runs after `except`, so this is NOT actually a problem. Execution order is: `except` body (including `_log("[ERROR]")`) → `finally` body (including `_flush_log()`). The error line will be in the buffer when `_flush_log()` runs.
**How to avoid:** No action needed — just be aware of the order when writing the test assertion. The test should assert the `[ERROR]` line IS in `job.log`.

### Pitfall 3: Double-write if `_flush_log()` left in `except` AND added to `finally`
**What goes wrong:** `job.log` gets duplicate content: flush in `except` writes buffer once, then `finally` runs but buffer is now empty (cleared by first flush) — actually this is harmless. But it's confusing.
**Why it happens:** `_flush_log()` clears `_log_buffer` after writing, so a second call is a no-op. Still, remove the call from `except` to keep code clean.
**How to avoid:** Remove `_flush_log()` from lines 284 and 290 when adding the `finally` block.

### Pitfall 4: `return` inside `finally` suppresses exception
**What goes wrong:** If `_flush_log()` raises an exception inside `finally`, the original exception is silently suppressed.
**Why it happens:** Python suppresses the original exception when a new one is raised in `finally` — only if the `finally` block itself has an unhandled exception. `_flush_log()` uses a plain `with Session` block; a DB error here would suppress the original job exception.
**How to avoid:** Wrap `_flush_log()` in a `try/except` inside the `finally` block, or accept that DB flush failures are logged at the `logger` level. The existing code does not protect against this in the `except` block either, so the risk is unchanged.

## Code Examples

### Current Problematic Structure (lines 81–298 of runner.py)

```python
# Source: src/backend/runner.py (current — lines 81, 284, 287, 290)
try:
    # ... all job work ...
    _log(f"Job complete. {len(deduped)} listings processed.")
    _flush_log()           # only on happy path
    return job_id
except Exception as exc:
    logger.exception("Job %d failed", job_id)
    _log(f"[ERROR] {exc}")
    _flush_log()           # only on Exception subclass path
    with Session(engine) as session:
        # ... mark failed ...
    return job_id
# BaseException (CancelledError, KeyboardInterrupt) skips BOTH flush calls
```

### Fixed Structure

```python
# Target structure — no external sources needed; pure Python semantics
try:
    # ... all job work ...
    _log(f"Job complete. {len(deduped)} listings processed.")
    return job_id
except Exception as exc:
    logger.exception("Job %d failed", job_id)
    _log(f"[ERROR] {exc}")
    with Session(engine) as session:
        # ... mark failed ...
    return job_id
finally:
    _flush_log()           # runs on ALL exit paths
```

### Unit Test Pattern for Exception Injection

```python
# Source: unittest.mock docs (stdlib) + existing test_runner.py pattern
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from sqlmodel import Session
from backend.db import engine, Job

def test_log_persists_on_mid_job_exception():
    config_id = _make_config()
    logs = []

    with (
        patch("backend.runner.browser") as mock_browser,
        patch("backend.runner.get_adapter_with_overrides") as mock_get_adapter,
        patch("backend.runner.enrich_with_details", new_callable=AsyncMock),
        patch("backend.runner.enrich_post_dates", new_callable=AsyncMock),
    ):
        # Raise mid-job — after _log calls for "Fetching ..." already ran
        mock_browser.fetch_page = AsyncMock(side_effect=RuntimeError("boom"))
        mock_adapter = MagicMock()
        mock_adapter.build_search_url.return_value = "https://example.com/search"
        mock_adapter.config.search_wait_selector = None
        mock_get_adapter.return_value = mock_adapter

        job_id = asyncio.run(backend_runner_run(config_id, logs.append))

    with Session(engine) as s:
        job = s.get(Job, job_id)
        assert job.status == "failed"
        assert job.log is not None and len(job.log) > 0
        assert "boom" in job.log      # error message persisted
        # Also assert a pre-exception log line is present
        assert "Fetching" in job.log  # written before the exception
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Flush in `try` + flush in `except` | Flush in `finally` | This phase | Guarantees flush on all exit paths including `BaseException` |

**Deprecated/outdated:**
- Duplicate `_flush_log()` in two branches: Replace with single call in `finally`.

## Open Questions

1. **Should `_flush_log()` in `finally` be wrapped in its own try/except?**
   - What we know: If `_flush_log()` raises (DB down), it will suppress the original exception. Current code in `except` block has the same risk.
   - What's unclear: Is silent suppression of the original exception a concern here?
   - Recommendation: Out of scope for this phase per RUNNER-01/RUNNER-02. The fix scope is "flush always happens" not "flush failures are safe." Document with a comment in the code.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio >= 0.23 |
| Config file | `pytest.ini` (asyncio_mode = auto, pythonpath = src) |
| Quick run command | `pytest tests/backend/test_runner.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RUNNER-01 | `_flush_log()` is in a `finally` block | unit (structural assertion) | `pytest tests/backend/test_runner.py -x` | Partial — existing file, new test needed |
| RUNNER-02 | Log lines written before exception appear in `job.log` after job fails | unit | `pytest tests/backend/test_runner.py::test_log_persists_on_mid_job_exception -x` | No — Wave 0 gap |

### Sampling Rate
- **Per task commit:** `pytest tests/backend/test_runner.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/backend/test_runner.py::test_log_persists_on_mid_job_exception` — covers RUNNER-02 (new test function in existing file)

*(Framework and shared fixtures already exist — `pytest.ini`, `_make_config()` helper, DB setup in test_runner.py)*

## Sources

### Primary (HIGH confidence)
- Python Language Reference — The `try` statement: https://docs.python.org/3/reference/compound_stmts.html#the-try-statement
- Python `unittest.mock` docs: https://docs.python.org/3/library/unittest.mock.html
- Direct code inspection: `src/backend/runner.py` (lines 59-298) — current flush placement confirmed
- Direct code inspection: `tests/backend/test_runner.py` — existing test pattern confirmed
- Direct code inspection: `src/backend/db.py` — `Job.log: str = ""` field confirmed
- Direct code inspection: `pytest.ini` — asyncio_mode = auto confirmed

### Secondary (MEDIUM confidence)
- N/A — all findings are from direct code inspection or Python stdlib docs

### Tertiary (LOW confidence)
- N/A

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in project; fix uses only stdlib language constructs
- Architecture: HIGH — code was read directly; control flow traced line by line
- Pitfalls: HIGH — derived from direct analysis of current code and Python `finally` semantics

**Research date:** 2026-03-16
**Valid until:** Stable indefinitely — Python `try/finally` semantics do not change
