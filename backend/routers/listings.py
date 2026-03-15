"""backend.routers.listings — Read-only listing queries."""
import json as _json_mod
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_
from sqlmodel import Session, select

from backend.db import Listing, SearchConfig, get_session
from apt_scrape.notion_push import mark_notion_duplicates, push_listings

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


class NotionPushRequest(BaseModel):
    listing_ids: list[int]


@router.post("/notion-push")
async def notion_push(
    body: NotionPushRequest,
    session: Session = Depends(get_session),
):
    if not body.listing_ids:
        raise HTTPException(status_code=400, detail="listing_ids must not be empty")

    api_key = os.environ.get("NOTION_API_KEY", "")
    apartments_db_id = os.environ.get("NOTION_APARTMENTS_DB_ID", "")
    if not api_key or not apartments_db_id:
        raise HTTPException(status_code=503, detail="Notion credentials not configured")

    # Fetch DB records
    records = {
        lst.id: lst
        for lst in session.exec(
            select(Listing).where(Listing.id.in_(body.listing_ids))
        ).all()
    }

    # Reconstruct full dicts from raw_json, overlay live DB fields
    listing_dicts = []
    for lid in body.listing_ids:
        rec = records.get(lid)
        if rec is None:
            continue
        try:
            d = _json_mod.loads(rec.raw_json or "{}")
        except Exception:
            d = {}
        d["ai_score"] = rec.ai_score
        d["ai_verdict"] = rec.ai_verdict
        d["notion_page_id"] = rec.notion_page_id
        d["_db_id"] = rec.id  # carry DB id for write-back
        listing_dicts.append(d)

    if not listing_dicts:
        return {"pushed": 0, "skipped": 0, "errors": []}

    # 1. Dedup check
    await mark_notion_duplicates(listing_dicts)

    # 2. Push non-skipped
    to_push = [d for d in listing_dicts if not d.get("notion_skipped")]
    errors: list[str] = []
    if to_push:
        try:
            await push_listings(to_push)
        except Exception as exc:
            errors.append(str(exc))

    # 3. Write notion_page_id back to DB (newly pushed + backfill for skipped-but-null)
    for d in listing_dicts:
        page_id = d.get("notion_page_id")
        if not page_id:
            continue
        db_id = d.get("_db_id")
        rec = records.get(db_id)
        if rec and rec.notion_page_id != page_id:
            rec.notion_page_id = page_id
            session.add(rec)
    session.commit()

    pushed = sum(
        1 for d in listing_dicts
        if not d.get("notion_skipped") and d.get("notion_page_id")
    )
    skipped = sum(1 for d in listing_dicts if d.get("notion_skipped"))

    return {"pushed": pushed, "skipped": skipped, "errors": errors}
