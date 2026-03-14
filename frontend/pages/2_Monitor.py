"""Streamlit page: Job Monitor."""
import time
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Monitor", page_icon="📡", layout="wide")
st.title("📡 Job Monitor")

STATUS_ICON = {"running": "🟡", "done": "🟢", "failed": "🔴", "pending": "⚪"}

# Build config name map
try:
    configs_list = api.get("/configs")
    config_names = {c["id"]: c["name"] for c in configs_list}
except Exception:
    config_names = {}


def cfg_label(config_id):
    name = config_names.get(config_id)
    return f"{name} (#{config_id})" if name else f"#{config_id}"


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
                c1, c2 = st.columns([3, 1])
                with c1:
                    st.markdown(
                        f"🟡 **Job #{job['id']}** — {cfg_label(job['config_id'])} — `running`"
                    )
                    st.caption(f"Started: {str(job.get('started_at', '—'))[:19]}")
                with c2:
                    st.caption(f"Triggered by: {job.get('triggered_by', '—')}")
                log_lines = (job.get("log") or "").strip().split("\n")
                st.code("\n".join(log_lines[-10:]), language=None)
    else:
        st.info("No jobs currently running.")

    st.subheader("Recent Jobs")
    if recent:
        for job in recent:
            icon = STATUS_ICON.get(job["status"], "⚪")
            listings_str = f"{job.get('listing_count') or 0} listings"
            finished = str(job.get("finished_at") or "")[:16]
            label = (
                f"{icon} Job #{job['id']} · {cfg_label(job['config_id'])} · "
                f"`{job['status']}` · {listings_str} · {finished}"
            )
            with st.expander(label, expanded=False):
                try:
                    detail = api.get(f"/jobs/{job['id']}")
                    st.code(detail.get("log", "(no log)"), language=None)
                except Exception as e:
                    st.error(str(e))
    else:
        st.info("No completed jobs yet.")


render()

# Auto-refresh every 5 seconds while any job is running
time.sleep(5)
st.rerun()
