---
phase: 01-browser-reliability
plan: 01
subsystem: browser-management
tags:
  - concurrency
  - pytest
  - bugfix
dependency_graph:
  requires: []
  provides:
    - Thread-safe _ensure_browser method
  affects:
    - src/apt_scrape/server.py
tech_stack:
  added:
    - asyncio.Lock
  patterns:
    - async concurrency testing with pytest
key_files:
  created:
    - tests/backend/test_server.py
  modified:
    - src/apt_scrape/server.py
metrics:
  tasks_completed: 2
  files_modified: 2
  duration: "10m"
key_decisions:
  - Phase 1: Use asyncio.Lock (stdlib) for `_ensure_browser()` — zero new dependencies, correct fix for async race
---

# Phase 01 Plan 01: Fix async race condition in `_ensure_browser()` Summary

**Thread-safe `BrowserManager` initialization using `asyncio.Lock()`.**

## Implementation Details

Added `self._browser_lock = asyncio.Lock()` in `BrowserManager.__init__`. Wrapped the initialization block inside `_ensure_browser` with `async with self._browser_lock:`.

Added test `test_concurrent_ensure_browser` inside `tests/backend/test_server.py` to catch any races where multiple components attempt to request a browser connection at the identical moment.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED