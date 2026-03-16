# Phase 4: Notion Fail-Fast - Context

**Gathered:** 2026-03-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Make the Notion pre-check API error halt the job immediately rather than silently continuing. The pre-check is `mark_notion_duplicates()` called in `runner.py`. When it raises, the job must stop — no listings should be pushed. A unit test must assert this behavior.

</domain>

<decisions>
## Implementation Decisions

### Error propagation
- The `except` block in `runner.py` (line 186-187) must be changed to log then re-raise — not suppress
- Log an explicit `[error]` message before re-raising so the job log shows the cause (e.g. `"[error] Notion pre-check failed: {e}"`)
- The exception then propagates to the job-level error handler, making the failure visible in job logs
- No listings should be pushed when the pre-check fails

### Test placement
- Claude's discretion: place the test in `tests/backend/test_runner.py` (testing the full job-halts behavior) — consistent with how Phase 2 log-flush tests were added to `test_runner.py`
- The test should mock a Notion API error during `mark_notion_duplicates` and assert an exception is raised (not a warning logged)

### Claude's Discretion
- Exact exception type to re-raise (raw SDK exception or wrapped) — raw re-raise is fine unless there's a reason to wrap
- Whether to also add a test in `test_notion_push.py` — not required but acceptable if planner judges it useful

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Bug site
- `src/backend/runner.py` §"2a. Check Notion duplicates upfront" (lines ~176–188) — the try/except block to change

### Notion pre-check function
- `src/apt_scrape/notion_push.py` — `mark_notion_duplicates()` function (lines ~304–328) — the function called during pre-check

### Existing test patterns
- `tests/backend/test_runner.py` — existing runner test patterns (AsyncMock, patch, pytest.mark.asyncio)

### Prior phase pattern (reference)
- `tests/backend/test_runner.py::test_log_persists_on_mid_job_exception` — Phase 2 exception propagation test — same structural pattern needed here

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `AsyncMock`, `MagicMock`, `patch` from `unittest.mock` — already used in `test_runner.py` for mocking runner dependencies
- `pytest.mark.asyncio` — already in use for async runner tests

### Established Patterns
- Phase 2 pattern: log `[warn]` → changed to exception propagation; same pattern applies here but the message prefix should be `[error]`
- Runner tests use `patch("backend.runner.mark_notion_duplicates", new_callable=AsyncMock)` style — `mark_notion_duplicates` is imported inside the try block so patch target is `backend.runner.mark_notion_duplicates` or the import path used at call site

### Integration Points
- `runner.py` line ~181: `from apt_scrape.notion_push import mark_notion_duplicates` (imported inside the try block) — fix is in the `except` clause immediately after

</code_context>

<specifics>
## Specific Ideas

- Log message format: `[error] Notion pre-check failed: {e}` — mirrors the existing `[warn]` format but signals failure
- The `re-raise` should be a bare `raise` (re-raise original exception) to preserve the traceback

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 04-notion-fail-fast*
*Context gathered: 2026-03-16*
