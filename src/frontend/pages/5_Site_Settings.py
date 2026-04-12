"""Streamlit page: Per-site config overrides. View areas, edit overrides as YAML."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import streamlit as st
import api

try:
    import yaml
except ImportError:
    yaml = None

import theme

st.set_page_config(page_title="Site Settings", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Site Settings")
st.caption("View current areas and full config. Edit overrides as YAML and save, or save a copy as a test variant.")

try:
    sites_list = api.get("/sites")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

if not sites_list:
    st.info("No sites registered.")
    st.stop()

selected_site = st.selectbox("Site", sites_list, key="site_settings_site", help="Base sites + any saved variants (e.g. immobiliare-test1).")

try:
    split = api.get(f"/sites/{selected_site}/config", params={"split": True})
    base = split.get("base")
    overrides = split.get("overrides")
    effective = split.get("effective")
    if effective is None and "site_id" in split:
        base, overrides, effective = {}, {}, split
    elif base is None or effective is None:
        st.error("Backend did not return split config. Check backend version.")
        st.stop()
except Exception as e:
    st.error(f"Failed to load config: {e}")
    st.stop()

# ---- Current areas (always visible) ----
try:
    current_areas = api.get(f"/sites/{selected_site}/areas")
except Exception:
    current_areas = effective.get("areas") or list(api.DEFAULT_AREAS)

st.subheader("Current areas")
if current_areas:
    st.markdown("**In use for this site** (from overrides, site YAML, or `config/default_areas.txt`):")
    st.code(" ".join(current_areas), language=None)
    st.caption("These appear in the Search Configs area dropdown. Default set matches the shell scripts.")
else:
    st.info("No areas defined. Add an `areas` list in the overrides YAML below, or ensure config/default_areas.txt exists.")

base_for_default = selected_site.split("-")[0] if "-" in selected_site else selected_site
default_areas_for_site = api.DEFAULT_AREAS_BY_SITE.get(base_for_default, api.DEFAULT_AREAS)
st.markdown(f"**Default areas for {base_for_default}** (when no overrides):")
st.caption("From config/default_areas_<site>.txt or default_areas.txt — keep in sync with scrape_multiple_areas*.sh")
st.code(" ".join(default_areas_for_site), language=None)

st.divider()
st.subheader("Edit areas (add or remove)")
st.caption("One area per line. Add a new line for a new area; these are used in the Search Configs dropdown. Save below to apply.")
areas_edit = st.text_area(
    "Areas (one per line)",
    value="\n".join(current_areas) if current_areas else "",
    height=160,
    key="site_areas_edit",
    label_visibility="collapsed",
)
# Parse to list (strip, skip empty)
areas_list_edited = [a.strip() for a in (areas_edit or "").split("\n") if a.strip()]

st.divider()
st.subheader("Config (read-only)")

with st.expander("Base (built-in)", expanded=False):
    st.caption("From YAML + adapter. Not editable here.")
    if yaml:
        st.code(yaml.dump(base, default_flow_style=False, allow_unicode=True, sort_keys=False), language="yaml")
    else:
        st.json(base)

with st.expander("Effective (merged)", expanded=False):
    st.caption("What the runner uses (base + overrides).")
    if yaml:
        st.code(yaml.dump(effective, default_flow_style=False, allow_unicode=True, sort_keys=False), language="yaml")
    else:
        st.json(effective)

st.divider()
st.subheader("Rate limit (per site)")
rpm = overrides.get("requests_per_minute") or effective.get("requests_per_minute")
_rpm_val = int(rpm) if rpm is not None else 0
requests_per_minute = st.number_input(
    "Max requests per minute (0 = no limit)",
    min_value=0,
    max_value=120,
    value=_rpm_val,
    step=1,
    help="Cap search requests for this site (e.g. immobiliare: 15). Runner uses max(config delay, 60/this).",
    key="site_rpm",
)
if requests_per_minute > 0:
    st.caption(f"→ minimum {60.0 / requests_per_minute:.1f}s between search requests")

st.divider()
st.subheader("Edit overrides (YAML)")

if not yaml:
    st.warning("Install PyYAML (`pip install pyyaml`) to use the YAML editor. Using JSON fallback.")
    import json
    overrides_editor_default = json.dumps(overrides if overrides else {}, indent=2)
else:
    overrides_editor_default = yaml.dump(overrides if overrides else {}, default_flow_style=False, allow_unicode=True, sort_keys=False)

overrides_yaml = st.text_area(
    "Overrides (YAML)",
    value=overrides_editor_default,
    height=280,
    help="Only keys you set here override the base. Example: areas, search_wait_selector, detail_wait_selector, requests_per_minute, search_selectors, etc.",
    key="site_overrides_yaml",
)

def _parse_overrides(text: str):
    """Return (dict or None, error_message or None)."""
    if not (text or "").strip():
        return {}, None
    if yaml:
        try:
            out = yaml.safe_load(text)
            return (out if isinstance(out, dict) else {}), None
        except yaml.YAMLError as e:
            return None, str(e)
    try:
        import json
        out = json.loads(text)
        return (out if isinstance(out, dict) else {}), None
    except json.JSONDecodeError as e:
        return None, str(e)

parsed, parse_err = _parse_overrides(overrides_yaml)
if parse_err:
    st.error(f"Invalid YAML: {parse_err}")
if parsed is None:
    parsed = {}

# Merge rate limit and areas from the dedicated inputs into payload
payload_for_save = dict(parsed)
if requests_per_minute > 0:
    payload_for_save["requests_per_minute"] = requests_per_minute
else:
    payload_for_save.pop("requests_per_minute", None)
# Areas from "Edit areas" text area (so you can add new areas without touching YAML)
if areas_list_edited:
    payload_for_save["areas"] = areas_list_edited
elif "areas" in payload_for_save:
    # Keep existing if user cleared the text area (empty = use defaults, so remove override)
    payload_for_save.pop("areas", None)

col_save, col_variant, _ = st.columns([1, 1, 2])
with col_save:
    if st.button("💾 Save overrides", type="primary"):
        if parse_err or parsed is None:
            st.error("Fix YAML syntax first.")
        else:
            try:
                api.put(f"/sites/{selected_site}/config", json=payload_for_save)
                st.success("Overrides saved. They apply to the next job run.")
                st.rerun()
            except Exception as e:
                st.error(str(e))

with col_variant:
    variant_name = st.text_input("Variant name (e.g. test1)", value="", placeholder="test1", key="variant_name")
    if st.button("📋 Save as test variant"):
        name = (variant_name or "").strip().replace(" ", "-")
        if not name:
            st.error("Enter a variant name (e.g. test1).")
        elif parse_err or parsed is None:
            st.error("Fix YAML syntax first.")
        else:
            base_name = selected_site.split("-")[0] if "-" in selected_site else selected_site
            if base_name not in ["immobiliare", "casa", "idealista"]:
                base_name = "immobiliare"
            new_site_id = f"{base_name}-{name}"
            try:
                api.put(f"/sites/{new_site_id}/config", json=payload_for_save)
                st.success(f"Saved as **{new_site_id}**. It will appear in the Site dropdown.")
                st.rerun()
            except Exception as e:
                st.error(str(e))
