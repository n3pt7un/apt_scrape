# Dashboard Improvements — Implementation Summary

**Date:** 2026-03-14  
**Plan:** `docs/superpowers/plans/2026-03-14-dashboard-improvements.md`  
**Spec:** `docs/superpowers/specs/2026-03-14-dashboard-improvements-design.md`

## What was implemented

### Backend

- **SearchConfig (db.py):** New columns `site_id`, `request_delay_sec`, `page_delay_sec`, `timeout_sec`. Migration `_migrate_searchconfig_20260314()` runs on startup for existing DBs (SQLite ALTER TABLE).
- **SiteConfigOverride (db.py):** New table for per-site overrides (site_id PK, overrides JSON).
- **Configs router:** `ConfigIn` extended with site_id, request_delay_sec, page_delay_sec, timeout_sec. Validation: `site_id` base must be in `list_adapters()` (variants like `immobiliare-test1` allowed). **GET /configs/sites** returns **GET /sites** (base + saved variants).
- **Sites router:** **GET /sites** returns base site IDs plus any saved variant IDs (e.g. `immobiliare-test1`). **GET /sites/{site_id}/config** supports base or variant `site_id`; effective config always includes `areas` (from overrides, YAML, or **config/default_areas.txt**). **GET /sites/{site_id}/config?split=True** returns `{ base, overrides, effective }`. **GET /sites/{site_id}/areas** uses same fallback (default_areas.txt). **PUT /sites/{site_id}/config** accepts variant `site_id` to create/update a test variant.
- **Runner:** Resolves base site (e.g. `immobiliare-test1` → `immobiliare`) for the adapter; loads overrides for the full `site_id` so variant overrides are used when a search config uses a variant.

### apt_scrape (minimal extension)

- **base.py:** `config_from_dict(d)`, `config_to_dict(config)`, `deep_merge(base, overrides)`. `load_config_from_yaml` refactored to use `config_from_dict`.
- **sites/__init__.py:** `get_adapter_with_overrides(site_id, overrides)`, `get_config_path(site_id)`. Adapters (Immobiliare, Casa, Idealista) accept optional `config: SiteConfig | None` in `__init__`.

### Frontend

- **1_Search_Configs.py:** Area dropdown from **GET /sites/{site_id}/areas** (full default list from backend or **api.DEFAULT_AREAS** fallback). Site dropdown includes base sites and saved variants (from **GET /configs/sites**).
- **2_Monitor.py:** Auto-refresh only when at least one job has `status == "running"`.
- **5_Site_Settings.py:** Full config view: **GET /sites/{id}/config?split=True** shows Base (built-in), Your overrides, and Effective (merged) in expanders. Editable: areas (one per line), search_wait_selector, detail_wait_selector, plus optional JSON overrides. **Save overrides** → PUT current site. **Save as test variant** → enter name (e.g. `test1`), PUT to `immobiliare-test1` (or `casa-test1` etc.); variant appears in Site dropdown and can be used in Search Configs and jobs.

### Tests

- **test_db.py:** Assert new SearchConfig defaults (site_id, request_delay_sec, page_delay_sec, timeout_sec).
- **test_configs.py:** test_create_config_with_site_and_delays, test_create_config_invalid_site_id_returns_422, test_get_configs_sites.
- **test_runner.py:** Mock `get_adapter_with_overrides` (was `get_adapter`).
- **test_sites.py:** list_sites, get_site_config, get_site_areas (default areas), put_site_config, site_not_found, **test_site_variant_save_and_list** (PUT variant, list includes it, GET variant config/areas).

## Verification

- `python -m pytest tests/backend/ -v` — 26 passed.
- Backend smoke: `/health`, `/configs/sites`, `/sites`, `/sites/immobiliare/areas` return expected JSON.

## How to run

See [docs/running-locally.md](running-locally.md). No Docker; use `./scripts/run_backend.sh` and `./scripts/run_frontend.sh`.
