"""Streamlit page: Job Monitor."""
import time
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Monitor", page_icon="📡", layout="wide")
st.title("📡 Job Monitor")

STATUS_COLORS = {"running": "🟡", "done": "🟢", "failed": "🔴", "pending": "⚪"}


def render():
    try:
        jobs = api.get("/jobs")
    except Exception as e:
        st.error(f"Cannot reach backend: {e}")
        return

    running = [j for j in jobs if j["status"] == "running"]
    recent = [j for j in jobs if j["status"] != "running"]

    if running:
        st.subheader("Active Jobs")
        for job in running:
            with st.container(border=True):
                st.markdown(f"{STATUS_COLORS['running']} **Job #{job['id']}** — config {job['config_id']} — `running`")
                st.caption(f"Started: {job.get('started_at', '—')}")
                log_lines = (job.get("log") or "").strip().split("\n")
                st.code("\n".join(log_lines[-10:]), language=None)
    else:
        st.info("No jobs currently running.")

    st.subheader("Recent Jobs")
    if recent:
        for job in recent:
            icon = STATUS_COLORS.get(job["status"], "⚪")
            with st.expander(
                f"{icon} Job #{job['id']} — config {job['config_id']} — `{job['status']}` — {job.get('listing_count', 0)} listings — {job.get('finished_at', '')}",
                expanded=False,
            ):
                try:
                    detail = api.get(f"/jobs/{job['id']}")
                    st.code(detail.get("log", "(no log)"), language=None)
                except Exception as e:
                    st.error(str(e))
    else:
        st.info("No completed jobs yet.")


render()

# Auto-refresh every 5 seconds
time.sleep(5)
st.rerun()
