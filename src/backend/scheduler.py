"""backend.scheduler — APScheduler setup and job management.

Every run (scheduled or manual) goes through _guarded_run: one run per config
at a time (a second request gets the running job back), and runs execute one
after another because they all drive the same shared browser. The browser is
closed after the last queued run.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from backend.db import Job, SearchConfig, engine
from backend.runner import run_config_job

logger = logging.getLogger(__name__)

# The backend usually runs on a laptop: a run due while the Mac slept (or the
# loop was busy) still fires once on wake instead of being silently dropped
# (APScheduler's default grace is 1 s). Bounded, so a day-old run is not fired.
MISFIRE_GRACE_SEC = 6 * 3600
_JOB_OPTIONS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": MISFIRE_GRACE_SEC}

_scheduler = AsyncIOScheduler(timezone="UTC", job_defaults=_JOB_OPTIONS)

# Runs in flight by config id: (job_id, task). The source of truth for "is this
# search already running?", and it keeps a strong reference to each task (the
# event loop only holds weak ones).
_active: dict[int, tuple[int, Optional[asyncio.Task]]] = {}
# All runs share one browser: run them one at a time; queued runs stay 'pending'
_run_lock = asyncio.Lock()

DAY_MAP = {
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu",
    "fri": "fri", "sat": "sat", "sun": "sun",
}


def _make_job_id(config_id: int) -> str:
    return f"config_{config_id}"


def _build_trigger(schedule_days: list[str], schedule_time: str) -> CronTrigger:
    # Known limitation: schedule_time and the weekdays are stored in UTC (the SPA
    # converts from local time), so a local time that crosses midnight in UTC
    # fires on the neighbouring weekday, and schedules shift by an hour at DST.
    # Fixing it needs a schedule_tz on the config and local wall times end to end.
    days_str = ",".join(DAY_MAP.get(d, d) for d in schedule_days) or "*"
    hour, minute = schedule_time.split(":")
    return CronTrigger(day_of_week=days_str, hour=int(hour), minute=int(minute), timezone="UTC")


def _create_job(config_id: int, triggered_by: str) -> int:
    with Session(engine) as session:
        job = Job(config_id=config_id, status="pending", triggered_by=triggered_by)
        session.add(job)
        session.commit()
        session.refresh(job)
        return job.id


def _fail_if_unfinished(job_id: int, reason: str) -> None:
    """Safety net: a run that ended without a final status is marked failed, never left 'running'."""
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job and job.status in ("pending", "running"):
            now = datetime.utcnow()
            job.status = "failed"
            job.finished_at = now
            job.log = (job.log or "") + f"[{now:%H:%M:%S}] [ERROR] {reason}\n"
            session.add(job)
            session.commit()


async def _guarded_run(config_id: int, job_id: int) -> None:
    """Run one registered job under the global run lock, then release the browser if nothing is queued."""
    reason = "Run ended without a final status."
    try:
        async with _run_lock:
            await run_config_job(config_id, lambda msg: None, existing_job_id=job_id)
    except asyncio.CancelledError:
        reason = "Run cancelled before it finished."
        raise
    except Exception as exc:
        logger.exception("Unhandled error in job %d for config %d", job_id, config_id)
        reason = str(exc) or repr(exc)
    finally:
        try:
            _fail_if_unfinished(job_id, reason)
        except Exception:
            logger.exception("Could not finalise job %d", job_id)
        if _active.get(config_id, (None, None))[0] == job_id:
            del _active[config_id]
        if not _active:
            # Restart the browser between runs to prevent memory accumulation, but
            # only when no other run is queued: they all share it. _ensure_browser()
            # lazily starts a fresh instance for the next run.
            try:
                from apt_scrape.server import browser
                await browser.close()
            except Exception:
                logger.debug("Error closing browser after job", exc_info=True)


async def _run_job_wrapper(config_id: int) -> None:
    """Scheduled entry point: skipped while the same config is already running."""
    active = _active.get(config_id)
    if active:
        logger.info("Config %d already running (job %d): skipping the scheduled run.", config_id, active[0])
        return
    job_id = _create_job(config_id, "schedule")
    _active[config_id] = (job_id, asyncio.current_task())
    await _guarded_run(config_id, job_id)


def _schedule(cfg: SearchConfig) -> bool:
    """Add or replace the cron job for *cfg*. Returns False when it has no schedule."""
    days = json.loads(cfg.schedule_days or "[]")
    if not days:
        return False
    trigger = _build_trigger(days, cfg.schedule_time)
    _scheduler.add_job(
        _run_job_wrapper, trigger=trigger, args=[cfg.id],
        id=_make_job_id(cfg.id), replace_existing=True, **_JOB_OPTIONS,
    )
    return True


async def start_scheduler() -> None:
    with Session(engine) as session:
        configs = session.exec(select(SearchConfig).where(SearchConfig.enabled == True)).all()

    for cfg in configs:
        # One malformed schedule must not keep the backend from starting
        try:
            if _schedule(cfg):
                logger.info("Scheduled config %d (%s) at %s on %s", cfg.id, cfg.name, cfg.schedule_time, cfg.schedule_days)
        except Exception:
            logger.exception("Skipping config %d: invalid schedule", cfg.id)

    _scheduler.start()
    logger.info("Scheduler started with %d jobs.", len(_scheduler.get_jobs()))


async def stop_scheduler() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
    # Cancel runs still in flight so each saves what it collected and marks its
    # job failed before the browser is closed under it.
    tasks = [task for _, task in _active.values() if task is not None and not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=10)


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

    try:
        if _schedule(cfg):
            logger.info("Reloaded schedule for config %d", config_id)
    except Exception:
        logger.exception("Config %d not scheduled: invalid schedule", config_id)


def next_run_time(config_id: int) -> Optional[datetime]:
    """Return the next scheduled (tz-aware UTC) run for a config, or None.

    None when the scheduler isn't running, the config has no schedule or is
    disabled, or its APScheduler job is paused.
    """
    if not _scheduler.running:
        return None
    try:
        job = _scheduler.get_job(_make_job_id(config_id))
    except Exception:
        return None
    return getattr(job, "next_run_time", None) if job else None


def active_job_id(config_id: int) -> Optional[int]:
    """The job currently running (or queued) for *config_id*, or None."""
    active = _active.get(config_id)
    return active[0] if active else None


def trigger_now(config_id: int) -> int:
    """Create a Job record synchronously, fire pipeline as background task. Returns real job_id.

    When the config is already running nothing new is started: the running
    job's id is returned instead.
    """
    active = _active.get(config_id)
    if active:
        logger.info("Config %d already running (job %d): not starting another run.", config_id, active[0])
        return active[0]

    job_id = _create_job(config_id, "manual")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _active[config_id] = (job_id, None)
        asyncio.run(_guarded_run(config_id, job_id))
        return job_id

    _active[config_id] = (job_id, loop.create_task(_guarded_run(config_id, job_id)))
    return job_id
