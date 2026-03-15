"""backend.routers.listings — Read-only listing queries."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_
from sqlmodel import Session, select

from backend.db import Listing, SearchConfig, get_session

router = APIRouter()


@router.get("")
def list_listings(
    config_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    min_score: Optional[int] = Query(None),
    max_score: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(200, le=1000),
    offset: int = Query(0),
    session: Session = Depends(get_session),
):
    stmt = select(Listing).order_by(Listing.scraped_at.desc())
    if config_id is not None:
        stmt = stmt.where(Listing.config_id == config_id)
    if job_id is not None:
        stmt = stmt.where(Listing.job_id == job_id)
    if min_score is not None:
        stmt = stmt.where(Listing.ai_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(Listing.ai_score <= max_score)
    if search:
        q = f"%{search}%"
        stmt = stmt.where(
            or_(
                Listing.title.like(q),
                Listing.area.like(q),
                Listing.city.like(q),
            )
        )
    stmt = stmt.offset(offset).limit(limit)
    listings = session.exec(stmt).all()

    config_ids = {lst.config_id for lst in listings}
    configs = {
        c.id: c.name
        for c in session.exec(select(SearchConfig).where(SearchConfig.id.in_(config_ids))).all()
    }

    result = []
    for lst in listings:
        d = lst.model_dump()
        d.pop("raw_json", None)
        d["config_name"] = configs.get(lst.config_id, "")
        result.append(d)
    return result
