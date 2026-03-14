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


def render(jobs):
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
                    if st.button("Cancel & Delete", key=f"del_run_{job['id']}", use_container_width=True):
                        api.delete(f"/jobs/{job['id']}")
                        st.rerun()
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
                c_del, c_log = st.columns([1, 5])
                with c_del:
                    if st.button("Delete", key=f"del_rec_{job['id']}", use_container_width=True):
                        try:
                            api.delete(f"/jobs/{job['id']}")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
                with c_log:
                    try:
                        detail = api.get(f"/jobs/{job['id']}")
                        st.code(detail.get("log", "(no log)"), language=None)
                    except Exception as e:
                        st.error(str(e))
    else:
        st.info("No completed jobs yet.")


try:
    jobs = api.get("/jobs")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    jobs = []
render(jobs)

# Auto-refresh only when at least one job is running
running = [j for j in jobs if j.get("status") == "running"]
if running:
    time.sleep(5)
    st.rerun()
