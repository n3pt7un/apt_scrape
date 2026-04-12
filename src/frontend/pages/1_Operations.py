"""Streamlit page: Operations — pipeline health, trends, and activity feed."""
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import api
import theme

st.set_page_config(page_title="Operations", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Operations")

# ── Config name lookup ───────────────────────────────────────────────────────
try:
    configs_list = api.get("/configs")
    config_names = {c["id"]: c["name"] for c in configs_list}
except Exception:
    configs_list = []
    config_names = {}


def cfg_label(config_id):
    name = config_names.get(config_id)
    return f"{name}" if name else f"#{config_id}"


def _fmt_duration(sec):
    if sec is None:
        return "—"
    sec = int(sec)
    if sec < 60:
        return f"{sec}s"
    return f"{sec // 60}m {sec % 60}s"


def _fmt_ago(seconds):
    """Human-friendly relative time."""
    if seconds is None:
        return "—"
    seconds = int(seconds)
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


# ══════════════════════════════════════════════════════════════════════════════
# ZONE 1: Health Strip
# ══════════════════════════════════════════════════════════════════════════════
try:
    health = api.get("/jobs/health")
except Exception:
    health = {}

if health:
    h1, h2, h3, h4, h5 = st.columns(5)

    def _health_metric(col, label, status_key, value):
        status = health.get(status_key, "healthy")
        color = theme.health_color(status)
        dot = theme.status_dot(color, size=10)
        col.markdown(
            f'{dot} <span style="color:{theme.TEXT_SECONDARY};font-size:0.75rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">{label}</span><br>'
            f'<span style="font-family:{theme.MONO_FONT};font-size:1.2rem;'
            f'color:{theme.TEXT_PRIMARY}">{value}</span>',
            unsafe_allow_html=True,
        )

    pipeline_val = health.get("last_job_status", "—")
    if health.get("last_job_ago_sec") is not None:
        pipeline_val += f" · {_fmt_ago(health['last_job_ago_sec'])}"
    _health_metric(h1, "Pipeline", "pipeline_status", pipeline_val)

    sched_val = "all on time"
    missed = health.get("missed_schedules", [])
    if missed:
        sched_val = f"{len(missed)} missed"
    _health_metric(h2, "Schedule", "schedule_health", sched_val)

    yield_val = f"{health.get('yield_7d_avg', 0):.0f}/run"
    _health_metric(h3, "Yield (7d)", "yield_trend", yield_val)

    dupe_val = f"{health.get('dupe_rate_7d', 0):.0%}"
    dupe_status = health.get("dupe_rate_trend", "stable")
    dupe_pct = health.get("dupe_rate_7d", 0)
    if dupe_pct > 0.6:
        dupe_color_status = "critical"
    elif dupe_pct > 0.3:
        dupe_color_status = "warning"
    else:
        dupe_color_status = "healthy"
    color = theme.health_color(dupe_color_status)
    dot = theme.status_dot(color, size=10)
    h4.markdown(
        f'{dot} <span style="color:{theme.TEXT_SECONDARY};font-size:0.75rem;'
        f'text-transform:uppercase;letter-spacing:0.05em">Dupe Rate</span><br>'
        f'<span style="font-family:{theme.MONO_FONT};font-size:1.2rem;'
        f'color:{theme.TEXT_PRIMARY}">{dupe_val}</span>'
        f' <span style="color:{theme.TEXT_MUTED};font-size:0.75rem">{dupe_status}</span>',
        unsafe_allow_html=True,
    )

    cost_val = f"${health.get('ai_cost_7d', 0):.2f}"
    cost_prev = health.get("ai_cost_prev_7d", 0)
    cost_7d = health.get("ai_cost_7d", 0)
    if cost_prev > 0 and cost_7d > cost_prev * 2:
        cost_color_status = "warning"
    else:
        cost_color_status = "healthy"
    color = theme.health_color(cost_color_status)
    dot = theme.status_dot(color, size=10)
    h5.markdown(
        f'{dot} <span style="color:{theme.TEXT_SECONDARY};font-size:0.75rem;'
        f'text-transform:uppercase;letter-spacing:0.05em">AI Cost (7d)</span><br>'
        f'<span style="font-family:{theme.MONO_FONT};font-size:1.2rem;'
        f'color:{theme.TEXT_PRIMARY}">{cost_val}</span>',
        unsafe_allow_html=True,
    )

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ZONE 2: Trend Charts
# ══════════════════════════════════════════════════════════════════════════════
try:
    overall = api.get("/jobs/stats/overall")
except Exception:
    overall = {}

timeline = overall.get("timeline", [])

if timeline:
    chart_left, chart_right = st.columns(2)

    with chart_left:
        # Listings over time — stacked area
        st.markdown(
            f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">Listings Over Time</span>',
            unsafe_allow_html=True,
        )
        dates = [t["started_at"] for t in timeline]
        unique = [t["listing_count"] for t in timeline]
        dupes = [t["dupes_removed"] for t in timeline]

        fig_listings = go.Figure()
        fig_listings.add_trace(go.Scatter(
            x=dates, y=unique, mode="lines", name="Unique",
            fill="tozeroy", line=dict(color=theme.GREEN, width=2),
            fillcolor="rgba(0,217,126,0.15)",
        ))
        fig_listings.add_trace(go.Scatter(
            x=dates, y=dupes, mode="lines", name="Dupes",
            fill="tozeroy", line=dict(color=theme.RED, width=2),
            fillcolor="rgba(230,55,87,0.15)",
        ))
        fig_listings.update_layout(**theme.PLOTLY_LAYOUT, height=280, showlegend=True)
        st.plotly_chart(fig_listings, use_container_width=True)

        # Success rate timeline
        st.markdown(
            f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">Job Success Rate</span>',
            unsafe_allow_html=True,
        )
        try:
            all_jobs = api.get("/jobs")
        except Exception:
            all_jobs = []

        if all_jobs:
            sorted_jobs = sorted(all_jobs, key=lambda j: j.get("started_at", ""))
            success_dates = []
            success_rates = []
            window = 7
            for i, j in enumerate(sorted_jobs):
                if j.get("status") in ("done", "failed"):
                    chunk = sorted_jobs[max(0, i - window + 1):i + 1]
                    chunk = [c for c in chunk if c.get("status") in ("done", "failed")]
                    if chunk:
                        rate = sum(1 for c in chunk if c["status"] == "done") / len(chunk)
                        success_dates.append(j.get("started_at"))
                        success_rates.append(round(rate * 100, 1))

            if success_dates:
                fig_success = go.Figure()
                fig_success.add_trace(go.Scatter(
                    x=success_dates, y=success_rates, mode="lines",
                    line=dict(color=theme.CYAN, width=2),
                    fill="tozeroy", fillcolor="rgba(0,184,217,0.1)",
                ))
                fig_success.update_layout(
                    **theme.PLOTLY_LAYOUT, height=200, showlegend=False,
                    yaxis=dict(
                        **theme.PLOTLY_LAYOUT["yaxis"],
                        range=[0, 105], ticksuffix="%",
                    ),
                )
                st.plotly_chart(fig_success, use_container_width=True)

    with chart_right:
        # Price per sqm by area
        price_sqm = overall.get("price_per_sqm_by_area", {})
        if price_sqm:
            st.markdown(
                f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
                f'text-transform:uppercase;letter-spacing:0.05em">Price per sqm by Area</span>',
                unsafe_allow_html=True,
            )
            sorted_areas = sorted(price_sqm.items(), key=lambda x: -x[1])
            areas = [a[0] or "whole city" for a in sorted_areas]
            values = [a[1] for a in sorted_areas]

            fig_price = go.Figure()
            fig_price.add_trace(go.Bar(
                x=values, y=areas, orientation="h",
                marker=dict(color=theme.BLUE, line=dict(width=0)),
                text=[f"€{v:.0f}" for v in values],
                textposition="outside",
                textfont=dict(color=theme.TEXT_SECONDARY, size=11),
            ))
            fig_price.update_layout(
                **theme.PLOTLY_LAYOUT, height=280,
                yaxis=dict(**theme.PLOTLY_LAYOUT["yaxis"], autorange="reversed"),
                xaxis=dict(**theme.PLOTLY_LAYOUT["xaxis"], title="€/sqm"),
            )
            st.plotly_chart(fig_price, use_container_width=True)

        # Run duration trend
        st.markdown(
            f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
            f'text-transform:uppercase;letter-spacing:0.05em">Run Duration Trend</span>',
            unsafe_allow_html=True,
        )
        dur_dates = [t["started_at"] for t in timeline if t.get("duration_sec")]
        dur_values = [t["duration_sec"] for t in timeline if t.get("duration_sec")]

        if dur_dates:
            fig_dur = go.Figure()
            fig_dur.add_trace(go.Scatter(
                x=dur_dates, y=dur_values, mode="lines+markers",
                line=dict(color=theme.AMBER, width=2),
                marker=dict(size=5, color=theme.AMBER),
            ))
            fig_dur.update_layout(
                **theme.PLOTLY_LAYOUT, height=200, showlegend=False,
                yaxis=dict(**theme.PLOTLY_LAYOUT["yaxis"], title="seconds"),
            )
            st.plotly_chart(fig_dur, use_container_width=True)

st.markdown("---")

# ══════════════════════════════════════════════════════════════════════════════
# ZONE 3: Recent Activity Feed
# ══════════════════════════════════════════════════════════════════════════════
st.markdown(
    f'<span style="color:{theme.TEXT_SECONDARY};font-size:0.85rem;'
    f'text-transform:uppercase;letter-spacing:0.05em">Recent Activity</span>',
    unsafe_allow_html=True,
)

try:
    jobs = api.get("/jobs")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    jobs = []

STATUS_COLORS_MAP = {
    "running": theme.AMBER,
    "done": theme.GREEN,
    "failed": theme.RED,
    "pending": theme.TEXT_MUTED,
}

running = [j for j in jobs if j["status"] == "running"]
recent = [j for j in jobs if j["status"] != "running"]

# Active jobs first
if running:
    for job in running:
        with st.container(border=True):
            c1, c2 = st.columns([4, 1])
            with c1:
                dot = theme.status_dot(theme.AMBER, size=10)
                st.markdown(
                    f'{dot} **{cfg_label(job["config_id"])}** · '
                    f'<span style="font-family:{theme.MONO_FONT};color:{theme.AMBER}">running</span> · '
                    f'started {str(job.get("started_at", ""))[:16]}',
                    unsafe_allow_html=True,
                )
            with c2:
                if st.button("Cancel", key=f"cancel_{job['id']}", type="primary", use_container_width=True):
                    try:
                        api.post(f"/jobs/{job['id']}/cancel")
                        st.success("Job cancelled.")
                    except Exception as e:
                        st.error(f"Cancel failed: {e}")
                    time.sleep(1)
                    st.rerun()
            log_lines = (job.get("log") or "").strip().split("\n")
            st.code("\n".join(log_lines[-10:]), language=None)

# Recent jobs
for job in recent[:20]:
    color = STATUS_COLORS_MAP.get(job["status"], theme.TEXT_MUTED)
    dot = theme.status_dot(color, size=8)

    scraped = job.get("scraped_count") or 0
    unique = job.get("listing_count") or 0
    dupes = job.get("dupes_removed") or 0
    yield_str = f"{scraped} found, {unique} unique, {dupes} dupes"

    duration = None
    if job.get("finished_at") and job.get("started_at"):
        from datetime import datetime
        try:
            start = datetime.fromisoformat(str(job["started_at"]))
            end = datetime.fromisoformat(str(job["finished_at"]))
            duration = (end - start).total_seconds()
        except Exception:
            pass

    finished_str = str(job.get("finished_at") or "")[:16]
    cost_str = f"${job.get('ai_cost_usd', 0) or 0:.2f}"

    label = (
        f"{cfg_label(job['config_id'])} · {job['status']} · "
        f"{yield_str} · {_fmt_duration(duration)} · {cost_str} · {finished_str}"
    )

    with st.expander(label, expanded=False):
        if job["status"] == "done":
            try:
                stats = api.get(f"/jobs/{job['id']}/stats")
                sc1, sc2, sc3, sc4, sc5 = st.columns(5)
                sc1.metric("Found", stats.get("scraped_count") or "—")
                sc2.metric("Unique", stats.get("listing_count") or "—")
                sc3.metric("Dupes", stats.get("dupes_removed") or "—")
                avg = stats.get("avg_price_eur")
                sc4.metric("Avg price", f"€{avg:,.0f}" if avg else "—")
                sc5.metric("Duration", _fmt_duration(stats.get("duration_sec")))

                area_stats = stats.get("area_stats") or {}
                if len(area_stats) > 1:
                    st.caption("**By area:** " + "  ·  ".join(
                        f"{a or 'whole city'}: {n}" for a, n in sorted(area_stats.items(), key=lambda x: -x[1])
                    ))
            except Exception:
                pass
            st.divider()

        bc1, bc2, bc3 = st.columns([1, 1, 4])
        with bc1:
            if st.button("Delete", key=f"del_{job['id']}", use_container_width=True):
                try:
                    api.delete(f"/jobs/{job['id']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
        with bc2:
            if job["status"] == "done" and st.button("Notion Push", key=f"notion_{job['id']}", use_container_width=True):
                try:
                    job_listings = api.get("/listings", params={"job_id": job["id"], "limit": 1000})
                    if not job_listings:
                        st.warning("No listings found for this job.")
                    else:
                        listing_ids = [l["id"] for l in job_listings]
                        result = api.post("/listings/notion-push", json={"listing_ids": listing_ids})
                        st.success(f"Pushed {result['pushed']}, skipped {result['skipped']}.")
                        if result.get("errors"):
                            st.error(f"Errors: {result['errors']}")
                        st.rerun()
                except Exception as e:
                    st.error(f"Push failed: {e}")

        try:
            detail = api.get(f"/jobs/{job['id']}")
            st.code(detail.get("log", "(no log)"), language=None)
        except Exception as e:
            st.error(str(e))

# Auto-refresh when jobs are running
if running:
    time.sleep(5)
    st.rerun()
