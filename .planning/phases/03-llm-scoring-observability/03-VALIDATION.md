---
phase: 3
slug: llm-scoring-observability
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-16
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pytest-asyncio >= 0.23 |
| **Config file** | `pytest.ini` (asyncio_mode = auto, pythonpath = src) |
| **Quick run command** | `pytest tests/test_analysis.py -x` |
| **Full suite command** | `pytest tests/ -x` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `pytest tests/test_analysis.py -x`
- **After every plan wave:** Run `pytest tests/ -x`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 3-01-01 | 01 | 1 | LLM-01 | unit | `pytest tests/test_analysis.py::test_api_failure_logs_distinct_message -x` | ❌ W0 | ⬜ pending |
| 3-01-02 | 01 | 1 | LLM-01 | unit | `pytest tests/test_analysis.py::test_parse_failure_logs_distinct_message -x` | ❌ W0 | ⬜ pending |
| 3-01-03 | 01 | 1 | LLM-02 | unit | `pytest tests/test_analysis.py::test_api_failure_logs_distinct_message tests/test_analysis.py::test_parse_failure_logs_distinct_message -x` | ❌ W0 | ⬜ pending |
| 3-01-04 | 01 | 1 | LLM-03 | unit | `pytest tests/test_analysis.py -x` | ✅ partial | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_analysis.py::test_api_failure_logs_distinct_message` — stub for LLM-01 (API path) + LLM-02
- [ ] `tests/test_analysis.py::test_parse_failure_logs_distinct_message` — stub for LLM-01 (parse path) + LLM-02

*Framework and shared fixtures already exist — `pytest.ini`, `LISTING` fixture in test_analysis.py, `asyncio_mode = auto`*

---

## Manual-Only Verifications

*All phase behaviors have automated verification.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
