"""backend.db — SQLModel table definitions and DB engine setup."""

import os
from datetime import datetime
from typing import Optional

from sqlmodel import Field, Session, SQLModel, create_engine, select

DB_PATH = os.getenv("DB_PATH", "data/app.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)


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


class Job(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    config_id: int = Field(foreign_key="searchconfig.id")
    status: str = "pending"         # pending / running / done / failed
    triggered_by: str = "schedule"  # schedule / manual
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None
    listing_count: Optional[int] = None
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


def create_db_and_tables() -> None:
    """Create all tables if they don't exist. Safe to call multiple times."""
    SQLModel.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: yield a DB session per request."""
    with Session(engine) as session:
        yield session
