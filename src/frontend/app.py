"""frontend.app — Streamlit multi-page app entry point. Redirects to Operations."""
import streamlit as st
import os
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="apt_scrape",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Redirect to Operations (the real landing page)
st.switch_page("pages/1_Operations.py")
