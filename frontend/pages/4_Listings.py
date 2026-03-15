"""Streamlit page: Listings browser."""
import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Listings", page_icon="🏠", layout="wide")
st.title("🏠 Listings")

# ── Sidebar filters ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Filters")
    try:
        configs = api.get("/configs")
    except Exception:
        configs = []

    config_options = {"All configs": None}
    for c in configs:
        config_options[c["name"]] = c["id"]

    selected_config_label = st.selectbox("Config", list(config_options.keys()))
    selected_config_id = config_options[selected_config_label]

    score_filter = st.checkbox("Only scored listings", value=False)
    min_score = st.slider("Min AI score", 0, 100, 0, disabled=not score_filter)

    search_text = st.text_input("Search title / area / city", placeholder="e.g. bicocca")

    st.divider()
    limit = st.select_slider("Max rows", options=[50, 100, 200, 500], value=200)

# ── Fetch listings ────────────────────────────────────────────────────────────
params: dict = {"limit": limit}
if selected_config_id is not None:
    params["config_id"] = selected_config_id
if score_filter and min_score > 0:
    params["min_score"] = min_score
if search_text.strip():
    params["search"] = search_text.strip()

try:
    listings = api.get("/listings", params=params)
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

if not listings:
    st.info("No listings found. Run a search config job first, or adjust your filters.")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
scored = [l for l in listings if l.get("ai_score") is not None]
avg_score = round(sum(l["ai_score"] for l in scored) / len(scored), 1) if scored else None

m1, m2, m3 = st.columns(3)
m1.metric("Total listings", len(listings))
m2.metric("AI scored", len(scored))
m3.metric("Avg AI score", avg_score if avg_score is not None else "—")

st.divider()

# ── Build dataframe ───────────────────────────────────────────────────────────
def score_label(score):
    if score is None:
        return ""
    if score >= 80:
        return f"{score} ●●●"
    if score >= 60:
        return f"{score} ●●"
    if score >= 40:
        return f"{score} ●"
    return f"{score}"

rows = []
for l in listings:
    rows.append({
        "ID": l["id"],
        "Title": l.get("title", "")[:60],
        "Price": l.get("price", ""),
        "sqm": l.get("sqm", ""),
        "Rooms": l.get("rooms", ""),
        "Area": l.get("area", ""),
        "City": l.get("city", ""),
        "Score": l.get("ai_score"),
        "Config": l.get("config_name", ""),
        "Scraped": str(l.get("scraped_at", ""))[:10],
        "URL": l.get("url", ""),
    })

df = pd.DataFrame(rows)

event = st.dataframe(
    df,
    column_config={
        "ID": st.column_config.NumberColumn("ID", width="small"),
        "Score": st.column_config.NumberColumn("Score", format="%d", width="small"),
        "URL": st.column_config.LinkColumn("Link", width="small"),
    },
    use_container_width=True,
    hide_index=True,
    selection_mode="multi-row",
    on_select="rerun",
)

# ── Selection actions ─────────────────────────────────────────────────────────
selected_rows = event.selection.rows if hasattr(event, "selection") else []

if len(selected_rows) > 1:
    selected_ids = [listings[i]["id"] for i in selected_rows]
    if st.button(f"Push {len(selected_ids)} listing(s) to Notion", type="primary", key="bulk_push_notion"):
        try:
            result = api.post("/listings/notion-push", json={"listing_ids": selected_ids})
            st.success(
                f"Notion push complete: {result['pushed']} pushed, "
                f"{result['skipped']} already in Notion."
            )
            if result.get("errors"):
                st.error(f"Errors: {result['errors']}")
            st.rerun()
        except Exception as e:
            st.error(f"Push failed: {e}")

# ── Selected listing detail (only when exactly one row selected) ──────────────
if len(selected_rows) == 1:
    idx = selected_rows[0]
    listing = listings[idx]

    st.subheader("Listing Detail")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"**{listing.get('title', '')}**")
        st.write(f"**Price:** {listing.get('price', '—')}")
        st.write(f"**Area:** {listing.get('sqm', '—')} sqm · {listing.get('rooms', '—')} rooms")
        st.write(f"**Location:** {listing.get('area', '—')}, {listing.get('city', '—')}")
        st.write(f"**Config:** {listing.get('config_name', '—')}")
        st.write(f"**Scraped:** {str(listing.get('scraped_at', ''))[:19]}")
        st.link_button("Open listing", listing.get("url", "#"))
    with d2:
        score = listing.get("ai_score")
        if score is not None:
            color = "green" if score >= 70 else ("orange" if score >= 40 else "red")
            st.markdown(f"**AI Score:** :{color}[{score}/100]")
        else:
            st.write("**AI Score:** not scored")
        verdict = listing.get("ai_verdict")
        if verdict:
            st.markdown("**AI Verdict:**")
            st.write(verdict)
        if listing.get("notion_page_id"):
            st.write(f"**Notion:** {listing['notion_page_id']}")
            st.button("Already in Notion", disabled=True, key=f"already_notion_{listing['id']}")
        else:
            if st.button("Push this listing to Notion", key=f"push_single_{listing['id']}"):
                try:
                    result = api.post(
                        "/listings/notion-push",
                        json={"listing_ids": [listing["id"]]},
                    )
                    st.success(
                        f"Done: {result['pushed']} pushed, {result['skipped']} skipped."
                    )
                    if result.get("errors"):
                        st.error(f"Errors: {result['errors']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Push failed: {e}")
