"""Streamlit page: LLM Evaluation Preferences."""
import streamlit as st
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Preferences", page_icon="🧠", layout="wide")
st.title("🧠 LLM Evaluation Preferences")
st.caption("This text is passed to the AI to score listings 0–100. Changes take effect on the next job run.")

try:
    prefs_data = api.get("/preferences")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

content = prefs_data.get("content", "")
last_saved = prefs_data.get("last_saved")

if last_saved:
    st.caption(f"Last saved: {last_saved} UTC")

new_content = st.text_area(
    "Preferences",
    value=content,
    height=400,
    label_visibility="collapsed",
    help="Describe must-haves, nice-to-haves, and deal-breakers.",
)

if st.button("💾 Save Preferences", type="primary"):
    try:
        api.put("/preferences", json={"content": new_content})
        st.success("Preferences saved! They will be used on the next scrape run.")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to save: {e}")
