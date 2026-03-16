"""frontend.app — Streamlit multi-page app entry point."""
import streamlit as st

st.set_page_config(
    page_title="apt_scrape",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Hero
st.markdown("# 🏠 apt_scrape")
st.markdown(
    "**Run and monitor apartment scrapes** from Immobiliare, Casa.it, and Idealista — one place for search configs, jobs, and listings."
)
st.markdown("---")

# Navigation: cards with bordered containers
st.subheader("Go to")
col1, col2, col3 = st.columns(3)

with col1:
    with st.container(border=True):
        st.page_link("pages/1_Search_Configs.py", label="Search Configurations", icon="⚙️")
        st.caption("Create and edit search configs, set schedules and rate limits, run jobs.")
with col2:
    with st.container(border=True):
        st.page_link("pages/2_Monitor.py", label="Job Monitor", icon="📡")
        st.caption("Watch running jobs and recent run history.")
    with st.container(border=True):
        st.page_link("pages/4_Listings.py", label="Listings", icon="📋")
        st.caption("Browse scraped listings and AI analysis.")
with col3:
    with st.container(border=True):
        st.page_link("pages/5_Site_Settings.py", label="Site Settings", icon="🔧")
        st.caption("Override areas and selectors per site.")
    with st.container(border=True):
        st.page_link("pages/3_Preferences.py", label="Preferences", icon="📌")
        st.caption("Global preferences and paths.")

st.markdown("---")
st.caption("Use the sidebar to switch pages anytime.")
