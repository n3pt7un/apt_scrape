"""backend.routers.jobs — Job status and log retrieval."""

import json
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlmodel import Session, select

from backend.db import Job, Listing, get_session

router = APIRouter()


def _parse_price(price_str: str) -> Optional[float]:
    """Extract a numeric price from strings like '€ 1.200/mese' or '1200 €'."""
    cleaned = price_str.replace(".", "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", cleaned)
    return float(m.group(1)) if m else None


@router.get("")
def list_jobs(config_id: Optional[int] = None, session: Session = Depends(get_session)):
    stmt = select(Job).order_by(Job.started_at.desc()).limit(50)
    if config_id is not None:
        stmt = stmt.where(Job.config_id == config_id)
    jobs = session.exec(stmt).all()
    return [j.model_dump() for j in jobs]


@router.get("/stats/overall")
def overall_stats(session: Session = Depends(get_session)):
    """Aggregate stats across all completed jobs."""
    jobs = session.exec(select(Job).where(Job.status == "done")).all()

    total_runs = len(jobs)
    total_listings = sum(j.listing_count or 0 for j in jobs)
    total_scraped = sum(j.scraped_count or 0 for j in jobs)
    total_dupes = sum(j.dupes_removed or 0 for j in jobs)
    total_tokens = sum(j.ai_tokens_used or 0 for j in jobs)
    total_cost = sum(j.ai_cost_usd or 0.0 for j in jobs)

    total_duration_sec = sum(
        (j.finished_at - j.started_at).total_seconds()
        for j in jobs
        if j.finished_at and j.started_at
    )

    # Avg price across all listings
    listings = session.exec(select(Listing)).all()
    prices = [p for l in listings if (p := _parse_price(l.price or "")) is not None and p > 0]
    avg_price = round(sum(prices) / len(prices), 0) if prices else None

    # Area distribution across all listings
    area_dist: dict[str, int] = {}
    for l in listings:
        a = l.area or ""
        area_dist[a] = area_dist.get(a, 0) + 1

    return {
        "total_runs": total_runs,
        "total_listings": total_listings,
        "total_scraped": total_scraped,
        "total_dupes_removed": total_dupes,
        "total_ai_tokens": total_tokens,
        "total_ai_cost_usd": round(total_cost, 4),
        "total_duration_sec": round(total_duration_sec, 0),
        "avg_price_eur": avg_price,
        "area_distribution": area_dist,
    }


@router.get("/{job_id}/stats")
def job_stats(job_id: int, session: Session = Depends(get_session)):
    """Per-run stats for a single job."""
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")

    duration_sec = None
    if job.finished_at and job.started_at:
        duration_sec = round((job.finished_at - job.started_at).total_seconds(), 1)

    listings = session.exec(select(Listing).where(Listing.job_id == job_id)).all()
    prices = [p for l in listings if (p := _parse_price(l.price or "")) is not None and p > 0]
    avg_price = round(sum(prices) / len(prices), 0) if prices else None

    area_dist: dict[str, int] = {}
    for l in listings:
        a = l.area or ""
        area_dist[a] = area_dist.get(a, 0) + 1

    # area_stats from runner is the authoritative scrape-time count; use DB listing counts as fallback
    stored_area_stats = {}
    try:
        stored_area_stats = json.loads(job.area_stats or "{}")
    except Exception:
        pass

    return {
        "job_id": job_id,
        "status": job.status,
        "triggered_by": job.triggered_by,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "duration_sec": duration_sec,
        "scraped_count": job.scraped_count,
        "listing_count": job.listing_count,
        "dupes_removed": job.dupes_removed,
        "ai_tokens_used": job.ai_tokens_used,
        "ai_cost_usd": job.ai_cost_usd,
        "avg_price_eur": avg_price,
        "area_stats": stored_area_stats or area_dist,
    }


@router.get("/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job.model_dump()


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    session.delete(job)
    session.commit()
    return Response(status_code=204)
