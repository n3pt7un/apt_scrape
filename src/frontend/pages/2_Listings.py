"""Streamlit page: Listings browser — redesigned with horizontal filters and inline detail."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import streamlit as st
import pandas as pd

import api
import theme

st.set_page_config(page_title="Listings", page_icon="⚡", layout="wide")
theme.apply_theme()
st.title("Listings")

# ── Config & area lookups ────────────────────────────────────────────────────
try:
    configs = api.get("/configs")
except Exception:
    configs = []

config_options = {"All": None}
for c in configs:
    config_options[c["name"]] = c["id"]

# Collect known areas from configs
all_areas = set()
for c in configs:
    area = c.get("area") or ""
    for a in area.split(","):
        a = a.strip()
        if a:
            all_areas.add(a)

# ── Horizontal filter bar ────────────────────────────────────────────────────
f1, f2, f3, f4, f5, f6 = st.columns([2, 1, 1, 2, 1, 2])

with f1:
    selected_configs = st.multiselect("Config", list(config_options.keys())[1:], default=[], key="lst_configs")
with f2:
    score_min, score_max = st.slider("AI Score", 0, 100, (0, 100), key="lst_score")
with f3:
    price_min = st.number_input("Min €", min_value=0, value=0, step=100, key="lst_price_min")
with f4:
    price_max = st.number_input("Max €", min_value=0, value=0, step=100, key="lst_price_max",
                                 help="0 = no limit")
with f5:
    date_preset = st.selectbox("Period", ["7 days", "30 days", "All time"], index=0, key="lst_date")
with f6:
    search_text = st.text_input("Search title / area", placeholder="e.g. bicocca", key="lst_search")

# ── Build API params ─────────────────────────────────────────────────────────
params: dict = {"limit": 500}

# Config filter — if multiple selected, we'll filter client-side
selected_config_id = None
if len(selected_configs) == 1:
    selected_config_id = config_options.get(selected_configs[0])
    if selected_config_id is not None:
        params["config_id"] = selected_config_id

if score_min > 0:
    params["min_score"] = score_min
if score_max < 100:
    params["max_score"] = score_max
if search_text.strip():
    params["search"] = search_text.strip()

# Date filter
days_map = {"7 days": 7, "30 days": 30, "All time": None}
days = days_map.get(date_preset)
if days:
    params["days"] = days

try:
    listings = api.get("/listings", params=params)
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

# Client-side multi-config filter
if len(selected_configs) > 1:
    selected_ids = {config_options[name] for name in selected_configs if config_options.get(name)}
    listings = [l for l in listings if l.get("config_id") in selected_ids]

# Client-side price filter
if price_min > 0 or price_max > 0:
    import re as _re
    def _in_price_range(lst):
        price_str = lst.get("price", "")
        cleaned = price_str.replace(".", "").replace(",", ".")
        m = _re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if not m:
            return True  # keep items we can't parse
        val = float(m.group(1))
        if price_min > 0 and val < price_min:
            return False
        if price_max > 0 and val > price_max:
            return False
        return True
    listings = [l for l in listings if _in_price_range(l)]

if not listings:
    st.info("No listings found. Run a search config job first, or adjust your filters.")
    st.stop()

# ── Summary metrics ──────────────────────────────────────────────────────────
scored = [l for l in listings if l.get("ai_score") is not None]
avg_score = round(sum(l["ai_score"] for l in scored) / len(scored), 1) if scored else None
prices_per_sqm = [l["price_per_sqm"] for l in listings if l.get("price_per_sqm")]
avg_pps = round(sum(prices_per_sqm) / len(prices_per_sqm), 1) if prices_per_sqm else None

m1, m2, m3, m4 = st.columns(4)
m1.metric("Listings", len(listings))
m2.metric("AI Scored", len(scored))
m3.metric("Avg Score", avg_score if avg_score is not None else "—")
m4.metric("Avg €/sqm", f"€{avg_pps:.0f}" if avg_pps else "—")

st.markdown("---")

# ── Build table ──────────────────────────────────────────────────────────────
def _relative_time(dt_str):
    if not dt_str:
        return ""
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(str(dt_str))
        now = datetime.utcnow()
        diff = (now - dt).total_seconds()
        if diff < 3600:
            return f"{int(diff // 60)}m ago"
        if diff < 86400:
            return f"{int(diff // 3600)}h ago"
        return f"{int(diff // 86400)}d ago"
    except Exception:
        return str(dt_str)[:10]


# Sort by AI score descending (best first)
listings_sorted = sorted(listings, key=lambda l: l.get("ai_score") or -1, reverse=True)

rows = []
for l in listings_sorted:
    rows.append({
        "Title": (l.get("title") or "")[:55],
        "€/mo": l.get("price", ""),
        "€/sqm": f'{l["price_per_sqm"]:.0f}' if l.get("price_per_sqm") else "—",
        "sqm": l.get("sqm", ""),
        "Rooms": l.get("rooms", ""),
        "Area": l.get("area", ""),
        "Score": l.get("ai_score"),
        "Scraped": _relative_time(l.get("scraped_at")),
        "Notion": "✓" if l.get("notion_page_id") else "—",
    })

df = pd.DataFrame(rows)

event = st.dataframe(
    df,
    column_config={
        "Score": st.column_config.NumberColumn("Score", format="%d", width="small"),
        "€/sqm": st.column_config.TextColumn("€/sqm", width="small"),
        "Rooms": st.column_config.TextColumn("Rooms", width="small"),
        "Notion": st.column_config.TextColumn("Notion", width="small"),
    },
    use_container_width=True,
    hide_index=True,
    selection_mode="multi-row",
    on_select="rerun",
)

# ── Selection actions ────────────────────────────────────────────────────────
selected_rows = event.selection.rows if hasattr(event, "selection") else []

if len(selected_rows) > 1:
    selected_ids = [listings_sorted[i]["id"] for i in selected_rows]
    if st.button(f"Push {len(selected_ids)} listing(s) to Notion", type="primary", key="bulk_push"):
        try:
            result = api.post("/listings/notion-push", json={"listing_ids": selected_ids})
            st.success(f"Pushed {result['pushed']}, skipped {result['skipped']}.")
            if result.get("errors"):
                st.error(f"Errors: {result['errors']}")
            st.rerun()
        except Exception as e:
            st.error(f"Push failed: {e}")

# ── Inline detail panel ──────────────────────────────────────────────────────
if len(selected_rows) == 1:
    listing = listings_sorted[selected_rows[0]]

    st.markdown("---")
    d1, d2 = st.columns(2)
    with d1:
        st.markdown(f"### {listing.get('title', '')}")
        st.markdown(
            f"**Price:** {listing.get('price', '—')}  \n"
            f"**€/sqm:** {listing.get('price_per_sqm', '—')}  \n"
            f"**Size:** {listing.get('sqm', '—')} sqm · {listing.get('rooms', '—')} rooms  \n"
            f"**Area:** {listing.get('area', '—')}, {listing.get('city', '—')}  \n"
            f"**Config:** {listing.get('config_name', '—')}  \n"
            f"**Scraped:** {str(listing.get('scraped_at', ''))[:19]}"
        )
        st.link_button("Open listing ↗", listing.get("url", "#"))
    with d2:
        score = listing.get("ai_score")
        if score is not None:
            if score >= 70:
                color = theme.GREEN
            elif score >= 40:
                color = theme.AMBER
            else:
                color = theme.RED
            dot = theme.status_dot(color, size=12)
            st.markdown(
                f'{dot} <span style="font-family:{theme.MONO_FONT};font-size:2rem;'
                f'color:{color}">{score}</span>'
                f'<span style="color:{theme.TEXT_MUTED};font-size:1rem">/100</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown("**AI Score:** not scored")

        verdict = listing.get("ai_verdict")
        if verdict:
            st.markdown("**AI Verdict:**")
            st.write(verdict)

        if listing.get("notion_page_id"):
            st.button("Already in Notion", disabled=True, key=f"already_{listing['id']}")
        else:
            if st.button("Push to Notion", key=f"push_{listing['id']}"):
                try:
                    result = api.post("/listings/notion-push", json={"listing_ids": [listing["id"]]})
                    st.success(f"Pushed {result['pushed']}, skipped {result['skipped']}.")
                    if result.get("errors"):
                        st.error(f"Errors: {result['errors']}")
                    st.rerun()
                except Exception as e:
                    st.error(f"Push failed: {e}")
