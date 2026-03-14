"""Streamlit page: Search Configurations."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Search Configs", page_icon="⚙️", layout="wide")
st.title("⚙️ Search Configurations")

try:
    configs = api.get("/configs")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

if configs:
    for cfg in configs:
        days = cfg.get("schedule_days", [])
        schedule_str = f"{', '.join(d.capitalize() for d in days)} at {cfg.get('schedule_time','')}"
        with st.container(border=True):
            col1, col2, col3, col4 = st.columns([3, 2, 2, 2])
            with col1:
                st.markdown(f"**{cfg['name']}** — {cfg.get('city','')} / {cfg.get('area','')}")
                st.caption(f"{cfg.get('operation','')} · {cfg.get('min_price','')}–{cfg.get('max_price','')}€ · {schedule_str}")
            with col2:
                status = "🟢 enabled" if cfg["enabled"] else "⚫ disabled"
                st.write(status)
                if cfg.get("auto_analyse"):
                    st.caption("🤖 AI on")
                if cfg.get("auto_notion_push"):
                    st.caption("📝 Notion auto")
            with col3:
                if st.button("▶ Run now", key=f"run_{cfg['id']}"):
                    try:
                        api.post(f"/configs/{cfg['id']}/run")
                        st.success("Job started!")
                        st.switch_page("pages/2_Monitor.py")
                    except Exception as e:
                        st.error(str(e))
                if st.button("⏸ Toggle", key=f"tog_{cfg['id']}"):
                    try:
                        api.patch(f"/configs/{cfg['id']}/toggle")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with col4:
                if st.button("🗑 Delete", key=f"del_{cfg['id']}"):
                    try:
                        api.delete(f"/configs/{cfg['id']}")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
else:
    st.info("No search configs yet. Create one below.")

st.divider()
st.subheader("New Search Config")

with st.form("new_config"):
    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Config name", placeholder="Milano · Bicocca")
        city = st.text_input("City slug", value="milano")
        area = st.text_input("Area slug (optional)", placeholder="bicocca")
        operation = st.selectbox("Operation", ["affitto", "vendita"])
        property_type = st.text_input("Property types (comma-separated)", value="appartamenti,attici")
    with c2:
        min_price, max_price = st.slider("Price range (€)", 0, 5000, (700, 1200), step=50)
        min_sqm = st.number_input("Min sqm", min_value=0, value=50, step=5)
        min_rooms = st.selectbox("Min rooms", [1, 2, 3, 4, 5], index=1)
        start_page = st.number_input("Start page", min_value=1, value=1)
        end_page = st.number_input("End page", min_value=1, value=10)

    st.markdown("**Schedule**")
    sc1, sc2 = st.columns(2)
    with sc1:
        schedule_days = st.multiselect(
            "Days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            default=["mon", "wed", "fri"]
        )
    with sc2:
        schedule_time = st.time_input("Time (UTC)", value=None)

    st.markdown("**Rate limits & toggles**")
    rl1, rl2, rl3, rl4 = st.columns(4)
    with rl1:
        detail_concurrency = st.slider("Detail concurrency", 1, 10, 5)
    with rl2:
        vpn_rotate_batches = st.slider("VPN rotate batches", 1, 10, 3)
    with rl3:
        auto_analyse = st.toggle("AI analysis", value=True)
    with rl4:
        auto_notion_push = st.toggle("Notion auto-push", value=False)

    submitted = st.form_submit_button("Save Config")
    if submitted:
        time_str = schedule_time.strftime("%H:%M") if schedule_time else "08:00"
        payload = {
            "name": name, "city": city, "area": area or None,
            "operation": operation, "property_type": property_type,
            "min_price": min_price, "max_price": max_price,
            "min_sqm": min_sqm, "min_rooms": min_rooms,
            "start_page": start_page, "end_page": end_page,
            "schedule_days": schedule_days, "schedule_time": time_str,
            "detail_concurrency": detail_concurrency,
            "vpn_rotate_batches": vpn_rotate_batches,
            "auto_analyse": auto_analyse,
            "auto_notion_push": auto_notion_push,
            "enabled": True,
        }
        try:
            api.post("/configs", json=payload)
            st.success("Config saved!")
            st.rerun()
        except Exception as e:
            st.error(str(e))
