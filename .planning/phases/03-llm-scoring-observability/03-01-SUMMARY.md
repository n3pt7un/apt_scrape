---
phase: 03-llm-scoring-observability
plan: 01
subsystem: analysis
tags: [logging, exceptions, observability, pytest, caplog, tdd]

# Dependency graph
requires: []
provides:
  - LLMError, LLMAPIError, LLMParseError exception hierarchy in analysis.py
  - Module-level logger (logging.getLogger(__name__)) in analysis.py
  - Per-listing skip warning with listing URL in _score_one
  - Distinct log messages for API vs parse failures
  - Two new unit tests covering each failure path via caplog
affects: [04-notion-fail-fast]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Typed exception hierarchy (LLMError -> LLMAPIError / LLMParseError) for distinguishable LLM failure modes"
    - "Module-level logger = logging.getLogger(__name__) for testable structured warnings"
    - "caplog.at_level(logging.WARNING, logger=...) pattern for asserting log messages in async tests"
    - "Safety-net except Exception after typed except clauses to handle unexpected untyped errors"

key-files:
  created: []
  modified:
    - src/apt_scrape/analysis.py
    - tests/test_analysis.py

key-decisions:
  - "Log at _score_one level (not inside _analyse_node) because _score_one owns the listing dict with the URL identifier"
  - "Keep raw-JSON fallback in _analyse_node; only raise LLMParseError if the fallback parse also fails"
  - "Retain safety-net except Exception as final clause in _score_one so pre-existing tests raising plain Exception continue to pass"
  - "Update existing test_analyse_listings_handles_error_gracefully to raise LLMAPIError for meaningful typed coverage"

patterns-established:
  - "TDD RED/GREEN: write failing tests first, then add exception classes and typed handling"
  - "Distinct warning message strings ('LLM API failure' vs 'LLM parse failure') enable log-grep diagnostics"

requirements-completed: [LLM-01, LLM-02, LLM-03]

# Metrics
duration: 12min
completed: 2026-03-16
---

# Phase 3 Plan 01: LLM Scoring Observability Summary

**Typed LLMAPIError/LLMParseError exception hierarchy + module logger + per-listing skip warnings that distinguish API failures from parse failures by URL**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-16T11:57:52Z
- **Completed:** 2026-03-16T12:09:57Z
- **Tasks:** 3
- **Files modified:** 2

## Accomplishments
- Added `LLMError`, `LLMAPIError`, `LLMParseError` exception classes with clear docstrings to `analysis.py`
- Added `logger = logging.getLogger(__name__)` and `import logging` enabling testable structured warnings
- Restructured `_score_one` with three typed `except` clauses emitting distinct `logger.warning` messages per failure mode including listing URL
- Added two new `caplog`-based unit tests (`test_api_failure_logs_distinct_message`, `test_parse_failure_logs_distinct_message`) covering each failure path
- Full suite: 58 tests pass

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing tests (RED)** - `5a7c5cf` (test)
2. **Task 2: Add exception classes, logger, _score_one typed handling** - `eda6ac1` (feat)
3. **Task 3: Update existing test, full suite green** - `7ec4488` (feat)

_Note: Task 2 included the _score_one restructure because the tests patch _get_graph and the typed exceptions must be caught there for the new tests to pass._

## Files Created/Modified
- `src/apt_scrape/analysis.py` - Added import logging, LLMError/LLMAPIError/LLMParseError classes, module logger, restructured _analyse_node to raise LLMParseError, restructured _score_one with typed catch + logger.warning + listing_id capture
- `tests/test_analysis.py` - Added import logging, two new caplog tests, updated existing error test to raise LLMAPIError

## Decisions Made
- Logged at `_score_one` level, not inside `_analyse_node`, because `_score_one` has the listing dict with URL in scope
- The raw-JSON fallback in `_analyse_node` is preserved; `LLMParseError` is only raised when the fallback parse also fails
- A safety-net `except Exception` is retained as the final clause in `_score_one` to handle unexpected untyped errors (and to avoid breaking pre-existing plain-Exception patterns)
- Existing `test_analyse_listings_handles_error_gracefully` was updated to raise `LLMAPIError("network error")` instead of plain `Exception` for meaningful typed coverage while preserving the test's intent

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] _score_one typed exception handling added in Task 2, not Task 3**
- **Found during:** Task 2 (GREEN verification)
- **Issue:** The two new tests patch `_get_graph` to raise `LLMAPIError`/`LLMParseError` directly into `_score_one`. Task 2's acceptance criteria required those tests to pass, but the plan description placed `_score_one` restructuring in Task 3. The tests could not pass without typed handlers in `_score_one`.
- **Fix:** Added full typed `except` clauses with `logger.warning` and `listing_id` capture to `_score_one` during Task 2, making Task 3 a smaller update (just the existing test change).
- **Files modified:** src/apt_scrape/analysis.py
- **Verification:** Both new tests passed after fix; full suite passed in Task 3
- **Committed in:** eda6ac1 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (execution order — _score_one typed handling done in Task 2 rather than Task 3 to satisfy Task 2 acceptance criteria)
**Impact on plan:** No scope change. All planned work completed. Task 3 remained meaningful (existing test update + full suite gate).

## Issues Encountered
None beyond the deviation documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LLM-01, LLM-02, LLM-03 requirements fully satisfied
- Phase 3 analysis.py now exports `LLMAPIError` and `LLMParseError` for potential use by Phase 4 (Notion fail-fast)
- No blockers

## Self-Check: PASSED
- FOUND: src/apt_scrape/analysis.py
- FOUND: tests/test_analysis.py
- FOUND: .planning/phases/03-llm-scoring-observability/03-01-SUMMARY.md
- FOUND: commit 5a7c5cf (test: failing tests RED)
- FOUND: commit eda6ac1 (feat: exception classes + typed handling)
- FOUND: commit 7ec4488 (feat: existing test updated + full suite green)
