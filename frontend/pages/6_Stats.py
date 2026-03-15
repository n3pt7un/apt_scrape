"""Streamlit page: Statistics dashboard."""
import streamlit as st
import pandas as pd
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import api

st.set_page_config(page_title="Statistics", page_icon="📊", layout="wide")
st.title("📊 Statistics")

# ── Overall stats ─────────────────────────────────────────────────────────────
try:
    overall = api.get("/jobs/stats/overall")
except Exception as e:
    st.error(f"Cannot reach backend: {e}")
    st.stop()

st.subheader("Overall")
c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total runs", overall.get("total_runs", 0))
c2.metric("Total listings", overall.get("total_listings", 0))
total_scraped = overall.get("total_scraped") or 0
total_dupes = overall.get("total_dupes_removed") or 0
dedup_pct = round(total_dupes / total_scraped * 100, 1) if total_scraped else 0
c3.metric("Dupes removed", f"{total_dupes} ({dedup_pct}%)")
avg_price = overall.get("avg_price_eur")
c4.metric("Avg price", f"€{avg_price:,.0f}" if avg_price else "—")
c5.metric("AI tokens", f"{overall.get('total_ai_tokens', 0):,}")
cost = overall.get("total_ai_cost_usd") or 0
c6.metric("AI cost", f"${cost:.4f}")

# Area distribution (overall)
area_dist = overall.get("area_distribution") or {}
if area_dist:
    st.subheader("Listings by area (all time)")
    area_df = pd.DataFrame(
        sorted(area_dist.items(), key=lambda x: -x[1]),
        columns=["Area", "Count"],
    ).set_index("Area")
    st.bar_chart(area_df)

st.divider()

# ── Per-run stats ─────────────────────────────────────────────────────────────
st.subheader("Per-run breakdown")

try:
    jobs = api.get("/jobs")
except Exception as e:
    st.error(f"Cannot load jobs: {e}")
    st.stop()

done_jobs = [j for j in jobs if j.get("status") == "done"]
if not done_jobs:
    st.info("No completed runs yet.")
    st.stop()

# Build config name map
try:
    configs_list = api.get("/configs")
    config_names = {c["id"]: c["name"] for c in configs_list}
except Exception:
    configs_list = []
    config_names = {}

# ── Config filter ─────────────────────────────────────────────────────────────
config_options = {"All configs": None}
for c in configs_list:
    config_options[c["name"]] = c["id"]
selected_label = st.selectbox("Filter by config", list(config_options.keys()))
selected_config_id = config_options[selected_label]

if selected_config_id is not None:
    done_jobs = [j for j in done_jobs if j.get("config_id") == selected_config_id]

def _fmt_dur(sec):
    if not sec:
        return ""
    sec = int(sec)
    return f"{sec // 60}m {sec % 60}s" if sec >= 60 else f"{sec}s"


# Fetch per-job stats
rows = []
for job in done_jobs:
    try:
        s = api.get(f"/jobs/{job['id']}/stats")
    except Exception:
        s = {}

    area_stats = s.get("area_stats") or {}
    area_summary = ", ".join(f"{a or 'city'}: {n}" for a, n in sorted(area_stats.items(), key=lambda x: -x[1])) if area_stats else "—"

    rows.append({
        "Job": f"#{job['id']}",
        "Config": config_names.get(job.get("config_id"), str(job.get("config_id", ""))),
        "Started": str(job.get("started_at", ""))[:16],
        "Duration": _fmt_dur(s.get("duration_sec")),
        "Scraped": s.get("scraped_count") or job.get("listing_count") or 0,
        "Unique": s.get("listing_count") or job.get("listing_count") or 0,
        "Dupes": s.get("dupes_removed") or 0,
        "Avg price": f"€{s['avg_price_eur']:,.0f}" if s.get("avg_price_eur") else "—",
        "AI tokens": s.get("ai_tokens_used") or 0,
        "AI cost": f"${s['ai_cost_usd']:.4f}" if s.get("ai_cost_usd") else "—",
        "By area": area_summary,
    })

if rows:
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)

    # Chart: listings found per run
    st.subheader("Unique listings per run")
    chart_df = pd.DataFrame({
        "Run": [r["Job"] for r in rows],
        "Unique": [r["Unique"] for r in rows],
        "Scraped": [r["Scraped"] for r in rows],
    }).set_index("Run")
    st.bar_chart(chart_df)

    # Chart: area breakdown for the most recent run with area data
    for r, job in zip(rows, done_jobs):
        try:
            s = api.get(f"/jobs/{job['id']}/stats")
            area_stats = s.get("area_stats") or {}
            if len(area_stats) > 1:
                st.subheader(f"Area breakdown — Job #{job['id']} ({r['Started']})")
                area_chart_df = pd.DataFrame(
                    sorted(area_stats.items(), key=lambda x: -x[1]),
                    columns=["Area", "Listings"],
                ).set_index("Area")
                st.bar_chart(area_chart_df)
                break
        except Exception:
            continue
else:
    st.info("No run data available.")
