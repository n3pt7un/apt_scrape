"""Streamlit page: Search Configurations."""
import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import streamlit as st
import api

st.set_page_config(page_title="Search Configs", page_icon="⚙️", layout="wide")
st.title("⚙️ Search Configurations")

@st.dialog("Search Configuration", width="large")
def config_dialog(edit_data=None):
    editing = edit_data is not None
    key_suffix = "ef" if editing else "nf"

    if editing:
        _raw = edit_data
        defaults = {
            "name": _raw.get("name", ""),
            "city": _raw.get("city", "milano"),
            "area": _raw.get("area") or "",
            "operation": _raw.get("operation", "affitto"),
            "property_type": _raw.get("property_type", "appartamenti"),
            "min_price": _raw.get("min_price") if _raw.get("min_price") is not None else 700,
            "max_price": _raw.get("max_price") if _raw.get("max_price") is not None else 1200,
            "min_sqm": _raw.get("min_sqm") if _raw.get("min_sqm") is not None else 0,
            "min_rooms": _raw.get("min_rooms") if _raw.get("min_rooms") is not None else 1,
            "start_page": _raw.get("start_page") or 1,
            "end_page": _raw.get("end_page") or 10,
            "schedule_days": _raw.get("schedule_days") or [],
            "schedule_time": _raw.get("schedule_time") or "08:00",
            "detail_concurrency": _raw.get("detail_concurrency") or 5,
            "vpn_rotate_batches": _raw.get("vpn_rotate_batches") or 3,
            "auto_analyse": _raw.get("auto_analyse", True),
            "auto_notion_push": _raw.get("auto_notion_push", False),
            "site_id": _raw.get("site_id") or "immobiliare",
            "request_delay_sec": _raw.get("request_delay_sec") if _raw.get("request_delay_sec") is not None else 2.0,
            "page_delay_sec": _raw.get("page_delay_sec") if _raw.get("page_delay_sec") is not None else 0.0,
            "timeout_sec": _raw.get("timeout_sec"),
        }
    else:
        defaults = {
            "name": "",
            "city": "milano",
            "area": "",
            "operation": "affitto",
            "property_type": "appartamenti,attici",
            "min_price": 700,
            "max_price": 1200,
            "min_sqm": 0,
            "min_rooms": 1,
            "start_page": 1,
            "end_page": 10,
            "schedule_days": [],
            "schedule_time": "08:00",
            "detail_concurrency": 5,
            "vpn_rotate_batches": 3,
            "auto_analyse": True,
            "auto_notion_push": False,
            "site_id": "immobiliare",
            "request_delay_sec": 2.0,
            "page_delay_sec": 0.0,
            "timeout_sec": None,
        }

    with st.form("config_form"):
        st.markdown("**Basics**")
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Config name", value=defaults["name"], key=f"{key_suffix}_name", placeholder="Milano · Bicocca")
            _sites = site_ids or ["immobiliare", "casa", "idealista"]
            _site_index = _sites.index(defaults["site_id"]) if defaults["site_id"] in _sites else 0
            site_id = st.selectbox("Site", _sites, index=_site_index, key=f"{key_suffix}_site_id")
            city = st.text_input("City slug", value=defaults["city"], key=f"{key_suffix}_city")
            area_options = []
            try:
                area_options = api.get(f"/sites/{site_id}/areas") or []
            except Exception:
                base_site = (site_id.split("-")[0] if "-" in site_id else site_id)
                area_options = list(api.DEFAULT_AREAS_BY_SITE.get(base_site, api.DEFAULT_AREAS))
            if not area_options:
                base_site = (site_id.split("-")[0] if "-" in site_id else site_id)
                area_options = list(api.DEFAULT_AREAS_BY_SITE.get(base_site, api.DEFAULT_AREAS))
            if "" not in area_options:
                area_options = [""] + area_options
            if defaults["area"] and defaults["area"] not in area_options:
                area_options = [defaults["area"]] + area_options
            area_index = area_options.index(defaults["area"]) if defaults["area"] in area_options else 0
            area = st.selectbox("Area (optional)", area_options, index=area_index, key=f"{key_suffix}_area")
            operation = st.selectbox("Operation", ["affitto", "vendita"], index=["affitto", "vendita"].index(defaults["operation"]), key=f"{key_suffix}_operation")
            property_type = st.text_input("Property types (comma-separated)", value=defaults["property_type"], key=f"{key_suffix}_property_type")
        with c2:
            min_price, max_price = st.slider("Price range (€)", 0, 5000, (defaults["min_price"], defaults["max_price"]), step=50, key=f"{key_suffix}_price")
            min_sqm = st.number_input("Min sqm", min_value=0, step=5, value=defaults["min_sqm"], key=f"{key_suffix}_min_sqm")
            min_rooms = st.selectbox("Min rooms", [1, 2, 3, 4, 5], index=[1, 2, 3, 4, 5].index(defaults["min_rooms"]) if defaults["min_rooms"] in [1, 2, 3, 4, 5] else 0, key=f"{key_suffix}_min_rooms")
            start_page = st.number_input("Start page", min_value=1, value=defaults["start_page"], key=f"{key_suffix}_start_page")
            end_page = st.number_input("End page", min_value=1, value=defaults["end_page"], key=f"{key_suffix}_end_page")

        st.markdown("**Schedule**")
        sc1, sc2 = st.columns(2)
        with sc1:
            schedule_days = st.multiselect("Days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], default=defaults["schedule_days"], key=f"{key_suffix}_days")
        with sc2:
            h, m = (defaults["schedule_time"] or "08:00").split(":")[:2]
            schedule_time = st.time_input("Time (UTC)", value=datetime.time(int(h), int(m)), key=f"{key_suffix}_time")

        st.markdown("**Rate limiting**")
        rl1, rl2, rl3 = st.columns(3)
        with rl1:
            request_delay_sec = st.number_input("Request delay (sec)", min_value=0.0, step=0.5, value=float(defaults["request_delay_sec"]), key=f"{key_suffix}_request_delay")
        with rl2:
            page_delay_sec = st.number_input("Page delay (sec)", min_value=0.0, step=0.5, value=float(defaults["page_delay_sec"]), key=f"{key_suffix}_page_delay")
        with rl3:
            timeout_sec = st.number_input("Timeout (sec, optional)", min_value=0, value=defaults["timeout_sec"] or 0, key=f"{key_suffix}_timeout")
            if timeout_sec == 0:
                timeout_sec = None

        st.markdown("**Concurrency & toggles**")
        rl4, rl5, rl6, rl7 = st.columns(4)
        with rl4:
            detail_concurrency = st.slider("Detail concurrency", 1, 10, defaults["detail_concurrency"], key=f"{key_suffix}_concurrency")
        with rl5:
            vpn_rotate_batches = st.slider("VPN rotate batches", 1, 10, defaults["vpn_rotate_batches"], key=f"{key_suffix}_vpn")
        with rl6:
            auto_analyse = st.toggle("AI analysis", value=defaults["auto_analyse"], key=f"{key_suffix}_analyse")
        with rl7:
            auto_notion_push = st.toggle("Notion auto-push", value=defaults["auto_notion_push"], key=f"{key_suffix}_notion")

        submitted = st.form_submit_button("Update Config" if editing else "Save Config", type="primary")

    if submitted:
        time_str = schedule_time.strftime("%H:%M") if schedule_time else "08:00"
        payload = {
            "name": name or "Unnamed",
            "city": city or "milano",
            "area": area or None,
            "operation": operation,
            "property_type": property_type or "appartamenti",
            "min_price": min_price,
            "max_price": max_price,
            "min_sqm": int(min_sqm) if min_sqm is not None else None,
            "min_rooms": min_rooms,
            "start_page": int(start_page),
            "end_page": int(end_page),
            "schedule_days": schedule_days,
            "schedule_time": time_str,
            "detail_concurrency": detail_concurrency,
            "vpn_rotate_batches": vpn_rotate_batches,
            "auto_analyse": auto_analyse,
            "auto_notion_push": auto_notion_push,
            "site_id": site_id,
            "request_delay_sec": float(request_delay_sec),
            "page_delay_sec": float(page_delay_sec),
            "timeout_sec": timeout_sec,
            "enabled": edit_data.get("enabled", True) if editing else True,
        }
        try:
            if editing:
                api.put(f"/configs/{edit_data['id']}", json=payload)
                st.success("Config updated!")
            else:
                api.post("/configs", json=payload)
                st.success("Config saved!")
            st.rerun()
        except Exception as e:
            st.error(str(e))

if "editing_id" not in st.session_state:
    st.session_state.editing_id = None
if "edit_data" not in st.session_state:
    st.session_state.edit_data = {}

try:
    configs = api.get("/configs")
    site_ids = api.get("/configs/sites")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

if configs:
    for cfg in configs:
        days = cfg.get("schedule_days", [])
        schedule_str = f"{', '.join(d.capitalize() for d in days)} at {cfg.get('schedule_time', '')}"
        with st.container(border=True):
            col1, col2, col3 = st.columns([4, 2, 3])
            with col1:
                status_dot = "🟢" if cfg["enabled"] else "⚫"
                site_badge = cfg.get("site_id") or "immobiliare"
                st.markdown(f"{status_dot} **{cfg['name']}** · `{site_badge}`")
                area_part = f"/{cfg['area']}" if cfg.get("area") else ""
                st.caption(
                    f"{cfg.get('operation', '')} · {cfg.get('city', '')}{area_part} · "
                    f"{cfg.get('min_price', '')}–{cfg.get('max_price', '')} € · {schedule_str}"
                )
                if cfg.get("auto_analyse"):
                    st.caption("AI")
                if cfg.get("auto_notion_push"):
                    st.caption("Notion")
            with col2:
                if st.button("▶ Run", key=f"run_{cfg['id']}", use_container_width=True):
                    try:
                        api.post(f"/configs/{cfg['id']}/run")
                        st.success("Job started!")
                        st.switch_page("pages/2_Monitor.py")
                    except Exception as e:
                        st.error(str(e))
                label = "Enable" if not cfg["enabled"] else "Disable"
                if st.button(label, key=f"tog_{cfg['id']}", use_container_width=True):
                    try:
                        api.patch(f"/configs/{cfg['id']}/toggle")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
            with col3:
                if st.button("✏ Edit", key=f"edit_{cfg['id']}", use_container_width=True):
                    config_dialog(cfg)
                if st.button("🗑 Delete", key=f"del_{cfg['id']}", use_container_width=True):
                    try:
                        api.delete(f"/configs/{cfg['id']}")
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
else:
    st.info("No search configs yet. Create one below.")

st.divider()

if st.button("➕ Create New Config", type="primary", use_container_width=True):
    config_dialog()
