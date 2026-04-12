"""frontend.theme — Palantir dark theme for the Streamlit dashboard."""

# ── Color palette ────────────────────────────────────────────────────────────
BG_PRIMARY = "#0a0a0a"
BG_CARD = "#111111"
BG_ELEVATED = "#1a1a1a"
BORDER_SUBTLE = "#2a2a2a"
BORDER_EMPHASIS = "#333333"
TEXT_PRIMARY = "#e0e0e0"
TEXT_SECONDARY = "#888888"
TEXT_MUTED = "#555555"

GREEN = "#00d97e"
AMBER = "#f7c948"
RED = "#e63757"
BLUE = "#0061ff"
CYAN = "#00b8d9"

# Mapping for health status strings from /jobs/health
STATUS_COLORS = {
    "healthy": GREEN,
    "stable": GREEN,
    "warning": AMBER,
    "declining": AMBER,
    "rising": AMBER,
    "critical": RED,
    "falling": GREEN,  # dupe rate falling is good
}

# ── Plotly layout template ───────────────────────────────────────────────────
PLOTLY_LAYOUT = dict(
    paper_bgcolor=BG_CARD,
    plot_bgcolor=BG_CARD,
    font=dict(color=TEXT_PRIMARY, family="system-ui, -apple-system, sans-serif"),
    xaxis=dict(gridcolor=BG_ELEVATED, zerolinecolor=BORDER_SUBTLE),
    yaxis=dict(gridcolor=BG_ELEVATED, zerolinecolor=BORDER_SUBTLE),
    legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=TEXT_SECONDARY)),
    margin=dict(l=40, r=20, t=40, b=40),
)

MONO_FONT = "'JetBrains Mono', 'SF Mono', 'Fira Code', 'Consolas', monospace"

# ── CSS ──────────────────────────────────────────────────────────────────────
_CSS = f"""
<style>
/* === Base === */
.stApp, .stApp > header {{
    background-color: {BG_PRIMARY} !important;
    color: {TEXT_PRIMARY} !important;
}}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background-color: #0d0d0d !important;
    border-right: 1px solid {BORDER_SUBTLE} !important;
}}
section[data-testid="stSidebar"] .stMarkdown p,
section[data-testid="stSidebar"] .stMarkdown span,
section[data-testid="stSidebar"] label {{
    color: {TEXT_SECONDARY} !important;
}}

/* Active sidebar nav link */
section[data-testid="stSidebar"] a[aria-current="page"] {{
    border-left: 3px solid {BLUE} !important;
    color: #ffffff !important;
    font-weight: 600 !important;
}}

/* Headers */
.stApp h1, .stApp h2, .stApp h3 {{
    color: {TEXT_PRIMARY} !important;
}}
.stApp h1 {{
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
}}

/* Metric cards */
div[data-testid="stMetric"] {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
    padding: 16px !important;
}}
div[data-testid="stMetric"] label {{
    color: {TEXT_SECONDARY} !important;
    font-size: 0.75rem !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}}
div[data-testid="stMetric"] div[data-testid="stMetricValue"] {{
    color: {TEXT_PRIMARY} !important;
    font-family: {MONO_FONT} !important;
}}

/* Dataframe */
.stDataFrame {{
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
}}

/* Inputs */
.stTextInput input, .stTextArea textarea, .stNumberInput input,
.stSelectbox > div > div {{
    background-color: {BG_ELEVATED} !important;
    color: {TEXT_PRIMARY} !important;
    border-color: {BORDER_SUBTLE} !important;
}}
.stTextInput input:focus, .stTextArea textarea:focus, .stNumberInput input:focus {{
    border-color: {BLUE} !important;
    box-shadow: 0 0 0 1px {BLUE} !important;
}}

/* Buttons — outlined default */
.stButton > button {{
    background-color: transparent !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_EMPHASIS} !important;
    border-radius: 6px !important;
    transition: all 0.15s ease !important;
}}
.stButton > button:hover {{
    border-color: {BLUE} !important;
    color: {BLUE} !important;
}}
/* Primary button — filled */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stFormSubmitButton"] {{
    background-color: {BLUE} !important;
    color: #ffffff !important;
    border-color: {BLUE} !important;
}}

/* Expander */
.streamlit-expanderHeader {{
    background-color: {BG_CARD} !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 6px !important;
}}
details[data-testid="stExpander"] {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
}}

/* Container borders */
div[data-testid="stVerticalBlock"] > div[data-testid="stHorizontalBlock"] > div > div.element-container {{
    color: {TEXT_PRIMARY} !important;
}}
div.stContainer {{
    border-color: {BORDER_SUBTLE} !important;
}}

/* Dividers */
hr {{
    border-color: {BORDER_SUBTLE} !important;
}}

/* Captions */
.stCaption, .stApp .stMarkdown small {{
    color: {TEXT_MUTED} !important;
}}

/* Code blocks */
.stCode, .stApp pre {{
    background-color: {BG_ELEVATED} !important;
    color: {TEXT_PRIMARY} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
}}

/* Alerts */
.stAlert {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{
    background-color: transparent !important;
}}
.stTabs [data-baseweb="tab"] {{
    color: {TEXT_SECONDARY} !important;
}}
.stTabs [aria-selected="true"] {{
    color: {TEXT_PRIMARY} !important;
    border-bottom-color: {BLUE} !important;
}}

/* Selectbox dropdown */
div[data-baseweb="select"] {{
    background-color: {BG_ELEVATED} !important;
}}
div[data-baseweb="popover"] {{
    background-color: {BG_ELEVATED} !important;
}}
div[data-baseweb="popover"] li {{
    color: {TEXT_PRIMARY} !important;
}}

/* Slider */
.stSlider > div > div > div {{
    color: {TEXT_SECONDARY} !important;
}}

/* Forms */
div[data-testid="stForm"] {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_SUBTLE} !important;
    border-radius: 8px !important;
    padding: 1rem !important;
}}

/* Dialog */
div[data-testid="stDialog"] > div {{
    background-color: {BG_CARD} !important;
    border: 1px solid {BORDER_EMPHASIS} !important;
}}

/* Multiselect */
span[data-baseweb="tag"] {{
    background-color: {BORDER_EMPHASIS} !important;
    color: {TEXT_PRIMARY} !important;
}}

/* Toggle */
div[data-testid="stToggle"] label span {{
    color: {TEXT_PRIMARY} !important;
}}
</style>
"""


def apply_theme():
    """Inject the Palantir dark theme CSS. Call at the top of every page."""
    import streamlit as st
    st.markdown(_CSS, unsafe_allow_html=True)


def status_dot(color: str, size: int = 8) -> str:
    """Return an inline HTML span for a colored status dot."""
    return (
        f'<span style="display:inline-block;width:{size}px;height:{size}px;'
        f'border-radius:50%;background:{color};margin-right:6px;'
        f'vertical-align:middle;"></span>'
    )


def mono(value) -> str:
    """Wrap a value in monospace font styling."""
    return f'<span style="font-family:{MONO_FONT};color:{TEXT_PRIMARY}">{value}</span>'


def health_color(status: str) -> str:
    """Map a health status string to its accent color."""
    return STATUS_COLORS.get(status, TEXT_MUTED)
