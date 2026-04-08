"""backend.scheduler — APScheduler setup and job management."""

import asyncio
import json
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from backend.db import Job, SearchConfig, engine
from backend.runner import run_config_job

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler(timezone="UTC")

# Track running tasks: job_id -> (asyncio.Task, asyncio.Event)
_running_tasks: dict[int, tuple[asyncio.Task, asyncio.Event]] = {}

DAY_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
}


def _make_job_id(config_id: int) -> str:
    return f"config_{config_id}"


def _build_trigger(schedule_days: list[str], schedule_time: str) -> CronTrigger:
    days_str = ",".join(DAY_MAP.get(d, d) for d in schedule_days) or "*"
    hour, minute = schedule_time.split(":")
    return CronTrigger(day_of_week=days_str, hour=int(hour), minute=int(minute), timezone="UTC")


async def _run_job_wrapper(config_id: int) -> None:
    cancel_event = asyncio.Event()
    job_id = None
    try:
        # Create job record first so we can track it
        with Session(engine) as session:
            job = Job(config_id=config_id, status="pending", triggered_by="schedule")
            session.add(job)
            session.commit()
            session.refresh(job)
            job_id = job.id
        task = asyncio.current_task()
        if job_id and task:
            _running_tasks[job_id] = (task, cancel_event)
        await run_config_job(config_id, lambda msg: None, existing_job_id=job_id, cancel_event=cancel_event)
    except Exception:
        logger.exception("Unhandled error in job for config %d", config_id)
    finally:
        if job_id:
            _running_tasks.pop(job_id, None)
        try:
            from apt_scrape.server import fetcher
            await fetcher.close()
        except Exception:
            logger.debug("Error closing browser after job", exc_info=True)


async def start_scheduler() -> None:
    with Session(engine) as session:
        configs = session.exec(select(SearchConfig).where(SearchConfig.enabled == True)).all()

    for cfg in configs:
        days = json.loads(cfg.schedule_days or "[]")
        if not days:
            continue
        trigger = _build_trigger(days, cfg.schedule_time)
        _scheduler.add_job(
            _run_job_wrapper, trigger=trigger, args=[cfg.id],
            id=_make_job_id(cfg.id), replace_existing=True,
            coalesce=True, max_instances=1,
        )
        logger.info("Scheduled config %d (%s) at %s on %s", cfg.id, cfg.name, cfg.schedule_time, days)

    _scheduler.start()
    logger.info("Scheduler started with %d jobs.", len(_scheduler.get_jobs()))


async def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


def reload_config(config_id: int) -> None:
    if not _scheduler.running:
        return
    job_id = _make_job_id(config_id)
    try:
        _scheduler.remove_job(job_id)
    except Exception:
        pass

    with Session(engine) as session:
        cfg = session.get(SearchConfig, config_id)

    if cfg is None or not cfg.enabled:
        return

    days = json.loads(cfg.schedule_days or "[]")
    if not days:
        return

    trigger = _build_trigger(days, cfg.schedule_time)
    _scheduler.add_job(
        _run_job_wrapper, trigger=trigger, args=[cfg.id],
        id=job_id, replace_existing=True, coalesce=True, max_instances=1,
    )
    logger.info("Reloaded schedule for config %d", config_id)


def trigger_now(config_id: int) -> int:
    """Create a Job record synchronously, fire pipeline as background task. Returns real job_id."""
    with Session(engine) as session:
        job = Job(config_id=config_id, status="pending", triggered_by="manual")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    cancel_event = asyncio.Event()

    async def _run():
        try:
            await run_config_job(config_id, lambda msg: None, existing_job_id=job_id, cancel_event=cancel_event)
        finally:
            _running_tasks.pop(job_id, None)

    try:
        loop = asyncio.get_running_loop()
        task = loop.create_task(_run())
        _running_tasks[job_id] = (task, cancel_event)
    except RuntimeError:
        asyncio.run(_run())

    return job_id


def cancel_job(job_id: int) -> bool:
    """Cancel a running job. Returns True if found and cancelled."""
    entry = _running_tasks.get(job_id)
    if not entry:
        return False
    task, cancel_event = entry
    cancel_event.set()  # Signal the runner to stop
    # Also close the browser to interrupt any in-progress fetch
    async def _close_browser():
        try:
            from apt_scrape.server import fetcher
            await fetcher.close()
        except Exception:
            pass

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_close_browser())
    except RuntimeError:
        pass
    return True
