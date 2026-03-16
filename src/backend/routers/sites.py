"""backend.routers.sites — Per-site config overrides (areas, selectors)."""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

import yaml
from apt_scrape.sites import config_to_dict, deep_merge, get_adapter, get_config_path, list_adapters

from backend.db import SiteConfigOverride, get_session
from sqlmodel import Session, select
from fastapi import Depends

router = APIRouter()

# Repo root: src/backend/routers/sites.py -> parent = routers, parent.parent = backend, parent.parent.parent = src, parent.parent.parent.parent = repo root
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CONFIG_DIR = _REPO_ROOT / "config"

# Resolve base adapter for variant site_ids (e.g. immobiliare-test1 -> immobiliare)
def resolve_base_site_id(site_id: str) -> str:
    """Return the base adapter id. If site_id is a variant (e.g. immobiliare-test1), return the adapter prefix."""
    adapters = list_adapters()
    if site_id in adapters:
        return site_id
    for base in adapters:
        if site_id.startswith(base + "-"):
            return base
    return site_id


def _read_areas_file(path: Path) -> list[str]:
    """Read area names from a text file (one per line, # comments ignored)."""
    if not path.exists():
        return []
    areas = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                areas.append(line)
    return areas


def _load_default_areas(base_site_id: str) -> list[str]:
    """Load default areas for this site: config/default_areas_{site}.txt, else config/default_areas.txt."""
    per_site = _CONFIG_DIR / f"default_areas_{base_site_id}.txt"
    if per_site.exists():
        areas = _read_areas_file(per_site)
        if areas:
            return areas
    return _read_areas_file(_CONFIG_DIR / "default_areas.txt")


def _get_overrides(site_id: str, session: Session) -> dict[str, Any]:
    row = session.get(SiteConfigOverride, site_id)
    if not row or not row.overrides:
        return {}
    return json.loads(row.overrides) if isinstance(row.overrides, str) else (row.overrides or {})


def _areas_for_site(base_site_id: str, overrides: dict[str, Any], session: Session) -> list[str]:
    """Return areas list for a site: overrides, then YAML, then default_areas.txt."""
    if overrides.get("areas") is not None and isinstance(overrides["areas"], list):
        return list(overrides["areas"])
    try:
        path = get_config_path(base_site_id)
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        if "area_map" in raw:
            return list(raw["area_map"].keys())
        if "areas" in raw and isinstance(raw["areas"], list):
            return list(raw["areas"])
    except Exception:
        pass
    return _load_default_areas(base_site_id)


def get_sites_list(session: Session) -> list[str]:
    """Return base site IDs plus any saved variant IDs (e.g. immobiliare-test1). Shared for list_sites and configs."""
    base_ids = list_adapters()
    rows = session.exec(select(SiteConfigOverride)).all()
    variant_ids = [r.site_id for r in rows if r.site_id and r.site_id not in base_ids]
    return base_ids + sorted(variant_ids)


@router.get("")
def list_sites(session: Session = Depends(get_session)) -> list[str]:
    """Return base site IDs plus any saved variant IDs (e.g. immobiliare-test1)."""
    return get_sites_list(session)


@router.get("/{site_id}/config")
def get_site_config(
    site_id: str,
    session: Session = Depends(get_session),
    split: bool = False,
) -> dict[str, Any]:
    """Return effective config (base + overrides merged).
    site_id can be a base (immobiliare) or variant (immobiliare-test1).
    If split=True, returns { base, overrides, effective }.
    effective always includes 'areas' (from overrides, YAML, or default_areas.txt).
    """
    base_site_id = resolve_base_site_id(site_id)
    if base_site_id not in list_adapters():
        raise HTTPException(404, f"Unknown site_id: {site_id}")
    adapter = get_adapter(base_site_id)
    base = config_to_dict(adapter.config)
    overrides = _get_overrides(site_id, session)
    effective = deep_merge(base, overrides) if overrides else dict(base)
    # Ensure effective always has 'areas' (used by Site Settings and dropdowns)
    if "areas" not in effective or not effective["areas"]:
        effective["areas"] = _areas_for_site(base_site_id, overrides, session)
    if split:
        return {"base": base, "overrides": overrides, "effective": effective}
    return effective


@router.get("/{site_id}/areas")
def get_site_areas(site_id: str, session: Session = Depends(get_session)) -> list[str]:
    """Return available areas (overrides, YAML, or config/default_areas.txt). Supports variant site_id."""
    base_site_id = resolve_base_site_id(site_id)
    if base_site_id not in list_adapters():
        raise HTTPException(404, f"Unknown site_id: {site_id}")
    overrides = _get_overrides(site_id, session)
    return _areas_for_site(base_site_id, overrides, session)


@router.put("/{site_id}/config")
def update_site_config(
    site_id: str,
    body: dict[str, Any],
    session: Session = Depends(get_session),
) -> dict[str, str]:
    """Merge partial overrides into stored overrides. site_id can be base or variant (e.g. immobiliare-test1)."""
    base_site_id = resolve_base_site_id(site_id)
    if base_site_id not in list_adapters():
        raise HTTPException(404, f"Unknown site_id: {site_id}")
    row = session.get(SiteConfigOverride, site_id)
    current = {}
    if row and row.overrides:
        current = json.loads(row.overrides) if isinstance(row.overrides, str) else (row.overrides or {})
    merged = deep_merge(current, body)
    if row:
        row.overrides = json.dumps(merged)
        session.add(row)
    else:
        session.add(SiteConfigOverride(site_id=site_id, overrides=json.dumps(merged)))
    session.commit()
    return {"status": "saved"}
