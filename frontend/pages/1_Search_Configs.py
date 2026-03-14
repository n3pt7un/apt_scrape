"""Streamlit page: Search Configurations."""
import datetime
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Search Configs", page_icon="⚙️", layout="wide")
st.title("⚙️ Search Configurations")

# ── Session state init ────────────────────────────────────────────────────────
if "editing_id" not in st.session_state:
    st.session_state.editing_id = None
if "edit_data" not in st.session_state:
    st.session_state.edit_data = {}

# ── Load configs ──────────────────────────────────────────────────────────────
try:
    configs = api.get("/configs")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

# ── Config cards ──────────────────────────────────────────────────────────────
if configs:
    for cfg in configs:
        days = cfg.get("schedule_days", [])
        schedule_str = f"{', '.join(d.capitalize() for d in days)} at {cfg.get('schedule_time', '')}"
        is_editing = st.session_state.editing_id == cfg["id"]

        with st.container(border=True):
            col1, col2, col3 = st.columns([4, 2, 3])
            with col1:
                status_dot = "🟢" if cfg["enabled"] else "⚫"
                st.markdown(f"{status_dot} **{cfg['name']}**")
                area_part = f"/{cfg['area']}" if cfg.get("area") else ""
                st.caption(
                    f"{cfg.get('operation', '')} · "
                    f"{cfg.get('city', '')}{area_part} · "
                    f"{cfg.get('min_price', '')}–{cfg.get('max_price', '')} € · "
                    f"{schedule_str}"
                )
                badges = []
                if cfg.get("auto_analyse"):
                    badges.append("AI")
                if cfg.get("auto_notion_push"):
                    badges.append("Notion")
                if badges:
                    st.caption(" · ".join(badges))
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
                edit_label = "Cancel Edit" if is_editing else "✏ Edit"
                if st.button(edit_label, key=f"edit_{cfg['id']}", use_container_width=True):
                    if is_editing:
                        st.session_state.editing_id = None
                        st.session_state.edit_data = {}
                    else:
                        st.session_state.editing_id = cfg["id"]
                        st.session_state.edit_data = cfg
                        # Pre-populate form session state keys
                        h, m = (cfg.get("schedule_time") or "08:00").split(":")
                        st.session_state["ef_name"] = cfg.get("name", "")
                        st.session_state["ef_city"] = cfg.get("city", "")
                        st.session_state["ef_area"] = cfg.get("area") or ""
                        st.session_state["ef_operation"] = cfg.get("operation", "affitto")
                        st.session_state["ef_property_type"] = cfg.get("property_type", "appartamenti")
                        st.session_state["ef_price"] = (cfg.get("min_price") or 0, cfg.get("max_price") or 2000)
                        st.session_state["ef_min_sqm"] = cfg.get("min_sqm") or 0
                        st.session_state["ef_min_rooms"] = cfg.get("min_rooms") or 1
                        st.session_state["ef_start_page"] = cfg.get("start_page") or 1
                        st.session_state["ef_end_page"] = cfg.get("end_page") or 10
                        st.session_state["ef_days"] = cfg.get("schedule_days") or []
                        st.session_state["ef_time"] = datetime.time(int(h), int(m))
                        st.session_state["ef_concurrency"] = cfg.get("detail_concurrency") or 5
                        st.session_state["ef_vpn"] = cfg.get("vpn_rotate_batches") or 3
                        st.session_state["ef_analyse"] = cfg.get("auto_analyse", True)
                        st.session_state["ef_notion"] = cfg.get("auto_notion_push", False)
                    st.rerun()
                if st.button("🗑 Delete", key=f"del_{cfg['id']}", use_container_width=True):
                    try:
                        api.delete(f"/configs/{cfg['id']}")
                        if st.session_state.editing_id == cfg["id"]:
                            st.session_state.editing_id = None
                            st.session_state.edit_data = {}
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
else:
    st.info("No search configs yet. Create one below.")

st.divider()

# ── Presets for Cities and Areas ────────────────────────────────────────────────
PRESET_CITIES = ["milano"]
PRESET_AREAS = [
    "",
    "bicocca",
    "centrale",
    "citta-studi",
    "crescenzago",
    "greco-segnano",
    "lambrate",
    "loreto",
    "niguarda",
    "pasteur-rovereto",
    "precotto",
    "turro",
]

# ── Create / Edit form ────────────────────────────────────────────────────────
editing = st.session_state.editing_id is not None
edit_data = st.session_state.edit_data

if editing:
    st.subheader(f"Edit Config: {edit_data.get('name', '')}")
else:
    st.subheader("New Search Config")

# Use different keys based on mode so values don't bleed between create/edit
key_suffix = "ef" if editing else "nf"
defaults = edit_data if editing else {}

with st.form("config_form"):
    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Config name", key=f"{key_suffix}_name",
                             placeholder="Milano · Bicocca")
        
        # Ensure current selections are in the preset lists
        current_city = st.session_state.get(f"{key_suffix}_city", "milano")
        city_options = PRESET_CITIES if current_city in PRESET_CITIES else PRESET_CITIES + [current_city]
        city = st.selectbox("City slug", city_options, key=f"{key_suffix}_city")
        
        current_area = st.session_state.get(f"{key_suffix}_area", "")
        area_options = PRESET_AREAS if current_area in PRESET_AREAS else PRESET_AREAS + [current_area]
        area = st.selectbox("Area slug (optional)", area_options, key=f"{key_suffix}_area")
        
        operation = st.selectbox("Operation", ["affitto", "vendita"],
                                 key=f"{key_suffix}_operation")
        property_type = st.text_input("Property types (comma-separated)",
                                      key=f"{key_suffix}_property_type",
                                      value="appartamenti,attici" if not editing else None)
    with c2:
        price_default = (defaults.get("min_price") or 0, defaults.get("max_price") or 2000) if editing else (700, 1200)
        min_price, max_price = st.slider(
            "Price range (€)", 0, 5000,
            value=st.session_state.get(f"{key_suffix}_price", price_default),
            step=50, key=f"{key_suffix}_price",
        )
        min_sqm = st.number_input("Min sqm", min_value=0, step=5, key=f"{key_suffix}_min_sqm",
                                  value=None if not editing else None)
        min_rooms = st.selectbox("Min rooms", [1, 2, 3, 4, 5],
                                 key=f"{key_suffix}_min_rooms")
        start_page = st.number_input("Start page", min_value=1, key=f"{key_suffix}_start_page",
                                     value=None if not editing else None)
        end_page = st.number_input("End page", min_value=1, key=f"{key_suffix}_end_page",
                                   value=None if not editing else None)

    st.markdown("**Schedule**")
    sc1, sc2 = st.columns(2)
    with sc1:
        schedule_days = st.multiselect(
            "Days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            key=f"{key_suffix}_days",
            default=[] if not editing else None,
        )
    with sc2:
        schedule_time = st.time_input("Time (UTC)", key=f"{key_suffix}_time",
                                      value=None if not editing else None)

    st.markdown("**Rate limits & toggles**")
    rl1, rl2, rl3, rl4 = st.columns(4)
    with rl1:
        detail_concurrency = st.slider("Detail concurrency", 1, 10,
                                       key=f"{key_suffix}_concurrency",
                                       value=5 if not editing else None)
    with rl2:
        vpn_rotate_batches = st.slider("VPN rotate batches", 1, 10,
                                       key=f"{key_suffix}_vpn",
                                       value=3 if not editing else None)
    with rl3:
        auto_analyse = st.toggle("AI analysis", key=f"{key_suffix}_analyse",
                                 value=True if not editing else None)
    with rl4:
        auto_notion_push = st.toggle("Notion auto-push", key=f"{key_suffix}_notion",
                                     value=False if not editing else None)

    col_submit, col_cancel = st.columns([1, 4])
    with col_submit:
        btn_label = "Update Config" if editing else "Save Config"
        submitted = st.form_submit_button(btn_label, type="primary")

    if submitted:
        time_str = schedule_time.strftime("%H:%M") if schedule_time else "08:00"
        payload = {
            "name": name,
            "city": city,
            "area": area or None,
            "operation": operation,
            "property_type": property_type,
            "min_price": min_price,
            "max_price": max_price,
            "min_sqm": int(min_sqm) if min_sqm else None,
            "min_rooms": min_rooms,
            "start_page": int(start_page) if start_page else 1,
            "end_page": int(end_page) if end_page else 10,
            "schedule_days": schedule_days,
            "schedule_time": time_str,
            "detail_concurrency": detail_concurrency,
            "vpn_rotate_batches": vpn_rotate_batches,
            "auto_analyse": auto_analyse,
            "auto_notion_push": auto_notion_push,
            "enabled": edit_data.get("enabled", True) if editing else True,
        }
        try:
            if editing:
                api.put(f"/configs/{st.session_state.editing_id}", json=payload)
                st.session_state.editing_id = None
                st.session_state.edit_data = {}
                st.success("Config updated!")
            else:
                api.post("/configs", json=payload)
                st.success("Config saved!")
            st.rerun()
        except Exception as e:
            st.error(str(e))
