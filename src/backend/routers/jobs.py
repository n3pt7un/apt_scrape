"""backend.routers.jobs — Job status, log retrieval and live log streaming (SSE)."""

import asyncio
import json
import time
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlmodel import Session, select

from backend.db import Job, Listing, SearchConfig, engine, get_session
from backend.parsing import parse_price as _parse_price

router = APIRouter()

# SSE tuning — module-level so tests can shrink them
STREAM_POLL_SEC = 1.0
STREAM_PING_SEC = 15.0
_TERMINAL_STATUSES = {"done", "failed"}


# Every job column except the (unbounded) log, for the polled list endpoint
_JOB_LIST_COLUMNS = [c for c in Job.__table__.columns if c.name != "log"]


@router.get("")
def list_jobs(
    config_id: Optional[int] = None,
    include_log: bool = Query(False, description="Also return each job's full log (GET /jobs/{id} has it too)"),
    session: Session = Depends(get_session),
):
    """Latest 50 jobs, newest first. Without include_log the log column is not even read."""
    columns = list(Job.__table__.columns) if include_log else _JOB_LIST_COLUMNS
    stmt = select(*columns).order_by(Job.started_at.desc()).limit(50)
    if config_id is not None:
        stmt = stmt.where(Job.config_id == config_id)
    jobs = [dict(row._mapping) for row in session.exec(stmt).all()]
    config_ids = {j["config_id"] for j in jobs}
    names = {
        c.id: c.name
        for c in session.exec(select(SearchConfig).where(SearchConfig.id.in_(config_ids))).all()
    }
    return [
        {**j, "attribution_exact": bool(j.get("attribution_exact")), "config_name": names.get(j["config_id"], "")}
        for j in jobs
    ]


@router.get("/stats/overall")
def overall_stats(session: Session = Depends(get_session)):
    """Aggregate stats across all completed jobs."""
    jobs = session.exec(select(Job).where(Job.status == "done")).all()

    total_runs = len(jobs)
    # Unique listings in the DB; the per-run sum counts a listing once per run that saw it
    total_listings = session.exec(select(func.count(Listing.id))).one()
    total_processed = sum(j.listing_count or 0 for j in jobs)
    total_scraped = sum(j.scraped_count or 0 for j in jobs)
    total_dupes = sum(j.dupes_removed or 0 for j in jobs)
    total_tokens = sum(j.ai_tokens_used or 0 for j in jobs)
    total_cost = sum(j.ai_cost_usd or 0.0 for j in jobs)

    total_duration_sec = sum(
        (j.finished_at - j.started_at).total_seconds()
        for j in jobs
        if j.finished_at and j.started_at
    )

    # Avg price and area distribution across all listings (only the two columns needed)
    prices = [p for price in session.exec(select(Listing.price)).all()
              if (p := _parse_price(price or "")) is not None and p > 0]
    avg_price = round(sum(prices) / len(prices), 0) if prices else None
    area_dist = {
        area or "": n
        for area, n in session.exec(select(Listing.area, func.count(Listing.id)).group_by(Listing.area)).all()
    }

    return {
        "total_runs": total_runs,
        "total_listings": total_listings,
        "total_processed": total_processed,
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

    # The run's listings as the SPA's run filter and verbale count them (inRun): the ones it
    # found first plus the known ones it saw again that no later run has seen since. For an
    # older run that is not everything it saw (last_job_id moves on); for the latest run it is.
    rows = session.exec(
        select(Listing.price, Listing.area).where(or_(Listing.job_id == job_id, Listing.last_job_id == job_id))
    ).all()
    prices = [p for price, _ in rows if (p := _parse_price(price or "")) is not None and p > 0]
    avg_price = round(sum(prices) / len(prices), 0) if prices else None

    area_dist: dict[str, int] = {}
    for _, area in rows:
        a = area or ""
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


def _sse(event: str, data: dict) -> str:
    """Format one Server-Sent Event with a JSON payload."""
    payload = json.dumps(jsonable_encoder(data), ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _read_job_state(job_id: int) -> Optional[tuple[str, dict[str, Any]]]:
    """Return (log, status payload) for a job using a fresh session, or None if missing."""
    with Session(engine) as s:
        job = s.get(Job, job_id)
        if job is None:
            return None
        return job.log or "", {
            "job_id": job.id,
            "status": job.status,
            "listing_count": job.listing_count,
            "scraped_count": job.scraped_count,
            "finished_at": job.finished_at,
        }


@router.get("/{job_id}/stream")
async def stream_job(job_id: int, request: Request, offset: int = Query(0, ge=0)):
    """Stream a job's log and status as SSE until it is done/failed.

    Events: ``log`` {offset, chunk} whenever the log grows (offset = new total
    length, pass it back as ``?offset=`` to resume), ``status`` whenever the
    status payload changes, and a final ``end`` with the terminal status.
    """
    initial = _read_job_state(job_id)
    if initial is None:
        raise HTTPException(404, "Job not found")

    async def _events() -> AsyncIterator[str]:
        state: Optional[tuple[str, dict]] = initial
        pos = offset
        last_status: Optional[dict] = None
        last_sent = time.monotonic()
        while state is not None:
            if await request.is_disconnected():
                return
            log, status = state
            if pos > len(log):
                pos = 0  # stale offset (e.g. from another job): resend the whole log
            if len(log) > pos:
                yield _sse("log", {"offset": len(log), "chunk": log[pos:]})
                pos = len(log)
                last_sent = time.monotonic()
            if status != last_status:
                yield _sse("status", status)
                last_status = status
                last_sent = time.monotonic()
            if status["status"] in _TERMINAL_STATUSES:
                yield _sse("end", status)
                return
            await asyncio.sleep(STREAM_POLL_SEC)
            if time.monotonic() - last_sent >= STREAM_PING_SEC:
                yield ": ping\n\n"
                last_sent = time.monotonic()
            state = _read_job_state(job_id)  # None if the job was deleted mid-stream

    return StreamingResponse(
        _events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}")
def get_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {**job.model_dump(), "attribution_exact": bool(job.attribution_exact)}


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, session: Session = Depends(get_session)):
    from backend import scheduler

    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    # The run's task would carry on unseen and keep its search locked until it ended.
    # A stale 'running' row that no task owns (startup reconciles those) stays deletable.
    if job.status in ("pending", "running") and scheduler.active_job_id(job.config_id) == job.id:
        raise HTTPException(409, "Run in corso: attendi che finisca prima di eliminarla.")
    session.delete(job)
    session.commit()
    return Response(status_code=204)
