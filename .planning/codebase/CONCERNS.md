# Codebase Concerns

**Analysis Date:** 2026-03-16

## Tech Debt

### Database Threading Model (Medium Impact)

**Issue:** SQLite with `check_same_thread=False` in FastAPI context
- **Files:** `backend/db.py`, `backend/runner.py`, `backend/scheduler.py`
- **Impact:** Threading model bypassed for FastAPI's threadpool executor. While mitigated with careful Session management, this is a fragile pattern that can silently corrupt data if a Session is reused across threads
- **Current mitigation:** All DB code uses context-manager pattern (`with Session(engine) as session`)
- **Fix approach:** Migrate to async SQLAlchemy 2.0+ with `AsyncSession` to properly handle async/await without thread safety issues. This would eliminate the need for `check_same_thread=False`

### Untyped Configuration Merging

**Issue:** Site config overrides loaded as untyped dicts with minimal validation
- **Files:** `backend/runner.py` (lines 92-95), `backend/routers/sites.py`
- **Impact:** Malformed YAML overrides can silently corrupt site adapters; no schema validation before use
- **Current mitigation:** Only affects non-critical overrides (areas, selectors); defaults always work
- **Fix approach:** Implement Pydantic schema for `SiteConfigOverride.overrides` with runtime validation before adapter construction

### Error Suppression in Notion Pre-check

**Issue:** Silent failure when Notion API errors occur during deduplication check
- **Files:** `backend/runner.py` (lines 186-187)
- **Impact:** Job logs show warning but continue enrichment on listings that may already be in Notion, causing duplicate pushes if followed by another `auto_notion_push` job
- **Fix approach:** Fail fast on Notion API errors during pre-check; don't assume dupes are safe to skip

## Known Issues

### Browser Reconnection Race Condition

**Issue:** Browser can reconnect while a fetch is in progress, causing handler closed errors
- **Symptoms:** Occasional "targetclosederror" or "handler is closed" exceptions during concurrent detail fetches
- **Files:** `apt_scrape/server.py` (lines 138-142, 333-339)
- **Trigger:** Long-running jobs with 50+ detail enrichments + proxy rotation
- **Current mitigation:** Catches `targetclosederror` string and reconnects on next attempt
- **Workaround:** Reduce `detail_concurrency` if experiencing frequent disconnects
- **Root cause:** `_ensure_browser()` can be called by multiple concurrent batch fetches; no lock prevents simultaneous close/reconnect cycles

### Geocoding Timeout on Large Batches

**Issue:** Nominatim requests can timeout during bulk Notion pushes with 100+ unique addresses
- **Symptoms:** "Geocoding failed for '{address}': [timeout]" appearing in logs repeatedly
- **Files:** `apt_scrape/notion_push.py` (line 96-112)
- **Impact:** Listings pushed without geocoded coordinates; map feature degrades silently
- **Current behavior:** In-process cache per run only; repeated Notion pushes re-geocode same addresses
- **Workaround:** Cache geocoding results to persistent storage or database between runs
- **Upstream:** Nominatim free tier has rate limits (1 req/sec); concurrent requests share client

### LLM Fallback JSON Parsing Fragile

**Issue:** When structured output fails, JSON parsing from fallback raw text response can fail silently
- **Files:** `apt_scrape/analysis.py` (lines 243-260)
- **Symptoms:** Listing gets skipped entirely from AI scoring without error visible to user
- **Current mitigation:** Catches all exceptions but doesn't distinguish parsing failure from API failure
- **Fix approach:** Implement retry logic with exponential backoff; log which listings failed to parse

### Streaming Logs Buffer Not Flushed on Exception

**Issue:** Job logs can lose final messages if exception occurs between buffer write and database commit
- **Files:** `backend/runner.py` (lines 287-290)
- **Impact:** Last error message may not appear in `/jobs/{id}` endpoint response
- **Current mitigation:** `_flush_log()` called on line 284, but exception on line 288 can occur before flush on partial-exception paths
- **Fix approach:** Wrap entire try block with finally to guarantee flush

## Security Considerations

### API Key Exposure via Raw JSON Storage

**Risk:** All listing JSON stored in SQLite raw_json field including any embedded API keys if present in page source
- **Files:** `backend/runner.py` (line 252), `backend/db.py` (Listing.raw_json)
- **Current mitigation:** Raw JSON comes from HTML parsing, not API responses; site adapter selectors don't capture headers
- **Recommendations:** Add sanitization to strip script tags and data URIs before storing raw_json

### Notion Database IDs in Environment Variables

**Risk:** Notion API key and three database IDs stored as plaintext env vars; if `.env` leaked, attacker can read/write all three databases
- **Files:** `.env` (contains NOTION_API_KEY, NOTION_APARTMENTS_DB_ID, NOTION_AREAS_DB_ID, NOTION_AGENCIES_DB_ID)
- **Current mitigation:** `.env` in .gitignore; not committed to repo
- **Recommendations:**
  - Implement API key rotation for Notion integration
  - Add Notion integration permissions to be database-specific, not workspace-wide (if available)
  - Audit Notion API audit logs for unauthorized access

### Proxy Credentials in Environment

**Risk:** NordVPN credentials stored as plaintext in env vars for SOCKS5 relay
- **Files:** `apt_scrape/server.py` (lines 76-84)
- **Current mitigation:** Used only locally in Docker; credentials are NordVPN service account (not personal login)
- **Recommendations:** Switch to certificate-based auth if NordVPN supports it; rotate service account periodically

## Performance Bottlenecks

### Sequential Geocoding During Notion Push

**Problem:** Notion push waits for geocoding to complete per listing before creating page
- **Files:** `apt_scrape/notion_push.py` (lines 217-250)
- **Cause:** `await _geocode_address(address)` called inside loop per listing
- **Impact:** 100 listings = 100 sequential Nominatim requests; takes 100+ seconds even with 1 req/sec limit
- **Improvement path:**
  1. Extract all unique addresses first
  2. Geocode all in parallel (respecting rate limit via semaphore)
  3. Store results in dict, reuse when creating pages

### Analysis Concurrency Hard-limited to 5

**Problem:** `ANALYSIS_CONCURRENCY` env var (default 5) bottlenecks AI scoring for large jobs
- **Files:** `apt_scrape/analysis.py` (line 363), `backend/runner.py` (line 104)
- **Cause:** OpenRouter API key rate limit shared across all concurrent requests
- **Impact:** 1000 listings = 200 serial batches of 5; takes 5+ minutes even with 1 token/sec inference
- **Improvement path:** Monitor OpenRouter rate limit headers; scale concurrency up to actual tier limit

### Browser Page Load Timeout (15s) on Slow Networks

**Problem:** Detail page load waits 15 seconds before timing out; on slow connections, legitimate pages fail
- **Files:** `apt_scrape/server.py` (line 472), `backend/runner.py` (line 139)
- **Current values:** `search_wait_timeout=15000` ms, `detail_wait_timeout=45000` ms (default implied)
- **Impact:** Legitimate listings in job marked as errors; `detail_concurrency` waits idle for timeout
- **Improvement path:**
  - Make timeout configurable per site (some sites load faster than others)
  - Implement adaptive timeout based on first N requests' actual load times

## Fragile Areas

### CSS Selector Brittleness

**Files:** `apt_scrape/sites/immobiliare.py`, `apt_scrape/sites/casa.py`, `apt_scrape/sites/idealista.py`
- **Why fragile:** All selector extraction relies on CSS classes and HTML structure that real estate sites change monthly. No DOM parsing abstraction layer
- **Safe modification:**
  1. Always use `SelectorGroup` with 3+ fallback selectors per field (specific → generic → broadest)
  2. Add site-specific tests with real HTML snapshot (commit `tests/fixtures/immobiliare_search_page.html`)
  3. Implement selector validation in adapter init to catch silent failures early
- **Test coverage:** `tests/test_immobiliare.py` has parsing tests but uses cached HTML; no snapshot versioning

### LLM Structured Output Dependency

**Files:** `apt_scrape/analysis.py` (lines 218, 239)
- **Why fragile:** Depends on OpenRouter + vendor's model maintaining structured output format. No format validation before using fields
- **Safe modification:**
  1. Add Pydantic field validation on `NotionApartmentFields` model with coercion (e.g., `ai_score` must be 0-100)
  2. Implement schema-less fallback that extracts minimum viable fields from raw text if structured output fails
  3. Log which listings got fallback treatment for monitoring
- **Test coverage:** `tests/test_analysis.py` mocks LLM response; no tests of actual OpenRouter API

### Notion Schema Assumption

**Files:** `apt_scrape/notion_push.py` (lines 128-135)
- **Why fragile:** Assumes Notion database has specific property names and types. If user edits schema, push breaks silently
- **Safe modification:**
  1. Add property existence checks before creating/updating pages
  2. Implement property name mapping config (e.g., "Title" → custom name if renamed)
  3. Validate field types match expectations (e.g., "AI Score" must be number, not text)
- **Test coverage:** No integration tests with actual Notion API; only mocked tests

### Multi-area CSV Concatenation Without Headers

**Files:** `backend/runner.py` (lines 123-160)
- **Why fragile:** When job scrapes multiple areas, `all_listings` concatenates raw dicts from different areas/property-types without normalizing order
- **Safe modification:**
  1. Ensure all listing dicts have same key set before concatenating
  2. Add test case for multi-area jobs to verify output consistency
- **Test coverage:** Integration tests only test single-area scrapes

## Scaling Limits

### Single Camoufox Browser Instance

**Current capacity:** ~5 concurrent detail fetches before context switch overhead kills throughput
- **Limit:** Single browser context shared across all detail enrichment batches; concurrent pages compete for same browser process
- **Scaling path:**
  1. Implement browser pool (e.g., 3 browser instances for 15 concurrent fetches)
  2. Rebalance load across pool using asyncio Queue
  3. Monitor memory per browser instance (each ~50-100 MB)

### SQLite Database Contention

**Current capacity:** ~10 concurrent Session writes before lock timeouts
- **Limit:** SQLite single-writer model; no WAL mode enabled (MEMORY journal mode avoids .db-journal corruption but disables concurrent writers)
- **Scaling path:**
  1. Enable WAL mode (PRAGMA journal_mode=WAL) and test on target filesystems
  2. Batch DB writes (currently scattered across runner, enrichment, push steps)
  3. Consider PostgreSQL if multi-instance deployment needed

### Notion API Rate Limit

**Current capacity:** ~1 page create/update per second; 100 listings = 100+ seconds
- **Limit:** Notion API tier-dependent; free tier ~3 req/sec, paid tiers higher
- **Scaling path:**
  1. Implement backoff-retry with jitter for 429 responses
  2. Batch page creates using Notion batch endpoint (if available)
  3. Add `NOTION_RATE_LIMIT` env var to configure concurrency

## Dependencies at Risk

### Camoufox Browser Lifecycle Tied to FastAPI Lifespan

**Risk:** Browser singleton created in `apt_scrape.server` but only imported when backend starts
- **Impact:** If backend crashes, browser process can become orphaned; multiple backend restarts leak browser processes
- **Mitigation:** Current code closes browser on lifespan shutdown (`backend/main.py` line 25)
- **Migration plan:** Switch to context manager pattern where browser is created per job (not singleton) for better isolation

### OpenRouter API Model Availability

**Risk:** Default model `google/gemini-3.1-flash-lite-preview` may be deprecated or throttled
- **Impact:** If model becomes unavailable, all AI scoring fails unless `OPENROUTER_MODEL` env var changed
- **Current fallback:** Hard-coded fallback in code (line 195) but requires code change
- **Migration plan:**
  1. Implement model negotiation endpoint that queries OpenRouter `/models` and picks best available
  2. Store chosen model in database so jobs are reproducible
  3. Alert user when fallback model is used

### Notion Client Library Updates

**Risk:** `notion_client` AsyncClient is young; breaking changes common in minor versions
- **Impact:** Version bump can break push pipeline silently
- **Current mitigation:** Requirements.txt pins version but no test on actual Notion API
- **Migration plan:**
  1. Implement integration tests against Notion sandbox database (requires API key)
  2. Add pre-release testing in CI (e.g., test weekly against latest notion_client)
  3. Implement adapter pattern for Notion client to reduce coupling

## Missing Critical Features

### Job Cancellation

**Problem:** No way to stop a running job short of killing backend process
- **Blocks:** Long-running jobs (1000+ listings) can't be interrupted mid-enrichment
- **Impact:** UI shows job as "running" forever; user must kill backend
- **Implementation:** Add cancellation token to job context; check in detail enrichment loop

### Selector Debugging Tools

**Problem:** When a selector breaks, no built-in way to test new selectors without manual HTML inspection
- **Blocks:** Site adapter maintenance; fixing broken selectors requires Python code change + restart
- **Impact:** Downtime when site changes HTML
- **Implementation:** Add `/debug/test-selector` endpoint that takes site, URL, and CSS selector, returns parsed result

### Duplicate Detection Across Notion Databases

**Problem:** Can't distinguish new listing in Notion from re-run of old listing pushed twice
- **Blocks:** Monthly archive use case; users can't tell if listing is from current month or old scrape
- **Implementation:** Add `_last_seen` timestamp to listing; update when re-encountered in Notion

### Preferences Editing UI Validation

**Problem:** Preferences file format not documented; invalid preferences silently cause LLM failures
- **Blocks:** Non-technical users can't safely edit preferences
- **Implementation:** Add schema validator for preferences; show helpful error on invalid format

## Test Coverage Gaps

### Notion Integration Tests Entirely Mocked

**What's not tested:** Real Notion API behavior with actual database (schema changes, rate limiting, 403 errors)
- **Files:** `tests/test_notion_push.py` (all mocks)
- **Risk:** New Notion features (e.g., database relations) break silently in production
- **Priority:** High (Notion push is user-facing feature)
- **Implementation:** Use Notion sandbox or throw-away test workspace; validate schema before first push

### Multi-site Selector Parsing

**What's not tested:** Casa.it and Idealista.it selectors with real pages; only Immobiliare has snapshot tests
- **Files:** `tests/test_immobiliare.py` (immobiliare only), no `test_casa.py` or `test_idealista.py`
- **Risk:** Casa/Idealista adapters silently break when sites change HTML
- **Priority:** High (two of three sites untested)
- **Implementation:** Commit HTML snapshots for each site (update quarterly when selectors change)

### Proxy Rotation Error Paths

**What's not tested:** Behavior when proxy server is actually unreachable or returns 407
- **Files:** `apt_scrape/server.py` (proxy rotation logic) — no tests
- **Risk:** Proxy rotation silently falls back to no proxy, exposing real IP
- **Priority:** Medium (risk only if NordVPN credential leak)
- **Implementation:** Mock SOCKS5 connection failures; verify rotation retry logic exhausts all proxies before raising error

### Job Lifecycle Edge Cases

**What's not tested:** Job recovery if backend crashes mid-enrichment; concurrent job scheduling edge cases
- **Files:** `backend/runner.py`, `backend/scheduler.py` — no failure injection tests
- **Risk:** Data corruption on restart; duplicate job scheduling if scheduler thread crashes
- **Priority:** Medium (rare in production but severe when occurs)
- **Implementation:** Add chaos engineering tests; simulate backend kill at various job stages

---

*Concerns audit: 2026-03-16*
