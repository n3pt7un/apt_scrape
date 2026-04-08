"""backend.main — FastAPI application entry point."""

import contextlib
import logging

from fastapi import FastAPI

from backend.db import create_db_and_tables
from backend.routers import configs, jobs, listings, preferences, sites

logger = logging.getLogger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables, start scheduler. Shutdown: stop scheduler."""
    create_db_and_tables()
    from backend.scheduler import start_scheduler, stop_scheduler
    await start_scheduler()
    yield
    await stop_scheduler()
    # Close browser singleton on shutdown
    try:
        from apt_scrape.server import fetcher
        await fetcher.close()
    except Exception:
        pass


app = FastAPI(title="apt_scrape backend", lifespan=lifespan)

app.include_router(configs.router, prefix="/configs", tags=["configs"])
app.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
app.include_router(listings.router, prefix="/listings", tags=["listings"])
app.include_router(preferences.router, prefix="/preferences", tags=["preferences"])
app.include_router(sites.router, prefix="/sites", tags=["sites"])


@app.get("/health")
async def health():
    return {"status": "ok"}
