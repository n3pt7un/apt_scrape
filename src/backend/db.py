"""backend.db — SQLModel table definitions and DB engine setup."""

import logging
import os
from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine, select

logger = logging.getLogger(__name__)

DB_PATH = os.getenv("DB_PATH", "data/app.db")

if DB_PATH == ":memory:":
    from sqlalchemy.pool import StaticPool
    # check_same_thread=False is required for FastAPI, as it can pass connections
    # across threads (e.g., when routing sync endpoints in a threadpool).
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
else:
    # WAL keeps app.db crash-safe (MEMORY, used before, could corrupt it on a
    # crash mid-commit) and lets API reads proceed while a run is writing.
    # SQLITE_JOURNAL_MODE overrides it, e.g. DELETE or TRUNCATE on filesystems
    # where WAL's shared-memory file is unreliable (some Docker bind mounts).
    _JOURNAL_MODES = {"WAL", "DELETE", "TRUNCATE", "PERSIST"}
    JOURNAL_MODE = os.getenv("SQLITE_JOURNAL_MODE", "WAL").strip().upper()
    if JOURNAL_MODE not in _JOURNAL_MODES:
        logger.warning("Unsupported SQLITE_JOURNAL_MODE %r, using WAL", JOURNAL_MODE)
        JOURNAL_MODE = "WAL"
    # Note: check_same_thread=False allows FastAPI's threadpool to share connections.
    engine = create_engine(
        f"sqlite:///{DB_PATH}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    from sqlalchemy import event
    @event.listens_for(engine, "connect")
    def set_journal_mode(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute(f"PRAGMA journal_mode={JOURNAL_MODE}")
        if JOURNAL_MODE == "WAL":
            # Durable across app crashes; only an OS crash can lose the last commits
            cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


class SearchConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
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
    schedule_days: str = '[]'       # JSON array: ["mon","wed","fri"]
    schedule_time: str = "08:00"    # HH:MM 24h UTC
    detail_concurrency: int = 5
    vpn_rotate_batches: int = 3
    auto_analyse: bool = True
    auto_notion_push: bool = False
    enabled: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)
    site_id: str = "immobiliare"
    request_delay_sec: float = 2.0
    page_delay_sec: float = 0.0
    timeout_sec: Optional[int] = None


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    config_id: int = Field(foreign_key="searchconfig.id")
    status: str = "pending"         # pending / running / done / failed
    triggered_by: str = "schedule"  # schedule / manual
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    listing_count: Optional[int] = None
    scraped_count: Optional[int] = None       # total listings before dedup
    dupes_removed: Optional[int] = None       # scraped_count - listing_count
    ai_tokens_used: Optional[int] = None      # total tokens consumed by AI analysis
    ai_cost_usd: Optional[float] = None       # estimated cost in USD
    ai_scored_count: Optional[int] = None     # listings sent to the LLM (runs are incremental); added 2026-10-11
    # True for runs made since listings keep their first-found run (2026-10-11); NULL
    # for older runs, whose "found first" counts are unknown (see _migrate_listing_seen_20261011)
    attribution_exact: Optional[bool] = True
    area_stats: str = "{}"                    # JSON: {area_slug: count}
    log: str = ""


class Listing(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    url: str = Field(unique=True, index=True)
    job_id: int = Field(foreign_key="job.id")
    config_id: int = Field(foreign_key="searchconfig.id")
    title: str = ""
    price: str = ""
    sqm: str = ""
    rooms: str = ""
    area: str = ""
    city: str = ""
    ai_score: Optional[int] = None
    ai_verdict: Optional[str] = None
    notion_page_id: Optional[str] = None
    raw_json: str = "{}"
    # job_id and scraped_at record the run that FIRST found the listing and are
    # never reassigned; last_job_id / last_seen_at move on every run that sees it.
    # Rows saved before 2026-10-11 are the exception: the old upsert rewrote both on
    # every run, so they hold the last run that saw the row (first_seen_exact NULL).
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    last_seen_at: Optional[datetime] = None         # added 2026-10-11
    last_job_id: Optional[int] = Field(default=None, foreign_key="job.id")
    first_seen_exact: Optional[bool] = True         # added 2026-10-11; NULL = legacy row, see above
    # Owner-side state for the web UI (all nullable; added 2026-10-04)
    triage_status: Optional[str] = None             # None / preferito / scartato / contattato
    triage_note: Optional[str] = None
    triage_updated_at: Optional[datetime] = None
    seen_at: Optional[datetime] = None              # first opened by the owner; NULL = "nuovo"
    lat: Optional[float] = None
    lon: Optional[float] = None
    geocode_status: Optional[str] = None            # None (not tried) / ok / failed


class SiteConfigOverride(SQLModel, table=True):
    """Per-site config overrides (areas, selectors, wait selectors). One row per site_id."""
    site_id: str = Field(primary_key=True)
    overrides: str = "{}"  # JSON dict


def _migrate_searchconfig_20260314() -> None:
    """Add site_id, request_delay_sec, page_delay_sec, timeout_sec to existing searchconfig table."""
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(searchconfig)"))
        cols = [row[1] for row in result.fetchall()]
        if "site_id" not in cols:
            conn.execute(text("ALTER TABLE searchconfig ADD COLUMN site_id TEXT DEFAULT 'immobiliare'"))
        if "request_delay_sec" not in cols:
            conn.execute(text("ALTER TABLE searchconfig ADD COLUMN request_delay_sec REAL DEFAULT 2.0"))
        if "page_delay_sec" not in cols:
            conn.execute(text("ALTER TABLE searchconfig ADD COLUMN page_delay_sec REAL DEFAULT 0.0"))
        if "timeout_sec" not in cols:
            conn.execute(text("ALTER TABLE searchconfig ADD COLUMN timeout_sec INTEGER"))
        conn.commit()


def _migrate_job_stats_20260314() -> None:
    """Add scraped_count, dupes_removed, ai_tokens_used, ai_cost_usd, area_stats to job table."""
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(job)"))
        cols = [row[1] for row in result.fetchall()]
        if "scraped_count" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN scraped_count INTEGER"))
        if "dupes_removed" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN dupes_removed INTEGER"))
        if "ai_tokens_used" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN ai_tokens_used INTEGER"))
        if "ai_cost_usd" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN ai_cost_usd REAL"))
        if "area_stats" not in cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN area_stats TEXT DEFAULT '{}'"))
        if "ai_scored_count" not in cols:  # added 2026-10-11, NULL for older jobs
            conn.execute(text("ALTER TABLE job ADD COLUMN ai_scored_count INTEGER"))
        conn.commit()


# Listing columns added for the web UI: name -> SQLite column type
_LISTING_WEB_COLUMNS = {
    "triage_status": "TEXT",
    "triage_note": "TEXT",
    "triage_updated_at": "DATETIME",
    "seen_at": "DATETIME",
    "lat": "REAL",
    "lon": "REAL",
    "geocode_status": "TEXT",
}


def _migrate_listing_web_20261004() -> None:
    """Add triage/seen/geocoding columns to the existing listing table."""
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(listing)"))
        cols = [row[1] for row in result.fetchall()]
        for name, col_type in _LISTING_WEB_COLUMNS.items():
            if name not in cols:
                conn.execute(text(f"ALTER TABLE listing ADD COLUMN {name} {col_type}"))
        conn.commit()


def _migrate_listing_seen_20261011() -> None:
    """Add last_seen_at/last_job_id to listing, backfilled from scraped_at/job_id.

    Caveat: the old upsert rewrote job_id and scraped_at on every run, so on
    existing rows they hold the LAST run that saw the listing, not the first;
    the true first-seen run is lost. Existing rows and jobs therefore keep
    first_seen_exact / attribution_exact NULL (new ones get True), and the API
    and UI label them "seen" instead of "found first".

    Idempotent: columns are added only when missing and the backfill only
    touches rows where they are still NULL.
    """
    from sqlalchemy import text
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(listing)"))
        cols = [row[1] for row in result.fetchall()]
        if "last_seen_at" not in cols:
            conn.execute(text("ALTER TABLE listing ADD COLUMN last_seen_at DATETIME"))
        if "last_job_id" not in cols:
            conn.execute(text("ALTER TABLE listing ADD COLUMN last_job_id INTEGER REFERENCES job (id)"))
        if "first_seen_exact" not in cols:
            conn.execute(text("ALTER TABLE listing ADD COLUMN first_seen_exact BOOLEAN"))
        job_cols = [row[1] for row in conn.execute(text("PRAGMA table_info(job)")).fetchall()]
        if "attribution_exact" not in job_cols:
            conn.execute(text("ALTER TABLE job ADD COLUMN attribution_exact BOOLEAN"))
        conn.execute(text("UPDATE listing SET last_seen_at = scraped_at WHERE last_seen_at IS NULL"))
        conn.execute(text("UPDATE listing SET last_job_id = job_id WHERE last_job_id IS NULL"))
        conn.commit()


def create_db_and_tables() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    SQLModel.metadata.create_all(engine)
    if DB_PATH != ":memory:":
        _migrate_searchconfig_20260314()
        _migrate_job_stats_20260314()
        _migrate_listing_web_20261004()
        _migrate_listing_seen_20261011()


def reconcile_interrupted_jobs() -> int:
    """Mark jobs a previous backend process left 'pending'/'running' as failed.

    Runs are in-process asyncio tasks, so at startup none of them can still be
    alive (this assumes a single backend process: no uvicorn --workers).
    Without it they would show as running forever and keep the UI polling.
    Returns the number of jobs reconciled.
    """
    now = datetime.utcnow()
    with Session(engine) as session:
        stale = session.exec(select(Job).where(Job.status.in_(("pending", "running")))).all()
        stale_ids = [job.id for job in stale]
        for job in stale:
            job.status = "failed"
            job.finished_at = now
            job.log = (job.log or "") + (
                f"[{now:%H:%M:%S}] [ERROR] Run interrupted: the backend stopped before it finished.\n"
            )
            session.add(job)
        session.commit()
    if stale_ids:
        logger.warning("Marked %d interrupted job(s) as failed: %s", len(stale_ids), stale_ids)
    return len(stale_ids)


def get_session():
    """FastAPI dependency: yield a DB session per request."""
    with Session(engine) as session:
        yield session
