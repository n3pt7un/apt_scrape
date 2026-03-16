# Phase 1: Browser Reliability - Research

**Researched:** 2026-03-16
**Domain:** Python AsyncIO & Playwright/Camoufox Browser Concurrency
**Confidence:** HIGH

<user_constraints>
## User Constraints (from Phase description and STATE.md)

### Locked Decisions
- Use `asyncio.Lock` (stdlib) for `_ensure_browser()` — zero new dependencies, correct fix for async race.
- Concurrent detail enrichment batches can never cause a double-reconnect or browser collision.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| BRWSR-01 | `_ensure_browser()` uses an asyncio.Lock so concurrent batches cannot collide | Confirmed `BrowserManager` needs a `_browser_lock = asyncio.Lock()` wrapped around its connection logic. |
| BRWSR-02 | Unit test verifies concurrent calls don't trigger simultaneous reconnects | Addressed via asyncio unit testing with mocked `AsyncCamoufox`. |
</phase_requirements>

## Summary

The `BrowserManager` instantiated at the module level in `src/apt_scrape/server.py` handles concurrent asynchronous tasks that fetch listing details. Its lazy initialization function, `_ensure_browser()`, does not hold a lock. Consequently, if the browser is closing/reconnecting, multiple incoming detail-fetching tasks will detect it as closed or `None` and attempt to start `AsyncCamoufox` simultaneously, leading to resource collisions (two Chromium instances spawned concurrently).

**Primary recommendation:** Introduce a generic `self._browser_lock = asyncio.Lock()` in `BrowserManager.__init__()` and wrap the entirety of the browser allocation and context creation logic inside `_ensure_browser()` within an `async with self._browser_lock:` block.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `asyncio` | stdlib | Async orchestration | Built-in Python standard library |
| `pytest-asyncio` | current | Test runner | Industry standard for async Python regression tests |
| `unittest.mock` | stdlib | Mocking browser behavior | Sufficient for asserting `__aenter__` call counts |

**Installation:** None required via package manager, components are already built-in or in the existing environment.

## Architecture Patterns

### Recommended Project Structure
Testing the module-level `browser` object logic belongs in `tests/backend/test_server.py`.
```
src/apt_scrape/
└── server.py         # Modified file handling _ensure_browser locking
tests/backend/
└── test_server.py    # New file for BRWSR-02 concurrency unit tests
```

### Pattern 1: Async Resource Instantiation Locking
**What:** Guarding a singleton async resource instantiation.
**When to use:** When a single module-level or global manager provides an async resource shared by concurrent tasks.
**Example:**
```python
async def _ensure_browser(self) -> None:
    async with self._browser_lock:
        if self._browser is not None:
            if not self._browser.is_connected():
                logger.warning("Browser disconnected unexpectedly. Cleaning up...")
                await self.close()

        if self._browser is not None:
            return
        
        # Safe spawn logic here...
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| In-flight request tracking | Custom boolean flags (`_is_starting = True`) | `asyncio.Lock` | Booleans yield control and don't park waiting coroutines properly; locks safely queue them. |

## Common Pitfalls

### Pitfall 1: Checking State Outside the Lock
**What goes wrong:** Fast-pathing the check before acquiring the lock causes a Time-Of-Check to Time-Of-Use (TOCTOU) bug.
**Why it happens:** Attempting to avoid the lock acquisition overhead if `self._browser` exists.
**How to avoid:** If doing a double-checked locking pattern, the check mechanism must strictly block inside the lock when mutating, and checking if it's connected might `await`, allowing a yield context. The safest is to acquire the lock *before* checking `.is_connected()` or mutating state.

## Code Examples

Verified patterns from official sources:

### Awaiting concurrent mock execution test
```python
import asyncio
from unittest.mock import AsyncMock, patch

async def test_concurrent_ensure_browser():
    manager = BrowserManager()
    
    with patch('camoufox.async_api.AsyncCamoufox.__aenter__', new_callable=AsyncMock) as mock_aenter:
        # spawn 5 concurrent calls
        tasks = [manager._ensure_browser() for _ in range(5)]
        await asyncio.gather(*tasks)
        
        # lock should ensure exactly 1 instantiation
        mock_aenter.assert_awaited_once()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Custom boolean locks | `asyncio.Lock` | Python 3 | Provides native, queue-managed resource contention rather than infinite sleep loops and races. |

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | None — see Wave 0 gaps |
| Quick run command | `pytest tests/backend/test_server.py -k test_browser_concurrency` |
| Full suite command | `pytest tests/` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| BRWSR-02 | Verifies concurrent `_ensure_browser` calls don't double spawn | unit | `pytest tests/backend/test_server.py -k test_concurrent_ensure_browser -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/backend/test_server.py -k test_concurrent_ensure_browser -x`
- **Per wave merge:** `pytest tests/`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/backend/test_server.py` — covers BRWSR-02

## Sources

### Primary (HIGH confidence)
- `STATE.md`, `REQUIREMENTS.md` - Context7 parsed requirements
- Python official documentation for `asyncio.Lock` 

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - `asyncio` is the built-in and active standard for this task.
- Architecture: HIGH - Confirmed via parsing `BrowserManager.__init__` in the existing project.
- Pitfalls: HIGH - Double-check locking and early state mutation without lock yield are standard async concurrency traps.

**Research date:** 2026-03-16
**Valid until:** Late 2026 (stable python concurrency model)
