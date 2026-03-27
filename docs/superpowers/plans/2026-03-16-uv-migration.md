# uv Migration & Repo Reorganization Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate environment management to uv with a single `pyproject.toml`, register `apt` and `scr-apt` as proper console script entry points, and update docs to cover uv/conda/pip.

**Architecture:** Single `pyproject.toml` at repo root with optional extras `[backend]`, `[frontend]`, and uv dev-dependencies for test tooling. The root `apt` script moves into `apt_scrape/devctl.py` as an importable module. Three legacy `requirements.txt` files are deleted.

**Tech Stack:** uv, pyproject.toml (PEP 517/621), Click (existing), Python 3.11+

---

## Chunk 1: pyproject.toml + devctl module

### Task 1: Create `apt_scrape/devctl.py`

**Files:**
- Create: `apt_scrape/devctl.py`
- Delete: `apt` (root script, after this task)

The `apt` root script is a standalone Python file. It must become an importable module so uv can register it as a console script entry point. The content is identical — only the file location changes.

- [ ] **Step 1: Copy `apt` content into `apt_scrape/devctl.py`**

Create `apt_scrape/devctl.py` with this content (identical to root `apt` script):

```python
#!/usr/bin/env python3
"""apt_scrape.devctl — local dev CLI for apt_scrape.

Commands:
  start     Start backend and/or frontend
  stop      Stop running processes
  status    Show what's running
  logs      Tail logs
  restart   Restart a service
"""
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import click

REPO_ROOT = Path(__file__).resolve().parent.parent


def _find_bin(name: str) -> str:
    """Find a binary on PATH, fall back to running via sys.executable -m."""
    found = shutil.which(name)
    return found if found else name  # let the shell error if missing

PID_DIR = REPO_ROOT / ".pids"
LOG_DIR = REPO_ROOT / ".logs"

SERVICES = {
    "backend": {
        "cmd": lambda: [
            _find_bin("uvicorn"), "backend.main:app",
            "--host", "0.0.0.0", "--port", "8000",
        ],
        "env": {
            "DB_PATH": str(REPO_ROOT / "data" / "app.db"),
            "PREFERENCES_FILE": str(REPO_ROOT / "preferences.txt"),
            "PYTHONPATH": str(REPO_ROOT),
        },
        "cwd": str(REPO_ROOT),
        "url": "http://localhost:8000/health",
    },
    "frontend": {
        "cmd": lambda: [
            _find_bin("streamlit"), "run",
            str(REPO_ROOT / "frontend" / "app.py"),
            "--server.port", "8501",
            "--server.address", "0.0.0.0",
        ],
        "env": {
            "BACKEND_URL": "http://localhost:8000",
        },
        "cwd": str(REPO_ROOT / "frontend"),
        "url": "http://localhost:8501",
    },
}


def _pid_file(name: str) -> Path:
    PID_DIR.mkdir(exist_ok=True)
    return PID_DIR / f"{name}.pid"


def _log_file(name: str) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    return LOG_DIR / f"{name}.log"


def _read_pid(name: str) -> int | None:
    p = _pid_file(name)
    if not p.exists():
        return None
    try:
        return int(p.read_text().strip())
    except ValueError:
        return None


def _is_running(name: str) -> bool:
    pid = _read_pid(name)
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        _pid_file(name).unlink(missing_ok=True)
        return False


def _start_service(name: str, verbose: bool = True) -> bool:
    if _is_running(name):
        click.echo(f"  {name} already running (pid {_read_pid(name)})")
        return False

    svc = SERVICES[name]
    env = {**os.environ, **svc["env"]}
    log_path = _log_file(name)

    with open(log_path, "a") as logf:
        proc = subprocess.Popen(
            svc["cmd"](),
            cwd=svc["cwd"],
            env=env,
            stdout=logf,
            stderr=logf,
        )

    _pid_file(name).write_text(str(proc.pid))
    if verbose:
        click.echo(f"  ✓ {name} started  (pid {proc.pid})  logs → {log_path}")
    return True


def _stop_service(name: str) -> bool:
    pid = _read_pid(name)
    if pid is None or not _is_running(name):
        click.echo(f"  {name} not running")
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    _pid_file(name).unlink(missing_ok=True)
    click.echo(f"  ✓ {name} stopped  (pid {pid})")
    return True


# ── CLI ──────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """apt_scrape local dev CLI."""


@cli.command()
@click.argument("service", default="all", type=click.Choice(["all", "backend", "frontend"]))
@click.option("--wait", default=3, show_default=True, help="Seconds to wait before printing URLs.")
def start(service: str, wait: int):
    """Start backend, frontend, or both."""
    names = list(SERVICES) if service == "all" else [service]
    click.echo(f"Starting {', '.join(names)}...")
    for name in names:
        _start_service(name)

    if wait:
        time.sleep(wait)

    click.echo("")
    for name in names:
        url = SERVICES[name]["url"]
        status = "🟢 running" if _is_running(name) else "🔴 failed to start"
        click.echo(f"  {name:10s}  {status:20s}  {url}")


@cli.command()
@click.argument("service", default="all", type=click.Choice(["all", "backend", "frontend"]))
def stop(service: str):
    """Stop backend, frontend, or both."""
    names = list(SERVICES) if service == "all" else [service]
    click.echo(f"Stopping {', '.join(names)}...")
    for name in names:
        _stop_service(name)


@cli.command()
@click.argument("service", default="all", type=click.Choice(["all", "backend", "frontend"]))
def restart(service: str):
    """Restart backend, frontend, or both."""
    names = list(SERVICES) if service == "all" else [service]
    click.echo(f"Restarting {', '.join(names)}...")
    for name in names:
        _stop_service(name)
    time.sleep(1)
    for name in names:
        _start_service(name)


@cli.command()
def status():
    """Show running status and URLs."""
    click.echo(f"{'SERVICE':<12} {'STATUS':<12} {'PID':<8} {'URL'}")
    click.echo("─" * 55)
    for name, svc in SERVICES.items():
        running = _is_running(name)
        pid = _read_pid(name) or "—"
        icon = "🟢" if running else "⚫"
        state = "running" if running else "stopped"
        click.echo(f"{name:<12} {icon} {state:<10} {str(pid):<8} {svc['url']}")


@cli.command()
@click.argument("service", type=click.Choice(["backend", "frontend"]))
@click.option("-n", "--lines", default=50, show_default=True, help="Number of lines to show.")
@click.option("-f", "--follow", is_flag=True, help="Follow log output (like tail -f).")
def logs(service: str, lines: int, follow: bool):
    """Tail logs for a service."""
    log_path = _log_file(service)
    if not log_path.exists():
        click.echo(f"No log file yet for {service}: {log_path}")
        return
    cmd = ["tail", f"-{lines}", "-f" if follow else "", str(log_path)]
    cmd = [c for c in cmd if c]  # remove empty strings
    try:
        subprocess.run(cmd)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    cli()
```

**Key difference from root `apt`:** `REPO_ROOT` is now `Path(__file__).resolve().parent.parent` (two levels up from `apt_scrape/devctl.py`) instead of `Path(__file__).resolve().parent` (one level up from root `apt`).

- [ ] **Step 2: Smoke-test the module import**

```bash
cd /path/to/apt_scrape
python -c "from apt_scrape.devctl import cli; print('OK')"
```

Expected: `OK` (no import errors)

- [ ] **Step 3: Delete root `apt` script**

```bash
rm apt
```

- [ ] **Step 4: Commit**

```bash
git add apt_scrape/devctl.py apt
git commit -m "refactor: move apt CLI script into apt_scrape/devctl.py for uv entry point"
```

---

### Task 2: Create `pyproject.toml`

**Files:**
- Create: `pyproject.toml`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "apt-scrape"
version = "0.1.0"
description = "Scrape and monitor Italian real estate listings"
requires-python = ">=3.11"

dependencies = [
    "mcp>=1.0.0",
    "pydantic>=2.0.0",
    "beautifulsoup4>=4.12.0",
    "camoufox[geoip]>=0.4.0",
    "lxml>=5.0.0",
    "pyyaml>=6.0",
    "python-dotenv>=1.0",
    "pproxy>=2.7.8",
    "click>=8.1.0",
    "langgraph>=0.2",
    "langchain-openai>=0.2",
    "langchain-core>=0.3",
    "notion-client==2.2.1",
]

[project.optional-dependencies]
backend = [
    "fastapi==0.115.6",
    "uvicorn[standard]==0.32.1",
    "apscheduler==3.10.4",
    "sqlmodel==0.0.21",
    "aiofiles==24.1.0",
    "httpx==0.28.1",
]
frontend = [
    "streamlit==1.42.0",
    "httpx==0.28.1",
]

[project.scripts]
apt     = "apt_scrape.devctl:cli"
scr-apt = "apt_scrape.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest",
    "pytest-asyncio>=0.23",
]

[tool.hatch.build.targets.wheel]
packages = ["apt_scrape", "backend", "frontend"]
```

- [ ] **Step 2: Install with uv and verify entry points**

```bash
uv sync --all-extras
```

Expected: uv resolves and installs all deps, creates/updates `.venv`, registers `apt` and `scr-apt` scripts in `.venv/bin/`.

- [ ] **Step 3: Test entry points work**

```bash
uv run apt --help
uv run scr-apt --help
```

Expected: Both print their Click help text without errors.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat: add pyproject.toml with uv extras and console script entry points"
```

---

### Task 3: Delete legacy `requirements.txt` files

**Files:**
- Delete: `requirements.txt`
- Delete: `backend/requirements.txt`
- Delete: `frontend/requirements.txt`

- [ ] **Step 1: Delete the three files**

```bash
rm requirements.txt backend/requirements.txt frontend/requirements.txt
```

- [ ] **Step 2: Verify tests still pass**

```bash
uv run pytest tests/ -x -q
```

Expected: same pass/fail count as before (no import errors from missing deps).

- [ ] **Step 3: Commit**

```bash
git add requirements.txt backend/requirements.txt frontend/requirements.txt
git commit -m "chore: remove legacy requirements.txt files (consolidated into pyproject.toml)"
```

---

## Chunk 2: Documentation

### Task 4: Rewrite `docs/running-locally.md`

**Files:**
- Modify: `docs/running-locally.md`

- [ ] **Step 1: Replace the file content**

Replace the entire file with:

```markdown
# Running Locally

This guide covers running the **FastAPI backend** (port 8000) and **Streamlit frontend** (port 8501) without Docker.

> **Docker:** Docker support is not currently maintained. `Dockerfile`s and `docker-compose.yml` are preserved for future use but may not work out of the box.

---

## Setup

Pick your environment manager:

- [uv (recommended)](#uv-recommended)
- [conda](#conda)
- [pip / venv](#pip--venv)

---

### uv (recommended)

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. Install it with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
git clone https://github.com/tarasivaniv/rent-fetch.git
cd rent-fetch

uv sync --all-extras          # installs all deps into .venv
camoufox fetch                # downloads browser binary (~100 MB, one-time)

cp .env.example .env          # fill in API keys
mkdir -p data && touch preferences.txt

apt start                     # starts backend + frontend
```

Open **http://127.0.0.1:8501**.

---

### conda

```bash
git clone https://github.com/tarasivaniv/rent-fetch.git
cd rent-fetch

conda create -n apt-scrape python=3.11 -y
conda activate apt-scrape

pip install -e ".[backend,frontend]"
camoufox fetch

cp .env.example .env
mkdir -p data && touch preferences.txt

python -m apt_scrape.devctl start
```

> `apt` and `scr-apt` entry points are available inside the activated conda env.

---

### pip / venv

```bash
git clone https://github.com/tarasivaniv/rent-fetch.git
cd rent-fetch

python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e ".[backend,frontend]"
camoufox fetch

cp .env.example .env
mkdir -p data && touch preferences.txt

apt start
```

---

## apt CLI

`apt` manages backend and frontend processes.

```bash
apt <command> [service]
```

| Command | Description |
|---------|-------------|
| `apt start` | Start backend and frontend |
| `apt start backend` | Start backend only |
| `apt start frontend` | Start frontend only |
| `apt stop` | Stop all services |
| `apt stop backend` | Stop backend only |
| `apt status` | Show running PIDs and URLs |
| `apt restart` | Restart all services |
| `apt restart frontend` | Restart frontend only |
| `apt logs backend` | Show last 50 lines of backend log |
| `apt logs frontend -f` | Follow frontend log (like `tail -f`) |
| `apt logs backend -n 200` | Show last 200 lines |

Logs: `.logs/backend.log` and `.logs/frontend.log`.

---

## Manual start (without apt)

**Backend:**

```bash
export PYTHONPATH=.
export DB_PATH=data/app.db
export PREFERENCES_FILE=data/preferences.txt
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

**Frontend** (separate terminal):

```bash
export BACKEND_URL=http://127.0.0.1:8000
streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0
```

---

## Troubleshooting

- **"No module named 'fastapi'"** — run `pip install -e ".[backend]"` or `uv sync --extra backend`
- **"No module named 'backend'"** — set `PYTHONPATH=.` or run from repo root
- **DB or preferences errors** — ensure `data/` exists and `DB_PATH`/`PREFERENCES_FILE` point to writable paths

---

## Environment Variables

Copy `.env.example` to `.env`. All are optional unless marked required.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DB_PATH` | no | `data/app.db` | SQLite database path |
| `PREFERENCES_FILE` | no | `preferences.txt` | Plain-text file for AI scoring |
| `BACKEND_URL` | no | `http://127.0.0.1:8000` | URL the frontend uses to reach the backend |
| `OPENROUTER_API_KEY` | for AI scoring | — | OpenRouter API key |
| `OPENROUTER_MODEL` | no | `google/gemini-2.0-flash-lite` | Model slug passed to OpenRouter |
| `ANALYSIS_CONCURRENCY` | no | `5` | Max parallel AI scoring calls |
| `NOTION_API_KEY` | for Notion push | — | Notion integration token |
| `NOTION_APARTMENTS_DB_ID` | for Notion push | — | Notion database ID for apartment listings |
| `NOTION_AREAS_DB_ID` | for Notion push | — | Notion database ID for areas |
| `NOTION_AGENCIES_DB_ID` | for Notion push | — | Notion database ID for agencies |
| `NORDVPN_USER` | for proxy rotation | — | NordVPN service username |
| `NORDVPN_PASS` | for proxy rotation | — | NordVPN service password |
| `NORDVPN_SERVERS` | for proxy rotation | — | Comma-separated SOCKS5 hostnames |
| `PROXY_ROTATE_EVERY` | no | `15` | Requests before rotating proxy |

---

## AI Scoring Setup

1. Set `OPENROUTER_API_KEY` in `.env`
2. Optionally set `OPENROUTER_MODEL`
3. Edit `preferences.txt` — one preference per line:
   ```
   I want at least 2 bedrooms
   Prefer quiet streets
   Max 1000 EUR/month
   Close to a metro stop
   ```
4. Enable AI scoring per Search Config in the dashboard

---

## Notion Integration

1. Create a Notion integration at [notion.so/my-integrations](https://www.notion.so/my-integrations) and copy the token to `NOTION_API_KEY`
2. Create three Notion databases and share each with your integration
3. Copy each database ID to `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID`
4. Enable "Push to Notion" per Search Config in the dashboard
```

- [ ] **Step 2: Commit**

```bash
git add docs/running-locally.md
git commit -m "docs: rewrite running-locally.md with uv/conda/pip sections and Docker deprecation note"
```

---

### Task 5: Update `README.md` Setup section

**Files:**
- Modify: `README.md`

The README's Setup section currently shows `python -m venv` + `pip install -r`. Replace it with uv-first quickstart and a link to full docs for conda/pip alternatives. Also add the Docker deprecation note.

- [ ] **Step 1: Replace the Setup section in README.md**

Find the `## Setup` section (lines 73–101 approximately) and replace with:

```markdown
## Setup

### Local (recommended)

Install [uv](https://docs.astral.sh/uv/) if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then:

```bash
git clone https://github.com/tarasivaniv/rent-fetch.git
cd rent-fetch

uv sync --all-extras            # installs all deps
camoufox fetch                  # downloads browser binary (~100 MB, one-time)

cp .env.example .env            # fill in API keys (see Environment Variables)
mkdir -p data && touch preferences.txt

apt start                       # starts backend (port 8000) + frontend (port 8501)
```

Open **http://127.0.0.1:8501**.

For **conda** or **pip/venv** setup, and for manual start without `apt`, see [docs/running-locally.md](docs/running-locally.md).

### Docker

> Docker support is not currently maintained. `Dockerfile`s and `docker-compose.yml` are preserved for future use but may not work out of the box.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: update README setup section to lead with uv, add Docker deprecation note"
```

---

## Verification Checklist

After all tasks are complete, verify:

- [ ] `uv sync --all-extras` completes without errors
- [ ] `uv run apt --help` prints the apt CLI help
- [ ] `uv run scr-apt --help` prints the scraping CLI help
- [ ] `uv run apt status` runs without errors
- [ ] `uv run pytest tests/ -x -q` passes (same as before)
- [ ] `requirements.txt`, `backend/requirements.txt`, `frontend/requirements.txt` are gone
- [ ] Root `apt` script is gone
- [ ] `apt_scrape/devctl.py` exists and imports cleanly
- [ ] `docs/running-locally.md` has uv, conda, and pip sections
- [ ] `README.md` setup section leads with uv
