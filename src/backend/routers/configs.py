"""backend.routers.configs — CRUD for search_configs."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func
from sqlmodel import Session, select

from backend.db import Job, Listing, SearchConfig, get_session
from backend import scheduler

router = APIRouter()


def _validate_site_id(site_id: str) -> None:
    from backend.routers.sites import resolve_base_site_id
    from apt_scrape.sites import list_adapters
    base = resolve_base_site_id(site_id)
    if base not in list_adapters():
        raise HTTPException(422, f"Invalid site_id. Base must be one of: {list_adapters()}")


WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class ConfigIn(BaseModel):
    """Validated config payload: a bad schedule or page range is a 422, never a stored row
    that makes the scheduler (or the next backend start) fail."""
    name: str
    city: str
    area: Optional[str] = None
    operation: str = "affitto"
    property_type: str = "appartamenti"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    min_sqm: Optional[int] = None
    min_rooms: Optional[int] = None
    start_page: int = Field(1, ge=1)
    end_page: int = Field(10, ge=1)
    schedule_days: list[str] = []
    schedule_time: str = Field("08:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")  # HH:MM, UTC
    detail_concurrency: int = Field(5, ge=1, le=20)
    vpn_rotate_batches: int = Field(3, ge=1)
    auto_analyse: bool = True
    auto_notion_push: bool = False
    enabled: bool = True
    site_id: str = "immobiliare"
    request_delay_sec: float = Field(2.0, ge=0)
    page_delay_sec: float = Field(0.0, ge=0)
    timeout_sec: Optional[int] = Field(None, ge=1)

    @field_validator("schedule_days")
    @classmethod
    def _known_weekdays(cls, days: list[str]) -> list[str]:
        """Lowercase, drop duplicates (order kept) and reject anything but mon..sun."""
        cleaned = list(dict.fromkeys(d.strip().lower() for d in days))
        invalid = [d for d in cleaned if d not in WEEKDAYS]
        if invalid:
            raise ValueError(f"unknown day(s) {invalid}; use {list(WEEKDAYS)}")
        return cleaned

    @model_validator(mode="after")
    def _page_range(self) -> "ConfigIn":
        if self.end_page < self.start_page:
            raise ValueError("end_page must be >= start_page")
        return self


def _config_extras(session: Session, config_ids: list[int]) -> dict[int, dict]:
    """Batch-load last_job and listing_count for the given config ids."""
    extras: dict[int, dict] = {cid: {"last_job": None, "listing_count": 0} for cid in config_ids}
    if not config_ids:
        return extras
    counts = session.exec(
        select(Listing.config_id, func.count(Listing.id))
        .where(Listing.config_id.in_(config_ids))
        .group_by(Listing.config_id)
    ).all()
    for cid, n in counts:
        extras[cid]["listing_count"] = n
    # Latest job per config = highest id (ids follow creation order); skip the heavy log column
    latest_ids = select(func.max(Job.id)).where(Job.config_id.in_(config_ids)).group_by(Job.config_id)
    rows = session.exec(
        select(Job.id, Job.config_id, Job.status, Job.started_at, Job.finished_at, Job.listing_count)
        .where(Job.id.in_(latest_ids))
    ).all()
    for job_id, cid, status, started_at, finished_at, listing_count in rows:
        extras[cid]["last_job"] = {
            "id": job_id,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "listing_count": listing_count,
        }
    return extras


def _to_response(cfg: SearchConfig, session: Session, extras: dict | None = None) -> dict:
    d = cfg.model_dump()
    d["schedule_days"] = json.loads(cfg.schedule_days or "[]")
    next_run = scheduler.next_run_time(cfg.id)
    d["next_run_at"] = next_run.isoformat() if next_run else None
    if extras is None:
        extras = _config_extras(session, [cfg.id])[cfg.id]
    d.update(extras)
    return d


@router.get("")
def list_configs(session: Session = Depends(get_session)):
    configs = session.exec(select(SearchConfig)).all()
    extras = _config_extras(session, [c.id for c in configs])
    return [_to_response(c, session, extras[c.id]) for c in configs]


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
    return _to_response(cfg, session)


@router.get("/{config_id}")
def get_config(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    return _to_response(cfg, session)


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
    return _to_response(cfg, session)


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
    return _to_response(cfg, session)


@router.post("/{config_id}/run")
async def run_config_now(config_id: int, session: Session = Depends(get_session)):
    cfg = session.get(SearchConfig, config_id)
    if not cfg:
        raise HTTPException(404, "Config not found")
    running = scheduler.active_job_id(config_id)
    if running is not None:
        # One run per search at a time: the UI shows this instead of starting a duplicate
        raise HTTPException(409, f"Questa ricerca è già in corso (run #{running}).")
    job_id = scheduler.trigger_now(config_id)
    return {"job_id": job_id}
