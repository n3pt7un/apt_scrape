"""backend.routers.configs — CRUD for search_configs."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from backend.db import SearchConfig, get_session
from backend import scheduler

router = APIRouter()


def _validate_site_id(site_id: str) -> None:
    from backend.routers.sites import resolve_base_site_id
    from apt_scrape.sites import list_adapters
    base = resolve_base_site_id(site_id)
    if base not in list_adapters():
        raise HTTPException(422, f"Invalid site_id. Base must be one of: {list_adapters()}")


class ConfigIn(BaseModel):
    name: str
    city: str
    area: Optional[str] = None
    operation: str = "affitto"
    property_type: str = "appartamenti"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_sqm: Optional[int] = None
    min_rooms: Optional[int] = None
    start_page: int = 1
    end_page: int = 10
    schedule_days: list[str] = []
    schedule_time: str = "08:00"
    detail_concurrency: int = 5
    vpn_rotate_batches: int = 3
    auto_analyse: bool = True
    auto_notion_push: bool = False
    enabled: bool = True
    site_id: str = "immobiliare"
    request_delay_sec: float = 2.0
    page_delay_sec: float = 0.0
    timeout_sec: Optional[int] = None


def _to_response(cfg: SearchConfig) -> dict:
    d = cfg.model_dump()
    d["schedule_days"] = json.loads(cfg.schedule_days or "[]")
    return d


@router.get("")
def list_configs(session: Session = Depends(get_session)):
    return [_to_response(c) for c in session.exec(select(SearchConfig)).all()]


@router.get("/sites")
def list_config_sites(session: Session = Depends(get_session)):
    """Return base and variant site IDs for the site selectbox (e.g. immobiliare, immobiliare-test1)."""
    from backend.routers.sites import get_sites_list
    return get_sites_list(session)


@router.post("", status_code=201)
def create_config(data: ConfigIn, session: Session = Depends(get_session)):
    _validate_site_id(data.site_id)
    cfg = SearchConfig(**{**data.model_dump(), "schedule_days": json.dumps(data.schedule_days)})
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    scheduler.reload_config(cfg.id)
    return _to_response(cfg)


@router.get("/{config_id}")
def get_config(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    return _to_response(cfg)


@router.put("/{config_id}")
def update_config(config_id: int, data: ConfigIn, session: Session = Depends(get_session)):
    _validate_site_id(data.site_id)
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    for k, v in data.model_dump().items():
        if k == "schedule_days":
            setattr(cfg, k, json.dumps(v))
        else:
            setattr(cfg, k, v)
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    scheduler.reload_config(cfg.id)
    return _to_response(cfg)


@router.delete("/{config_id}", status_code=204)
def delete_config(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    session.delete(cfg)
    session.commit()
    scheduler.reload_config(config_id)
    return Response(status_code=204)


@router.patch("/{config_id}/toggle")
def toggle_config(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    cfg.enabled = not cfg.enabled
    session.add(cfg)
    session.commit()
    session.refresh(cfg)
    scheduler.reload_config(cfg.id)
    return _to_response(cfg)


@router.post("/{config_id}/run")
async def run_config_now(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    job_id = scheduler.trigger_now(config_id)
    return {"job_id": job_id}
