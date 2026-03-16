# Requirements: apt_scrape Reliability Milestone

**Defined:** 2026-03-16
**Core Value:** Listings land in Notion accurately, completely, and without silent data loss — every failure is visible and no error is swallowed.

## v1 Requirements

Requirements for this reliability milestone. Each maps to a roadmap phase.

### Browser Reliability

- [x] **BRWSR-01**: `_ensure_browser()` uses an asyncio.Lock so concurrent detail enrichment batches cannot collide during browser close/reconnect cycles
- [x] **BRWSR-02**: Unit test verifies that concurrent calls to `_ensure_browser()` do not trigger simultaneous reconnects

### Job Runner Reliability

- [x] **RUNNER-01**: Job log buffer is flushed in a `finally` block so final error messages always persist to the database even if an exception occurs mid-job
- [x] **RUNNER-02**: Unit test verifies that log messages written before an exception are present in the Job record

### LLM Scoring Reliability

- [x] **LLM-01**: LLM fallback path distinguishes parse failures from API failures with distinct log messages and exception types
- [x] **LLM-02**: Listings that fail AI scoring are logged by listing ID so users can identify which ones were skipped
- [x] **LLM-03**: Unit test covers parse failure path and API failure path separately

### Notion Integration Reliability

- [ ] **NOTION-01**: Notion pre-check API errors cause the job to fail fast rather than silently continuing to push potential duplicates
- [ ] **NOTION-02**: Unit test verifies that a Notion API error during pre-check raises an exception (not a warning)

## v2 Requirements

Deferred to future milestones. Tracked but not in current roadmap.

### Missing Critical Features

- **FEAT-01**: User can cancel a running job without killing the backend process
- **FEAT-02**: `/debug/test-selector` endpoint lets user test CSS selectors without a code change

### Test Coverage Expansion

- **TEST-01**: Notion integration tests against real/sandbox Notion API (schema changes, rate limiting, 403 errors)
- **TEST-02**: Casa.it and Idealista.it selector parsing tests with HTML snapshots
- **TEST-03**: Proxy rotation error path tests (407, unreachable SOCKS5)
- **TEST-04**: Job lifecycle chaos tests (backend kill mid-enrichment)

### Tech Debt

- **DEBT-01**: Migrate to async SQLAlchemy 2.0+ AsyncSession to eliminate `check_same_thread=False`
- **DEBT-02**: Pydantic schema validation for `SiteConfigOverride.overrides` before adapter construction

## Out of Scope

| Feature | Reason |
|---------|--------|
| Job cancellation | Requires significant architectural work; deferred to next milestone |
| Database threading migration | Larger refactor; not blocking current reliability fixes |
| Performance improvements (geocoding, analysis concurrency) | Not a current pain point |
| Security credential hardening | No active risk identified; deferred |
| Browser pool scaling | Scaling concern, not reliability concern for current load |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| BRWSR-01 | Phase 1 | Complete |
| BRWSR-02 | Phase 1 | Complete |
| RUNNER-01 | Phase 2 | Complete |
| RUNNER-02 | Phase 2 | Complete |
| LLM-01 | Phase 3 | Complete |
| LLM-02 | Phase 3 | Complete |
| LLM-03 | Phase 3 | Complete |
| NOTION-01 | Phase 4 | Pending |
| NOTION-02 | Phase 4 | Pending |

**Coverage:**
- v1 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-16*
*Last updated: 2026-03-16 after roadmap creation*
