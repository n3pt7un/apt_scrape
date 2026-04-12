"""backend.routers.jobs — Job status and log retrieval."""

import json
import re
from datetime import datetime, timedelta
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
    from backend.db import SearchConfig

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

    # Price per sqm by area
    area_price_sqm: dict[str, list[float]] = {}
    for l in listings:
        price = _parse_price(l.price or "")
        sqm = _parse_price(l.sqm or "")
        if price and sqm and sqm > 0:
            a = l.area or ""
            area_price_sqm.setdefault(a, []).append(price / sqm)
    price_per_sqm_by_area = {
        a: round(sum(vals) / len(vals), 1)
        for a, vals in area_price_sqm.items()
        if vals
    }

    # Config name lookup
    config_ids = {j.config_id for j in jobs if j.config_id is not None}
    configs = {}
    if config_ids:
        configs = {
            c.id: c.name
            for c in session.exec(
                select(SearchConfig).where(SearchConfig.id.in_(config_ids))
            ).all()
        }

    # Timeline: per-job objects sorted by started_at asc
    timeline = []
    for j in sorted(jobs, key=lambda x: x.started_at or datetime.min):
        duration_sec = None
        if j.finished_at and j.started_at:
            duration_sec = round((j.finished_at - j.started_at).total_seconds(), 1)

        job_listings = [l for l in listings if l.job_id == j.id]
        job_prices = [p for l in job_listings if (p := _parse_price(l.price or "")) is not None and p > 0]
        job_avg_price = round(sum(job_prices) / len(job_prices), 0) if job_prices else None

        job_sqm_vals: list[float] = []
        for l in job_listings:
            price = _parse_price(l.price or "")
            sqm = _parse_price(l.sqm or "")
            if price and sqm and sqm > 0:
                job_sqm_vals.append(price / sqm)
        job_avg_price_per_sqm = round(sum(job_sqm_vals) / len(job_sqm_vals), 1) if job_sqm_vals else None

        job_area_stats: dict[str, int] = {}
        for l in job_listings:
            a = l.area or ""
            job_area_stats[a] = job_area_stats.get(a, 0) + 1

        timeline.append({
            "job_id": j.id,
            "config_name": configs.get(j.config_id, ""),
            "started_at": j.started_at,
            "duration_sec": duration_sec,
            "scraped_count": j.scraped_count,
            "listing_count": j.listing_count,
            "dupes_removed": j.dupes_removed,
            "ai_cost_usd": j.ai_cost_usd,
            "avg_price_eur": job_avg_price,
            "avg_price_per_sqm": job_avg_price_per_sqm,
            "area_stats": job_area_stats,
            "status": j.status,
        })

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
        "price_per_sqm_by_area": price_per_sqm_by_area,
        "timeline": timeline,
    }


@router.get("/health")
def pipeline_health(session: Session = Depends(get_session)):
    """Compute operational health indicators for the dashboard."""
    from backend.db import SearchConfig
    now = datetime.utcnow()

    # --- Pipeline status ---
    last_job = session.exec(
        select(Job).order_by(Job.started_at.desc()).limit(1)
    ).first()

    if not last_job:
        pipeline_status = "warning"
        last_job_status = None
        last_job_ago_sec = None
    else:
        last_job_status = last_job.status
        finished = last_job.finished_at or last_job.started_at
        last_job_ago_sec = (now - finished).total_seconds()
        if last_job.status == "failed":
            pipeline_status = "critical"
        elif last_job_ago_sec > 6 * 3600:
            pipeline_status = "warning"
        else:
            pipeline_status = "healthy"

    # --- Schedule health ---
    configs = session.exec(
        select(SearchConfig).where(SearchConfig.enabled == True)
    ).all()
    missed_schedules = []
    schedule_health = "healthy"

    for cfg in configs:
        days = cfg.schedule_days
        if isinstance(days, str):
            import json as _j
            try:
                days = _j.loads(days)
            except Exception:
                days = []
        if not days:
            continue
        last_cfg_job = session.exec(
            select(Job)
            .where(Job.config_id == cfg.id)
            .order_by(Job.started_at.desc())
            .limit(1)
        ).first()
        if not last_cfg_job:
            missed_schedules.append(cfg.name)
            schedule_health = "critical"
            continue
        ago = (now - (last_cfg_job.finished_at or last_cfg_job.started_at)).total_seconds()
        if ago > 6 * 3600:
            missed_schedules.append(cfg.name)
            if schedule_health != "critical":
                schedule_health = "critical"
        elif ago > 3600:
            if schedule_health == "healthy":
                schedule_health = "warning"

    # --- Yield trend (7-day windows) ---
    seven_days_ago = now - timedelta(days=7)
    fourteen_days_ago = now - timedelta(days=14)

    recent_jobs = session.exec(
        select(Job).where(Job.status == "done", Job.started_at >= seven_days_ago)
    ).all()
    prev_jobs = session.exec(
        select(Job).where(Job.status == "done", Job.started_at >= fourteen_days_ago, Job.started_at < seven_days_ago)
    ).all()

    def _avg_yield(jobs_list):
        counts = [j.listing_count or 0 for j in jobs_list]
        return round(sum(counts) / len(counts), 1) if counts else 0

    yield_7d = _avg_yield(recent_jobs)
    yield_prev_7d = _avg_yield(prev_jobs)

    if yield_prev_7d == 0:
        yield_trend = "stable"
    else:
        pct_change = (yield_7d - yield_prev_7d) / yield_prev_7d
        if pct_change < -0.5:
            yield_trend = "critical"
        elif pct_change < -0.2:
            yield_trend = "declining"
        else:
            yield_trend = "stable"

    # --- Dupe rate (7-day) ---
    total_scraped_7d = sum(j.scraped_count or 0 for j in recent_jobs)
    total_dupes_7d = sum(j.dupes_removed or 0 for j in recent_jobs)
    dupe_rate_7d = round(total_dupes_7d / total_scraped_7d, 2) if total_scraped_7d else 0

    total_scraped_prev = sum(j.scraped_count or 0 for j in prev_jobs)
    total_dupes_prev = sum(j.dupes_removed or 0 for j in prev_jobs)
    dupe_rate_prev = round(total_dupes_prev / total_scraped_prev, 2) if total_scraped_prev else 0

    if dupe_rate_7d > dupe_rate_prev + 0.1:
        dupe_rate_trend = "rising"
    elif dupe_rate_7d < dupe_rate_prev - 0.1:
        dupe_rate_trend = "falling"
    else:
        dupe_rate_trend = "stable"

    # --- AI cost (7-day) ---
    ai_cost_7d = round(sum(j.ai_cost_usd or 0 for j in recent_jobs), 4)
    ai_cost_prev_7d = round(sum(j.ai_cost_usd or 0 for j in prev_jobs), 4)

    return {
        "pipeline_status": pipeline_status,
        "last_job_status": last_job_status,
        "last_job_ago_sec": round(last_job_ago_sec) if last_job_ago_sec is not None else None,
        "schedule_health": schedule_health,
        "missed_schedules": missed_schedules,
        "yield_trend": yield_trend,
        "yield_7d_avg": yield_7d,
        "yield_prev_7d_avg": yield_prev_7d,
        "dupe_rate_7d": dupe_rate_7d,
        "dupe_rate_trend": dupe_rate_trend,
        "ai_cost_7d": ai_cost_7d,
        "ai_cost_prev_7d": ai_cost_prev_7d,
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


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, session: Session = Depends(get_session)):
    """Cancel a running job — signals the runner to stop and closes the browser."""
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status != "running":
        raise HTTPException(400, f"Job is not running (status={job.status})")

    from backend.scheduler import cancel_job as _cancel
    cancelled = _cancel(job_id)
    if not cancelled:
        # Task not tracked — force-mark as failed
        job.status = "failed"
        job.finished_at = datetime.utcnow()
        session.add(job)
        session.commit()
    return {"cancelled": True, "job_id": job_id}


@router.delete("/{job_id}", status_code=204)
def delete_job(job_id: int, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    session.delete(job)
    session.commit()
    return Response(status_code=204)
