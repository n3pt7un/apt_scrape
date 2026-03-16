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
import time
from pathlib import Path

import click

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


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
            "PYTHONPATH": str(REPO_ROOT / "src"),
        },
        "cwd": str(REPO_ROOT),
        "url": "http://localhost:8000/health",
    },
    "frontend": {
        "cmd": lambda: [
            _find_bin("streamlit"), "run",
            str(REPO_ROOT / "src" / "frontend" / "app.py"),
            "--server.port", "8501",
            "--server.address", "0.0.0.0",
        ],
        "env": {
            "BACKEND_URL": "http://localhost:8000",
        },
        "cwd": str(REPO_ROOT / "src" / "frontend"),
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
@click.option("-f", "--follow", "--stream", is_flag=True, help="Stream log output continuously (like tail -f).")
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
