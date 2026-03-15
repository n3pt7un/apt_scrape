"""backend.db — SQLModel table definitions and DB engine setup."""

import os
from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine, select

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
    # Use MEMORY journal mode to avoid journal files on mounted filesystems
    # (APFS/FUSE mounts can't reliably delete the .db-journal file).
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
        cursor.execute("PRAGMA journal_mode=MEMORY")
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
    scraped_at: datetime = Field(default_factory=datetime.utcnow)


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
        conn.commit()


def create_db_and_tables() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    SQLModel.metadata.create_all(engine)
    if DB_PATH != ":memory:":
        _migrate_searchconfig_20260314()
        _migrate_job_stats_20260314()


def get_session():
    """FastAPI dependency: yield a DB session per request."""
    with Session(engine) as session:
        yield session
