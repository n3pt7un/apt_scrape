"""backend.main — FastAPI application entry point.

Every router is mounted twice: at the root (used by the Streamlit app) and
under /api (used by the React SPA). When the SPA has been built
(src/web/dist, or WEB_DIST_DIR) it is served from the same app, with
index.html as the fallback for client-side routes.
"""

import contextlib
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# backend.db reads DB_PATH (and SQLITE_JOURNAL_MODE) at import: load .env first.
# Variables already set in the environment win, as with apt_scrape.server's own call.
load_dotenv()

from backend.db import create_db_and_tables, reconcile_interrupted_jobs  # noqa: E402
from backend.routers import configs, jobs, listings, preferences, sites  # noqa: E402

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_ROUTERS = [
    (configs.router, "/configs", "configs"),
    (jobs.router, "/jobs", "jobs"),
    (listings.router, "/listings", "listings"),
    (preferences.router, "/preferences", "preferences"),
    (sites.router, "/sites", "sites"),
]

# Vite dev server origins (the SPA calls the API cross-origin during development)
_DEV_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# First path segments that belong to the API: never answered with the SPA's index.html
_API_ROOTS = {"api", "configs", "jobs", "listings", "preferences", "sites", "health",
              "docs", "redoc", "openapi.json"}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables, fail interrupted jobs, start scheduler. Shutdown: stop scheduler and runs."""
    create_db_and_tables()
    # Jobs still 'pending'/'running' belong to a previous process (runs are in-process tasks)
    reconcile_interrupted_jobs()
    from backend.scheduler import start_scheduler, stop_scheduler
    await start_scheduler()
    yield
    # Cancels runs in flight (each marks its job failed) before the browser is closed
    await stop_scheduler()
    # Close browser singleton on shutdown
    try:
        from apt_scrape.server import browser
        await browser.close()
    except Exception:
        pass


async def health():
    return {"status": "ok"}


def _web_dist_dir() -> Path:
    """Built SPA location: WEB_DIST_DIR env var, else <repo>/src/web/dist."""
    return Path(os.getenv("WEB_DIST_DIR") or _REPO_ROOT / "src" / "web" / "dist")


def _mount_spa(app: FastAPI, dist: Path) -> None:
    """Serve the built SPA: /assets via StaticFiles, other files directly, index.html otherwise.

    Must run after all API routes are registered so the catch-all never shadows them.
    """
    dist = dist.resolve()
    index = dist / "index.html"
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="web-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.split("/", 1)[0] in _API_ROOTS:
            raise HTTPException(404, "Not Found")
        if full_path:
            candidate = (dist / full_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(dist):
                return FileResponse(candidate)
        # index.html must not be cached, or a rebuilt SPA would load stale asset hashes
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app() -> FastAPI:
    app = FastAPI(title="apt_scrape backend", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_DEV_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for router, prefix, tag in _ROUTERS:
        app.include_router(router, prefix=prefix, tags=[tag])
    app.add_api_route("/health", health, methods=["GET"])

    # Same API under /api for the SPA (hidden from the OpenAPI schema to avoid duplicates)
    for router, prefix, _tag in _ROUTERS:
        app.include_router(router, prefix=f"/api{prefix}", include_in_schema=False)
    app.add_api_route("/api/health", health, methods=["GET"], include_in_schema=False)

    dist = _web_dist_dir()
    if (dist / "index.html").is_file():
        _mount_spa(app, dist)
        logger.info("Serving web UI from %s", dist)
    return app


app = create_app()
