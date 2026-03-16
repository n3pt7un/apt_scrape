# apt_scrape — Reliability Milestone

## What This Is

A personal apartment scraping system that monitors Italian real estate sites (Immobiliare.it, Casa.it, Idealista.it), enriches listings with AI scoring via OpenRouter/LangGraph, and pushes curated results to Notion databases. Runs as a FastAPI backend + Streamlit dashboard, orchestrated via Docker Compose.

This milestone focuses on fixing four confirmed reliability and correctness bugs before the system handles higher load.

## Core Value

Listings land in Notion accurately, completely, and without silent data loss — every failure is visible and no error is swallowed.

## Requirements

### Validated

<!-- Shipped and confirmed working in the existing system -->

- ✓ User can create and run search configs for Italian real estate sites — existing
- ✓ Site adapters for Immobiliare.it, Casa.it, Idealista.it extract listings — existing
- ✓ Detail enrichment fetches rich fields (description, features, energy class) per listing — existing
- ✓ AI scoring evaluates listings against preferences.txt via LangGraph/OpenRouter — existing
- ✓ Notion push deduplicates and uploads listings to configured databases — existing
- ✓ APScheduler runs recurring scrape jobs on cron schedules — existing
- ✓ Streamlit dashboard monitors jobs, browses listings, edits preferences — existing
- ✓ Proxy rotation via NordVPN SOCKS5 with block detection — existing

### Active

<!-- Confirmed bugs being fixed in this milestone -->

- [ ] Browser reconnection is safe under concurrent detail enrichment batches (no race condition in `_ensure_browser()`)
- [ ] Job log buffer is guaranteed to flush even when an exception occurs mid-job
- [ ] LLM scoring failures are surfaced to the user — failed listings are logged and distinguishable from API failures vs parse failures
- [ ] Notion pre-check API errors cause job to fail fast rather than silently continuing to push potential duplicates
- [ ] Each fix is covered by a focused unit test to prevent regression

### Out of Scope

- Job cancellation mid-run — acknowledged missing feature, deferred to next milestone
- Database threading model migration (async SQLAlchemy) — larger refactor, not blocking
- Full test coverage overhaul (Notion integration tests, multi-site selector snapshots) — separate initiative
- Performance improvements (geocoding parallelization, analysis concurrency scaling) — not a current pain point
- Security hardening (Notion/proxy credential management) — no active risk, deferred

## Context

- The codebase has a thorough CONCERNS.md audit (generated 2026-03-16) that identified these issues
- Three bugs are confirmed observed in practice: browser disconnects, missing job logs, silent LLM scoring skips
- The Notion pre-check error suppression hasn't been seen but is a correctness risk worth closing
- Tech stack: Python 3.12, FastAPI, SQLModel/SQLite, Camoufox, LangGraph, Notion client, APScheduler, Streamlit

## Constraints

- **No breaking changes**: Fixes must not change public API contracts (router signatures, DB schema, CLI interface)
- **No new dependencies**: Use stdlib `asyncio.Lock` for the browser fix; no new packages
- **Test scope**: Unit tests only — no integration tests requiring live APIs (Notion, OpenRouter)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| asyncio.Lock for `_ensure_browser()` | Stdlib, zero overhead, correct fix for async race | — Pending |
| `finally` block for log flush | Simplest correct fix; no architectural change needed | — Pending |
| Distinguish parse vs API errors in LLM fallback | Enables targeted retry logic and meaningful user-facing logs | — Pending |
| Fail fast on Notion pre-check errors | Correctness over convenience — duplicates are worse than job failures | — Pending |

---
*Last updated: 2026-03-16 after initialization*
