"""frontend.app — Streamlit multi-page app entry point."""
import streamlit as st

st.set_page_config(
    page_title="apt_scrape",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🏠 apt_scrape")
st.write("Use the sidebar to navigate between pages.")
