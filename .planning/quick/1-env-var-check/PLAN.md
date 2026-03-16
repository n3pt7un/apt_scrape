# Plan: Environment Variable Check on Startup

## Objective
Add a check when the Streamlit app starts up to ensure all required environment variables are set and valid. Warn the user if they are missing so they know they cannot run tasks without a complete setup.

## Tasks
1. Identify required environment variables (`OPENROUTER_API_KEY`, `NOTION_API_KEY`, `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID`).
2. Update `src/frontend/app.py` to check for these variables upon startup.
3. If any missing or empty, display a comprehensive `st.warning` detailing what is missing and how to fix it before the rest of the application loads.
