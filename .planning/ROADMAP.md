# Roadmap: apt_scrape Reliability Milestone

## Overview

Four targeted bug fixes, each with a regression test, delivered in dependency order. Browser reconnect safety lands first (it gates detail enrichment), then job log flushing (independent runner fix), then LLM scoring observability (surfacing silent failures), then Notion fail-fast behavior (correctness guarantee). Each phase delivers one completely fixed subsystem with a test that locks in the behavior.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Browser Reliability** - Fix async race condition in `_ensure_browser()` with asyncio.Lock and cover with a concurrency test
- [x] **Phase 2: Job Runner Reliability** - Guarantee job log buffer flushes in a `finally` block and cover with a test that validates pre-exception messages persist (completed 2026-03-16)
- [ ] **Phase 3: LLM Scoring Observability** - Distinguish parse vs API failures and log every skipped listing by ID, covered by separate failure-path tests
- [ ] **Phase 4: Notion Fail-Fast** - Cause Notion pre-check API errors to raise rather than silently continue, covered by a test that verifies the exception

## Phase Details

### Phase 1: Browser Reliability
**Goal**: Concurrent detail enrichment batches can never cause a double-reconnect or browser collision
**Depends on**: Nothing (first phase)
**Requirements**: BRWSR-01, BRWSR-02
**Success Criteria** (what must be TRUE):
  1. Multiple concurrent calls to `_ensure_browser()` result in exactly one reconnect, not multiple simultaneous ones
  2. The asyncio.Lock is held for the duration of the close/reconnect cycle so no caller can interleave
  3. Unit test passes that spawns concurrent callers and asserts only one reconnect occurred
**Plans**: 1 plan

Plans:
- [ ] 01-01-PLAN.md — Fix async race condition in `_ensure_browser()` with asyncio.Lock and concurrency test

### Phase 2: Job Runner Reliability
**Goal**: Job log messages are always persisted to the database even when an exception aborts the job mid-run
**Depends on**: Phase 1
**Requirements**: RUNNER-01, RUNNER-02
**Success Criteria** (what must be TRUE):
  1. Log messages written before an exception are present in the Job record after the job fails
  2. The flush call lives in a `finally` block so no exception path can bypass it
  3. Unit test simulates a mid-job exception and asserts pre-exception log lines are in the database record
**Plans**: 1 plan

Plans:
- [ ] 02-01-PLAN.md — Move _flush_log() to finally block in runner.py; write failing test first (BaseException path), then apply fix

### Phase 3: LLM Scoring Observability
**Goal**: Users can tell which listings were skipped by AI scoring and why — API failure vs parse failure
**Depends on**: Phase 2
**Requirements**: LLM-01, LLM-02, LLM-03
**Success Criteria** (what must be TRUE):
  1. When the LLM API call fails, the error is logged with a message and exception type distinct from a parse failure
  2. When LLM response parsing fails, the error is logged with a message and exception type distinct from an API failure
  3. Every listing that fails AI scoring is logged by its listing ID so the user can identify it in logs
  4. Unit tests cover the parse failure path and API failure path separately and assert distinct exception types and log messages
**Plans**: 1 plan

Plans:
- [ ] 03-01-PLAN.md — Add LLMAPIError/LLMParseError exception hierarchy, module logger, restructure _analyse_node and _score_one, write caplog unit tests (TDD)

### Phase 4: Notion Fail-Fast
**Goal**: A Notion pre-check API error stops the job immediately rather than risking duplicate pushes
**Depends on**: Phase 3
**Requirements**: NOTION-01, NOTION-02
**Success Criteria** (what must be TRUE):
  1. When the Notion pre-check call returns an API error, the job raises an exception and halts — no listings are pushed
  2. The error is not swallowed as a warning; it propagates as a job-level failure visible in job logs
  3. Unit test mocks a Notion API error during pre-check and asserts an exception is raised (not a warning logged)
**Plans**: 1 plan

Plans:
- [ ] 04-01: Change Notion pre-check error handling to raise and write exception-assertion unit test

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Browser Reliability | 0/TBD | Not started | - |
| 2. Job Runner Reliability | 1/1 | Complete   | 2026-03-16 |
| 3. LLM Scoring Observability | 0/1 | Not started | - |
| 4. Notion Fail-Fast | 0/TBD | Not started | - |
