---
phase: 2
slug: job-runner-reliability
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-16
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio >= 0.23 |
| **Config file** | `pytest.ini` (asyncio_mode = auto, pythonpath = src) |
| **Quick run command** | `pytest tests/backend/test_runner.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/backend/test_runner.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** ~5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | RUNNER-01 | unit (structural) | `pytest tests/backend/test_runner.py -x` | ✅ existing file | ⬜ pending |
| 2-01-02 | 01 | 1 | RUNNER-02 | unit | `pytest tests/backend/test_runner.py::test_log_persists_on_mid_job_exception -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/backend/test_runner.py::test_log_persists_on_mid_job_exception` — new test function in existing file, covers RUNNER-02

*Framework and shared fixtures already exist — `pytest.ini`, `_make_config()` helper, DB setup in test_runner.py*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
