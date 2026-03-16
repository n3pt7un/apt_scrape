# Summary: Environment Variable Check on Startup

## Completed Plan Tasks
- Identified required environment variables (`OPENROUTER_API_KEY`, `NOTION_API_KEY`, `NOTION_APARTMENTS_DB_ID`, `NOTION_AREAS_DB_ID`, `NOTION_AGENCIES_DB_ID`).
- Added a startup check in `src/frontend/app.py` for missing env vars.
- Added a `st.warning` in the app to display a message indicating which env vars are missing so users cannot unintentionally run tasks without everything set up.

## Verification
- Checked `src/frontend/app.py` syntax and logic.
- The `os.environ.get()` properly evaluates the presence of keys and prevents runtime failures later on.
