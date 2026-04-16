"""DRAFTi Pro - NFL Draft Value Evaluator.

Three modes:
  1. Live Draft Tracker  — grade picks in real time as the NFL draft happens
  2. Historical Analysis — evaluate past draft classes with actual career outcomes
  3. Prospect Explorer   — browse consensus boards, positional value, and hit rates
"""
import streamlit as st
import pandas as pd
import json
import html
import math
import os
import sys

# Add parent dir so we can import if needed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from draft_engine_pro import (
    NFL_POSITIONS, GRADE_VALUES, GRADE_THRESHOLDS, STATUS_LABELS,
    ordinal, utc_timestamp, pick_to_round,
    load_trade_value_chart, load_position_values,
    load_historical_drafts, load_consensus_board, available_consensus_board_years,
    get_pick_value, calculate_trade_surplus,
    grade_pick, grade_team_draft,
    evaluate_historical_pick, evaluate_historical_draft_class,
    find_historical_comps, get_position_hit_rate_summary,
    init_live_draft, record_live_pick, record_live_trade,
    get_live_draft_team_summary, get_live_draft_leaderboard,
    get_remaining_top_prospects,
    save_evaluated_draft,
    # Pro signal loaders
    load_transaction_wire, get_transaction_wire_summary,
    apply_transaction_wire_to_board,
    load_team_schemes, load_cap_context,
    compute_combine_score, compute_cfb_production_score,
    compute_injury_risk_penalty, compute_board_velocity_signal,
    compute_recruiting_signal, compute_source_confidence,
    compute_scheme_bonus, compute_cap_bonus,
)

# ---------------------------------------------------------------------------
# THEME (shared palette with fantasy app)
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        "BG": "#0a0a0f", "PANEL_BG": "#111116", "TEXT_PRI": "#f2f2f8",
        "TEXT_SEC": "#a0a8be", "GRID_LINE": "#1e1e2a", "BORDER": "#1e1e2a",
        "CARD_BG": "#111116", "STAT_BG": "#161620", "CARD_HOVER": "#18181f",
        "SURFACE": "#1a1a24",
    },
    "light": {
        "BG": "#f3f4f6", "PANEL_BG": "#ffffff", "TEXT_PRI": "#111827",
        "TEXT_SEC": "#4b5563", "GRID_LINE": "#e5e7eb", "BORDER": "#d1d5db",
        "CARD_BG": "#ffffff", "STAT_BG": "#f9fafb", "CARD_HOVER": "#f3f4f6",
        "SURFACE": "#f0f1f3",
    },
}

ACCENT_GOLD = "#facc15"
ACCENT_GRN  = "#10b981"
ACCENT_RED  = "#ef4444"
ACCENT_BLUE = "#3b82f6"

POS_COLORS = {
    "QB": "#a78bfa", "EDGE": "#34d399", "OT": "#60a5fa", "CB": "#fb923c",
    "WR": "#f472b6", "IDL": "#f87171", "S": "#38bdf8", "LB": "#a3e635",
    "IOL": "#818cf8", "TE": "#fbbf24", "RB": "#4ade80", "K": "#c084fc", "P": "#94a3b8",
}
POS_COLORS_BG = {k: v + "1f" for k, v in POS_COLORS.items()}

GRADE_COLORS = {
    "A+": "#10b981", "A": "#10b981", "A-": "#34d399",
    "B+": "#86efac", "B": "#86efac", "B-": "#bef264",
    "C+": "#facc15", "C": "#facc15", "C-": "#fbbf24",
    "D+": "#fb923c", "D": "#fb923c", "F": "#ef4444", "N/A": "#6b7280",
}
GRADE_COLORS_BG = {k: v + "26" for k, v in GRADE_COLORS.items()}

STATUS_COLORS = {
    "star": "#10b981", "starter": "#60a5fa", "developing": "#facc15",
    "bust": "#ef4444", "out": "#6b7280", "unknown": "#94a3b8",
}

VERDICT_COLORS = {
    "Steal": "#10b981", "Great Value": "#34d399", "Fair Value": "#60a5fa",
    "Slight Reach": "#fbbf24", "Major Reach": "#ef4444",
    "Off-Board Pick": "#f87171", "Dart Throw": "#94a3b8",
}

NFL_TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE",
    "DAL", "DEN", "DET", "GB", "HOU", "IND", "JAX", "KC",
    "LV", "LAC", "LAR", "MIA", "MIN", "NE", "NO", "NYG",
    "NYJ", "PHI", "PIT", "SF", "SEA", "TB", "TEN", "WAS",
]

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="DRAFTi Pro \u2014 NFL Draft Evaluator",
    page_icon="\U0001f3c8",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------------
_defaults = {
    "theme": "dark",
    "pro_mode": "Live Draft Tracker",
    "live_draft_state": None,
    "draft_year": 2026,
    "historical_year": 2023,
    "global_search_query": "",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# --- Lazily-loaded pro signal data (cached per session) ---
@st.cache_data(ttl=300)
def _cached_team_schemes():
    return load_team_schemes()

@st.cache_data(ttl=300)
def _cached_cap_context():
    return load_cap_context()

@st.cache_data(ttl=300)
def _cached_transaction_wire(year):
    return get_transaction_wire_summary(year)

# ---------------------------------------------------------------------------
# ACTIVE THEME
# ---------------------------------------------------------------------------
_T = THEMES[st.session_state.theme]
BG = _T["BG"]; PANEL_BG = _T["PANEL_BG"]
TEXT_PRI = _T["TEXT_PRI"]; TEXT_SEC = _T["TEXT_SEC"]
BORDER = _T["BORDER"]; CARD_BG = _T["CARD_BG"]
STAT_BG = _T["STAT_BG"]; SURFACE = _T["SURFACE"]
IS_DARK = st.session_state.theme == "dark"

SUCCESS_TX = "#34d399" if IS_DARK else "#047857"
WARNING_TX = "#fbbf24" if IS_DARK else "#92400e"
INFO_TX = "#93c5fd" if IS_DARK else "#1d4ed8"
DANGER_TX = "#f87171" if IS_DARK else "#b91c1c"

# ---------------------------------------------------------------------------
# UI TOKENS
# ---------------------------------------------------------------------------
UI_SPACE_1 = 4; UI_SPACE_2 = 8; UI_SPACE_3 = 12
UI_SPACE_4 = 16; UI_SPACE_5 = 24; UI_SPACE_6 = 32
UI_RADIUS_SM = 8; UI_RADIUS_MD = 12; UI_RADIUS_LG = 14
UI_TEXT_XS = 0.68; UI_TEXT_SM = 0.78; UI_TEXT_MD = 0.90
UI_TEXT_H3 = 1.50; UI_TEXT_2XS = 0.62; UI_TEXT_LABEL = 0.68

_SYS_FONT = "system-ui,sans-serif"
_MONO_FONT = "SFMono-Regular,Consolas,monospace"
_btn_bg = "#2e2e3a" if IS_DARK else "#e8e8f0"
_btn_hover = "#3a3a4a" if IS_DARK else "#d8d8e8"

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown(f"""<style>
*{{font-family:{_SYS_FONT}}}
.stApp{{background:{BG};color:{TEXT_PRI}}}
.block-container{{padding-top:{UI_SPACE_3}px;padding-bottom:{UI_SPACE_4}px;max-width:1400px}}
h1,h2,h3,h4{{color:{TEXT_PRI};font-weight:800;letter-spacing:-.02em}}
h4,h5,h6{{text-transform:uppercase;letter-spacing:.08em;font-size:.75rem;color:{TEXT_SEC}}}
p,li,span{{color:{TEXT_PRI};line-height:1.45}}
div[data-testid="stMetricValue"]{{color:{TEXT_PRI};font-size:1.6rem;font-weight:800;font-variant-numeric:tabular-nums}}
div[data-testid="stMetricLabel"]{{color:{TEXT_SEC};font-size:{UI_TEXT_LABEL}rem;text-transform:uppercase;letter-spacing:.095em;font-weight:700}}
div[data-testid="stCaptionContainer"] p{{color:{TEXT_SEC};font-size:{UI_TEXT_XS}rem}}
.stSelectbox label,.stTextInput label,.stSlider label,.stNumberInput label{{color:{TEXT_SEC};font-size:.78rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
.stButton>button{{background:{_btn_bg};color:{TEXT_PRI};border:1px solid {BORDER};border-radius:{UI_RADIUS_SM}px;font-weight:600;transition:all .15s}}
.stButton>button:hover{{background:{_btn_hover};border-color:{ACCENT_GRN};color:{ACCENT_GRN}}}
.stButton>button[kind="primary"],.stButton>button[data-testid="stBaseButton-primary"]{{background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none;font-weight:700;text-transform:uppercase;letter-spacing:.06em}}
.stButton>button[kind="primary"]:hover,.stButton>button[data-testid="stBaseButton-primary"]:hover{{background:linear-gradient(135deg,#059669,#047857);color:#fff}}
.stTabs [data-baseweb="tab-list"]{{border-bottom:1px solid {BORDER}}}
.stTabs [data-baseweb="tab"]{{color:{TEXT_SEC};font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
.stTabs [aria-selected="true"]{{color:{ACCENT_GRN}!important;border-bottom:2px solid {ACCENT_GRN}!important}}
div[data-testid="stDataFrame"]{{background:{PANEL_BG};border-radius:{UI_RADIUS_SM}px;border:1px solid {BORDER}}}
hr{{border-color:{BORDER};opacity:.5}}
code,.stCode{{font-family:{_MONO_FONT};font-variant-numeric:tabular-nums}}
::-webkit-scrollbar{{width:6px}}
::-webkit-scrollbar-thumb{{background:{BORDER};border-radius:3px}}
#MainMenu,footer,header{{visibility:hidden}}
div[data-testid="stExpander"] details summary{{font-weight:600;font-size:0.9rem;border-radius:{UI_RADIUS_SM}px}}
div[data-testid="stExpander"] details summary span{{color:{TEXT_SEC}}}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# SHARED UI HELPERS
# ---------------------------------------------------------------------------
def _section_header(title, subtitle=""):
    st.markdown(
        "<div style='margin-bottom:" + str(UI_SPACE_4) + "px;'>"
        "<h3 style='color:" + TEXT_PRI + ";font-weight:800;font-size:" + str(UI_TEXT_H3) + "rem;"
        "letter-spacing:-0.02em;margin:0;'>" + html.escape(title) + "</h3>"
        + ("<p style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_SM) + "rem;margin:" + str(UI_SPACE_1) + "px 0 0;'>"
           + subtitle + "</p>" if subtitle else "")
        + "</div>", unsafe_allow_html=True,
    )


def _eyebrow(text, mb=UI_SPACE_2):
    st.markdown(
        "<h5 style='color:" + TEXT_SEC + ";margin:0 0 " + str(mb) + "px;font-weight:700;"
        "text-transform:uppercase;letter-spacing:0.10em;font-size:" + str(UI_TEXT_2XS) + "rem;'>"
        + html.escape(text) + "</h5>", unsafe_allow_html=True,
    )


def _grade_badge(grade, size="lg"):
    color = GRADE_COLORS.get(grade, "#6b7280")
    bg = GRADE_COLORS_BG.get(grade, "rgba(107,114,128,0.1)")
    fs = "2.2rem" if size == "lg" else ("1.1rem" if size == "md" else "0.85rem")
    pad = "8px 16px" if size == "lg" else ("4px 10px" if size == "md" else "3px 8px")
    return (
        "<span style='color:" + color + ";background:" + bg + ";font-size:" + fs + ";"
        "font-weight:800;padding:" + pad + ";border-radius:" + str(UI_RADIUS_SM) + "px;"
        "font-family:" + _MONO_FONT + ";letter-spacing:-0.02em;'>" + html.escape(grade) + "</span>"
    )


def _verdict_badge(verdict):
    color = VERDICT_COLORS.get(verdict, TEXT_SEC)
    return (
        "<span style='color:" + color + ";font-size:" + str(UI_TEXT_SM) + "rem;"
        "font-weight:700;padding:3px 8px;border-radius:999px;border:1px solid " + color + "44;"
        "background:" + color + "15;'>" + html.escape(verdict) + "</span>"
    )


def _pos_badge(pos):
    color = POS_COLORS.get(pos, TEXT_SEC)
    bg = POS_COLORS_BG.get(pos, "transparent")
    return (
        "<span style='color:" + color + ";background:" + bg + ";font-size:0.75rem;"
        "font-weight:700;padding:2px 8px;border-radius:999px;letter-spacing:0.04em;'>"
        + html.escape(pos) + "</span>"
    )


def _status_dot(status):
    color = STATUS_COLORS.get(status, "#94a3b8")
    label = STATUS_LABELS.get(status, status)
    return (
        "<span style='display:inline-flex;align-items:center;gap:5px;font-size:" + str(UI_TEXT_SM) + "rem;'>"
        "<span style='width:8px;height:8px;border-radius:50%;background:" + color + ";display:inline-block;'></span>"
        "<span style='color:" + color + ";font-weight:600;'>" + html.escape(label) + "</span></span>"
    )


def _normalize_search_text(value):
    return " ".join(str(value or "").lower().split())


def _matches_query(query, *fields):
    q = _normalize_search_text(query)
    if not q:
        return True
    hay = " ".join(_normalize_search_text(v) for v in fields if v is not None)
    return all(token in hay for token in q.split())


def _result_count_badge(label, count):
    return (
        "<div style='display:inline-flex;align-items:center;gap:8px;"
        "background:" + STAT_BG + ";border:1px solid " + BORDER + ";"
        "border-radius:999px;padding:3px 10px;margin-bottom:8px;'>"
        "<span style='color:" + TEXT_SEC + ";font-size:0.68rem;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;'>"
        + html.escape(str(label)) + "</span>"
        "<span style='color:" + TEXT_PRI + ";font-size:0.78rem;font-weight:800;font-family:" + _MONO_FONT + ";'>"
        + html.escape(str(count)) + "</span></div>"
    )


def _render_validation_messages(board_data, year_label):
    validation = (board_data or {}).get("_validation", {})
    if not isinstance(validation, dict):
        return
    warnings = validation.get("warnings", []) or []
    errors = validation.get("errors", []) or []
    stats = validation.get("stats", {}) or {}
    if stats.get("num_prospects"):
        st.caption(
            "Board validation: "
            + str(stats.get("num_prospects"))
            + " prospects checked for "
            + str(year_label)
            + "."
        )
    for msg in errors[:5]:
        st.error("Data quality error: " + str(msg))
    for msg in warnings[:6]:
        st.warning("Data quality warning: " + str(msg))


def _render_remediation_messages(board_data, year_label):
    remediation = (board_data or {}).get("_remediation", {})
    if not isinstance(remediation, dict):
        return
    removed = remediation.get("dedupe_names_removed", []) or []
    if not removed:
        return
    names = [str(x.get("name", "")) for x in removed if isinstance(x, dict) and x.get("name")]
    st.caption(
        "Auto-remediation for "
        + str(year_label)
        + ": removed "
        + str(len(removed))
        + " duplicate name entr"
        + ("y" if len(removed) == 1 else "ies")
        + ((" (" + ", ".join(names[:3]) + (" ..." if len(names) > 3 else "") + ")") if names else "")
    )


def _stat_card(label, value, accent=None):
    ac = accent or TEXT_PRI
    return (
        "<div style='background:" + STAT_BG + ";border:1px solid " + BORDER + ";border-radius:" + str(UI_RADIUS_SM) + "px;"
        "padding:" + str(UI_SPACE_3) + "px " + str(UI_SPACE_4) + "px;text-align:center;'>"
        "<div style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_2XS) + "rem;font-weight:700;"
        "text-transform:uppercase;letter-spacing:0.10em;margin-bottom:4px;'>" + html.escape(str(label)) + "</div>"
        "<div style='color:" + ac + ";font-size:1.4rem;font-weight:800;font-family:" + _MONO_FONT + ";"
        "font-variant-numeric:tabular-nums;'>" + html.escape(str(value)) + "</div></div>"
    )


ELIGIBILITY_ICONS = {
    "declared": ("✓", "#10b981"),
    "withdrew": ("⚠", "#fbbf24"),
    "medical_retirement": ("✕", "#ef4444"),
    "transferred": ("→", "#60a5fa"),
    "undeclared": ("?", "#94a3b8"),
}

VELOCITY_ICONS = {
    "rising": "↑", "falling": "↓", "stable": "→",
}


def _eligibility_badge(status):
    icon, color = ELIGIBILITY_ICONS.get(status or "declared", ("✓", "#10b981"))
    label = (status or "declared").replace("_", " ").title()
    return (
        "<span style='color:" + color + ";font-size:0.72rem;font-weight:700;"
        "background:" + color + "18;padding:2px 7px;border-radius:999px;"
        "border:1px solid " + color + "44;'>" + icon + " " + label + "</span>"
    )


def _velocity_badge(board_velocity):
    if not board_velocity:
        return ""
    weekly = board_velocity.get("weekly_change")
    stability = board_velocity.get("stability", "")
    if weekly is None:
        return ""
    try:
        w = float(weekly)
    except (TypeError, ValueError):
        return ""
    if abs(w) < 1:
        return ""
    color = "#10b981" if w > 0 else "#ef4444"
    icon = "↑" if w > 0 else "↓"
    return (
        "<span style='color:" + color + ";font-size:0.72rem;font-weight:700;"
        "background:" + color + "18;padding:2px 7px;border-radius:999px;"
        "border:1px solid " + color + "44;'>"
        + icon + " " + str(abs(int(w))) + " spots</span>"
    )


def _injury_flag_badge():
    return (
        "<span style='color:#ef4444;font-size:0.72rem;font-weight:700;"
        "background:#ef444418;padding:2px 7px;border-radius:999px;"
        "border:1px solid #ef444444;'>🩺 Injury Flag</span>"
    )


def _signal_breakdown_html(graded):
    """Compact signal bar showing new pro signal contributions."""
    signals = [
        ("Board", graded.get("board_delta", 0)),
        ("Pos", graded.get("positional_adj", 0)),
        ("Need", graded.get("need_bonus", 0)),
        ("Tier", graded.get("tier_bonus", 0)),
        ("Ath", graded.get("athletic_bonus", 0)),
        ("CFB", graded.get("production_bonus", 0)),
        ("Inj", graded.get("injury_penalty", 0)),
        ("Vel", graded.get("velocity_bonus", 0)),
        ("Rec", graded.get("recruiting_bonus", 0)),
        ("Fit", graded.get("scheme_bonus", 0) + graded.get("cap_bonus", 0)),
    ]
    parts = []
    for label, val in signals:
        if abs(val) < 0.01:
            continue
        color = SUCCESS_TX if val > 0 else DANGER_TX
        sign = "+" if val > 0 else ""
        parts.append(
            "<span style='font-size:0.65rem;color:" + color + ";font-family:" + _MONO_FONT + ";'>"
            + label + ":" + sign + str(round(val, 2)) + "</span>"
        )
    if not parts:
        return ""
    return (
        "<div style='display:flex;flex-wrap:wrap;gap:6px;margin-top:5px;'>"
        + " ".join(parts) + "</div>"
    )


def _pick_card(graded, show_team=True):
    """Render a single graded pick as an HTML card."""
    grade = graded["grade"]
    g_color = GRADE_COLORS.get(grade, "#6b7280")
    g_bg = GRADE_COLORS_BG.get(grade, "rgba(107,114,128,0.1)")
    v_color = VERDICT_COLORS.get(graded["verdict"], TEXT_SEC)
    pos_color = POS_COLORS.get(graded["position"], TEXT_SEC)

    team_html = ""
    if show_team and graded.get("team"):
        team_html = (
            "<span style='color:" + TEXT_SEC + ";font-size:0.75rem;font-weight:700;"
            "background:" + STAT_BG + ";padding:2px 6px;border-radius:4px;'>"
            + html.escape(graded["team"]) + "</span> "
        )

    consensus_html = ""
    if graded.get("consensus_rank"):
        delta = graded["consensus_rank"] - graded["pick_overall"]
        delta_color = SUCCESS_TX if delta > 0 else (DANGER_TX if delta < 0 else TEXT_SEC)
        delta_str = ("+" + str(delta)) if delta > 0 else str(delta)
        consensus_html = (
            "<div style='margin-top:6px;font-size:" + str(UI_TEXT_XS) + "rem;color:" + TEXT_SEC + ";'>"
            "Board rank: <span style='font-weight:700;'>#" + str(graded["consensus_rank"]) + "</span>"
            " &nbsp; Delta: <span style='color:" + delta_color + ";font-weight:700;'>" + delta_str + "</span>"
            "</div>"
        )

    needs_html = ""
    if graded.get("needs_filled"):
        needs_html = (
            "<span style='color:" + SUCCESS_TX + ";font-size:" + str(UI_TEXT_XS) + "rem;font-weight:600;'>"
            "Fills need</span>"
        )

    hit_html = ""
    if graded.get("hit_rate") is not None:
        pct = int(graded["hit_rate"] * 100)
        hit_html = (
            "<div style='font-size:" + str(UI_TEXT_XS) + "rem;color:" + TEXT_SEC + ";margin-top:4px;'>"
            "Historical hit rate for Rd " + str(graded["round"]) + " " + graded["position"] + ": "
            "<span style='font-weight:700;'>" + str(pct) + "%</span></div>"
        )

    # --- New signal flags ---
    flags_html = ""
    if graded.get("injury_flag"):
        flags_html += " " + _injury_flag_badge()
    conf = graded.get("source_confidence", 1.0)
    if conf < 0.85:
        flags_html += (
            " <span style='color:#fbbf24;font-size:0.70rem;background:#fbbf2418;"
            "padding:2px 6px;border-radius:999px;border:1px solid #fbbf2444;'>"
            "Low source consensus</span>"
        )
    scheme_b = graded.get("scheme_bonus", 0)
    cap_b = graded.get("cap_bonus", 0)
    fit_total = scheme_b + cap_b
    if fit_total >= 0.15:
        flags_html += (
            " <span style='color:#60a5fa;font-size:0.70rem;background:#60a5fa18;"
            "padding:2px 6px;border-radius:999px;border:1px solid #60a5fa44;'>"
            "+ Scheme/Cap fit</span>"
        )

    signal_html = _signal_breakdown_html(graded)

    return (
        "<div style='background:" + CARD_BG + ";border:1px solid " + BORDER + ";border-radius:" + str(UI_RADIUS_MD) + "px;"
        "padding:" + str(UI_SPACE_4) + "px;margin-bottom:" + str(UI_SPACE_2) + "px;'>"
        "<div style='display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;'>"
        # Left: pick info
        "<div style='flex:1;min-width:200px;'>"
        "<div style='display:flex;align-items:center;gap:8px;margin-bottom:4px;flex-wrap:wrap;'>"
        "<span style='color:" + TEXT_SEC + ";font-size:0.8rem;font-weight:700;font-family:" + _MONO_FONT + ";'>"
        "Pick " + str(graded["pick_overall"]) + "</span>"
        + team_html
        + _pos_badge(graded["position"])
        + " " + needs_html
        + flags_html
        + "</div>"
        "<div style='font-size:1.15rem;font-weight:800;color:" + TEXT_PRI + ";'>"
        + html.escape(graded["player"]) + "</div>"
        + consensus_html + hit_html + signal_html
        + "</div>"
        # Right: grade + verdict
        "<div style='text-align:right;'>"
        + _grade_badge(grade, "md")
        + "<div style='margin-top:6px;'>" + _verdict_badge(graded["verdict"]) + "</div>"
        + "</div>"
        "</div></div>"
    )


# ---------------------------------------------------------------------------
# HEADER
# ---------------------------------------------------------------------------
hdr_c1, hdr_c2, hdr_c3 = st.columns([5, 3, 2])
with hdr_c1:
    st.markdown(
        "<div style='padding:" + str(UI_SPACE_3) + "px 0;'>"
        "<h1 style='margin:0;font-size:2rem;letter-spacing:-0.03em;'>"
        "<span style='color:" + ACCENT_GRN + ";'>DRAFTi</span>"
        " <span style='color:" + TEXT_SEC + ";font-weight:400;font-size:1.2rem;'>Pro</span></h1>"
        "<p style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_SM) + "rem;margin:2px 0 0;'>"
        "NFL Draft Value Evaluator &mdash; Real picks. Real grades. Real outcomes.</p></div>",
        unsafe_allow_html=True,
    )
with hdr_c2:
    mode = st.selectbox(
        "MODE",
        ["Live Draft Tracker", "Historical Analysis", "Prospect Explorer"],
        index=["Live Draft Tracker", "Historical Analysis", "Prospect Explorer"].index(
            st.session_state.pro_mode
        ),
        key="mode_select",
    )
    st.session_state.pro_mode = mode
with hdr_c3:
    # Align theme button baseline with the mode selectbox control row.
    st.markdown("<div style='height:30px;'></div>", unsafe_allow_html=True)
    if st.button("Dark" if st.session_state.theme == "light" else "Light", width="stretch"):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()

search_c1, search_c2 = st.columns([8, 1])
with search_c1:
    search_query = st.text_input(
        "Search prospects / players",
        key="global_search_query",
        placeholder="Type a name, team, school, or position (e.g. Cam Ward, QB, Miami)",
    )
with search_c2:
    st.markdown("<div style='height:26px;'></div>", unsafe_allow_html=True)
    if st.button("Clear", width="stretch", key="clear_global_search"):
        st.session_state.global_search_query = ""
        st.rerun()
if _normalize_search_text(search_query):
    st.caption("Search active: " + html.escape(search_query))

st.markdown("<hr style='margin:0 0 " + str(UI_SPACE_4) + "px;border-color:" + BORDER + ";opacity:0.5;'>", unsafe_allow_html=True)


# ===========================================================================
# MODE 1: LIVE DRAFT TRACKER
# ===========================================================================
if st.session_state.pro_mode == "Live Draft Tracker":
    _section_header("Live Draft Tracker", "Record picks as they happen. Every pick is graded instantly against the consensus board.")

    # --- Setup / Controls ---
    ctrl_c1, ctrl_c2 = st.columns([1, 3])
    with ctrl_c1:
        draft_year = st.number_input("Draft Year", min_value=2020, max_value=2030, value=st.session_state.draft_year, key="live_year")
        st.session_state.draft_year = draft_year

        if st.session_state.live_draft_state is None:
            if st.button("Start Tracking", type="primary", width="stretch"):
                st.session_state.live_draft_state = init_live_draft(draft_year)
                st.rerun()
        else:
            ds = st.session_state.live_draft_state
            st.markdown(
                _stat_card("Current Pick", "#" + str(ds["current_pick"]), ACCENT_GRN),
                unsafe_allow_html=True,
            )
            st.markdown(
                _stat_card("Round", str(pick_to_round(ds["current_pick"])), ACCENT_BLUE),
                unsafe_allow_html=True,
            )
            st.markdown(
                _stat_card("Picks Recorded", str(len(ds["picks"])), TEXT_PRI),
                unsafe_allow_html=True,
            )
            st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
            if st.button("Reset Draft", width="stretch"):
                st.session_state.live_draft_state = None
                st.rerun()

    with ctrl_c2:
        ds = st.session_state.live_draft_state
        if ds is not None:
            _src_year = ds.get("board_data", {}).get("_source_year")
            _req_year = ds.get("board_data", {}).get("_requested_year")
            if _src_year and _req_year and _src_year != _req_year:
                st.info(
                    "Consensus board data for " + str(_req_year) + " is not available yet; using "
                    + str(_src_year) + " board as the closest proxy.",
                    icon="ℹ️",
                )
            _excluded = ds.get("board_data", {}).get("_excluded_prospects", [])
            if _excluded:
                st.caption(
                    "Excluded known non-eligible names for "
                    + str(_req_year or draft_year)
                    + ": " + ", ".join(_excluded[:5])
                    + (" ..." if len(_excluded) > 5 else "")
                )
            _overrides = ds.get("board_data", {}).get("_overrides_applied", [])
            if _overrides:
                st.caption(
                    "Applied board corrections for "
                    + str(_req_year or draft_year)
                    + ": " + ", ".join(_overrides[:3])
                    + (" ..." if len(_overrides) > 3 else "")
                )
            _render_remediation_messages(ds.get("board_data", {}), _req_year or draft_year)
            _render_validation_messages(ds.get("board_data", {}), _req_year or draft_year)
            # --- Pick entry form ---
            _eyebrow("Record Pick #" + str(ds["current_pick"]))
            form_c1, form_c2, form_c3, form_c4 = st.columns([2, 3, 2, 1])
            with form_c1:
                team = st.selectbox("Team", NFL_TEAMS, key="pick_team")
            with form_c2:
                player_name = st.text_input("Player Name", key="pick_player", placeholder="e.g. Cam Ward")
            with form_c3:
                position = st.selectbox("Position", NFL_POSITIONS, key="pick_position")
            with form_c4:
                st.markdown("<div style='height:26px;'></div>", unsafe_allow_html=True)
                pick_submitted = st.button("Grade", type="primary", width="stretch", key="submit_pick")

            if pick_submitted and player_name.strip():
                graded = record_live_pick(ds, team, player_name.strip(), position)
                st.rerun()

            # --- Tabs: Feed / Leaderboard / Best Available ---
            if ds["graded_picks"]:
                tabs = st.tabs(["Pick Feed", "Team Leaderboard", "Best Available"])

                with tabs[0]:
                    # Show graded picks in reverse order
                    filtered_feed = [
                        gp for gp in reversed(ds["graded_picks"])
                        if _matches_query(
                            search_query,
                            gp.get("player", ""),
                            gp.get("team", ""),
                            gp.get("position", ""),
                            gp.get("verdict", ""),
                        )
                    ]
                    st.markdown(_result_count_badge("Matching picks", len(filtered_feed)), unsafe_allow_html=True)
                    if not filtered_feed:
                        st.info("No pick feed matches for the current search.")
                    for gp in filtered_feed:
                        st.markdown(_pick_card(gp), unsafe_allow_html=True)

                with tabs[1]:
                    leaderboard = get_live_draft_leaderboard(ds)
                    if leaderboard:
                        filtered_leaderboard = []
                        for team_sum in leaderboard:
                            if _matches_query(
                                search_query,
                                team_sum.get("team", ""),
                                " ".join(p.get("player", "") for p in team_sum.get("picks", [])),
                                " ".join(p.get("position", "") for p in team_sum.get("picks", [])),
                            ):
                                filtered_leaderboard.append(team_sum)
                        st.markdown(_result_count_badge("Matching teams", len(filtered_leaderboard)), unsafe_allow_html=True)
                        if not filtered_leaderboard:
                            st.info("No leaderboard teams match the current search.")
                        for rank, team_sum in enumerate(filtered_leaderboard, 1):
                            grade = team_sum["overall_grade"]
                            g_color = GRADE_COLORS.get(grade, "#6b7280")
                            picks_str = ", ".join(p["position"] for p in team_sum["picks"])
                            st.markdown(
                                "<div style='display:flex;align-items:center;gap:12px;padding:8px 12px;"
                                "background:" + CARD_BG + ";border:1px solid " + BORDER + ";"
                                "border-radius:" + str(UI_RADIUS_SM) + "px;margin-bottom:4px;'>"
                                "<span style='color:" + TEXT_SEC + ";font-weight:700;font-family:" + _MONO_FONT + ";"
                                "font-size:0.85rem;min-width:24px;'>" + str(rank) + "</span>"
                                "<span style='font-weight:800;font-size:1rem;min-width:40px;'>" + html.escape(team_sum["team"]) + "</span>"
                                + _grade_badge(grade, "sm")
                                + "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;margin-left:auto;'>"
                                + html.escape(picks_str) + "</span>"
                                "</div>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.info("Record picks to see team rankings.")

                with tabs[2]:
                    remaining = get_remaining_top_prospects(ds, n=15)
                    remaining = [
                        p for p in remaining
                        if _matches_query(
                            search_query,
                            p.get("name", ""),
                            p.get("position", ""),
                            p.get("school", ""),
                        )
                    ]
                    st.markdown(_result_count_badge("Best available", len(remaining)), unsafe_allow_html=True)
                    if remaining:
                        for p in remaining:
                            st.markdown(
                                "<div style='display:flex;align-items:center;gap:10px;padding:6px 12px;"
                                "background:" + CARD_BG + ";border:1px solid " + BORDER + ";"
                                "border-radius:" + str(UI_RADIUS_SM) + "px;margin-bottom:3px;'>"
                                "<span style='color:" + TEXT_SEC + ";font-weight:700;font-family:" + _MONO_FONT + ";"
                                "font-size:0.8rem;min-width:28px;'>#" + str(p["consensus_rank"]) + "</span>"
                                + _pos_badge(p["position"])
                                + "<span style='font-weight:700;font-size:0.95rem;'>" + html.escape(p["name"]) + "</span>"
                                "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;margin-left:auto;'>"
                                + html.escape(p.get("school", "")) + "</span>"
                                "</div>",
                                unsafe_allow_html=True,
                            )
                    else:
                        st.info("All board prospects have been drafted.")
            else:
                st.info("Enter picks above to start grading the draft.", icon="\U0001f3c8")
        else:
            st.info("Select a draft year and click **Start Tracking** to begin grading the NFL draft in real time.", icon="\u2b50")


# ===========================================================================
# MODE 2: HISTORICAL ANALYSIS
# ===========================================================================
elif st.session_state.pro_mode == "Historical Analysis":
    _section_header("Historical Draft Analysis", "Evaluate past drafts using actual career outcomes &mdash; powered by real <a href='https://github.com/nflverse/nflverse-data' style='color:" + ACCENT_GRN + ";'>nflverse</a> data.")

    hist_data = load_historical_drafts()
    available_years = sorted(hist_data.get("drafts", {}).keys(), reverse=True)

    if not available_years:
        st.warning("No historical draft data found. Run `python pro/build_historical_data.py` to download real NFL data.")
    else:
        ctrl_c1, ctrl_c2, ctrl_c3 = st.columns([2, 2, 1])
        with ctrl_c1:
            year = st.selectbox("Draft Year", available_years, key="hist_year_select")
        with ctrl_c2:
            round_filter = st.selectbox("Round Filter", ["All Rounds", "Round 1", "Rounds 1-3", "Late Rounds (4-7)"], key="hist_round_filter")
        with ctrl_c3:
            st.markdown("<div style='height:26px;'></div>", unsafe_allow_html=True)
            if st.button("Refresh Data", width="stretch", help="Re-download from nflverse"):
                try:
                    from build_historical_data import build_historical_data
                    build_historical_data()
                    st.success("Data refreshed from nflverse!")
                    st.rerun()
                except Exception as e:
                    st.error("Refresh failed: " + str(e))

        evaluation = evaluate_historical_draft_class(int(year))

        # Apply round filter
        if evaluation and round_filter != "All Rounds":
            round_map = {"Round 1": [1], "Rounds 1-3": [1, 2, 3], "Late Rounds (4-7)": [4, 5, 6, 7]}
            allowed = round_map.get(round_filter, list(range(1, 8)))
            evaluation["evaluated_picks"] = [p for p in evaluation["evaluated_picks"] if p["round"] in allowed]
            evaluation["stars"] = [p for p in evaluation["stars"] if p["round"] in allowed]
            evaluation["busts"] = [p for p in evaluation["busts"] if p["round"] in allowed]
            if evaluation["evaluated_picks"]:
                evaluation["best_pick"] = max(evaluation["evaluated_picks"], key=lambda x: x["av_surplus"])
                evaluation["worst_pick"] = min(evaluation["evaluated_picks"], key=lambda x: x["av_surplus"])
                evaluation["total_career_av"] = sum(p["career_av"] for p in evaluation["evaluated_picks"])
                evaluation["total_av_surplus"] = round(sum(p["av_surplus"] for p in evaluation["evaluated_picks"]), 1)
                evaluation["num_picks"] = len(evaluation["evaluated_picks"])

        if evaluation is None:
            st.error("Could not evaluate draft class for " + str(year))
        else:
            filtered_eval_picks = [
                p for p in evaluation["evaluated_picks"]
                if _matches_query(
                    search_query,
                    p.get("player", ""),
                    p.get("team", ""),
                    p.get("position", ""),
                    p.get("school", ""),
                )
            ]
            filtered_stars = [p for p in evaluation["stars"] if p in filtered_eval_picks]
            filtered_busts = [p for p in evaluation["busts"] if p in filtered_eval_picks]
            filtered_best = max(filtered_eval_picks, key=lambda x: x["av_surplus"]) if filtered_eval_picks else None
            filtered_worst = min(filtered_eval_picks, key=lambda x: x["av_surplus"]) if filtered_eval_picks else None
            filtered_pos_groups = {}
            for p in filtered_eval_picks:
                filtered_pos_groups.setdefault(p["position"], []).append(p)

            # --- Class summary metrics ---
            m_cols = st.columns(6)
            with m_cols[0]:
                st.markdown(_stat_card("Class Grade", evaluation["overall_grade"],
                            GRADE_COLORS.get(evaluation["overall_grade"], TEXT_PRI)), unsafe_allow_html=True)
            with m_cols[1]:
                st.markdown(_stat_card("Picks Evaluated", str(len(filtered_eval_picks)), TEXT_PRI), unsafe_allow_html=True)
            with m_cols[2]:
                st.markdown(_stat_card("Total Career AV", str(sum(p["career_av"] for p in filtered_eval_picks)), ACCENT_BLUE), unsafe_allow_html=True)
            with m_cols[3]:
                total_surplus = round(sum(p["av_surplus"] for p in filtered_eval_picks), 1)
                st.markdown(_stat_card("AV Surplus", str(total_surplus),
                            SUCCESS_TX if total_surplus > 0 else DANGER_TX), unsafe_allow_html=True)
            with m_cols[4]:
                st.markdown(_stat_card("Stars", str(len(filtered_stars)), ACCENT_GRN), unsafe_allow_html=True)
            with m_cols[5]:
                st.markdown(_stat_card("Busts", str(len(filtered_busts)), ACCENT_RED), unsafe_allow_html=True)

            st.markdown("<div style='height:" + str(UI_SPACE_4) + "px;'></div>", unsafe_allow_html=True)

            # --- Tabs: All Picks / Best & Worst / By Position ---
            tabs = st.tabs(["All Picks", "Best & Worst", "By Position"])

            with tabs[0]:
                st.markdown(_result_count_badge("Filtered picks", len(filtered_eval_picks)), unsafe_allow_html=True)
                if not filtered_eval_picks:
                    st.info("No historical picks match the current search.")
                for ep in filtered_eval_picks:
                    grade = ep["outcome_grade"]
                    g_color = GRADE_COLORS.get(grade, "#6b7280")
                    pos_color = POS_COLORS.get(ep["position"], TEXT_SEC)
                    surplus_color = SUCCESS_TX if ep["av_surplus"] > 0 else (DANGER_TX if ep["av_surplus"] < 0 else TEXT_SEC)

                    st.markdown(
                        "<div style='background:" + CARD_BG + ";border:1px solid " + BORDER + ";"
                        "border-radius:" + str(UI_RADIUS_MD) + "px;padding:" + str(UI_SPACE_3) + "px " + str(UI_SPACE_4) + "px;"
                        "margin-bottom:" + str(UI_SPACE_1) + "px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;'>"
                        # Pick number
                        "<span style='color:" + TEXT_SEC + ";font-family:" + _MONO_FONT + ";font-weight:700;"
                        "font-size:0.8rem;min-width:44px;'>Pick " + str(ep["overall"]) + "</span>"
                        # Team
                        "<span style='font-weight:700;font-size:0.8rem;color:" + TEXT_SEC + ";"
                        "background:" + STAT_BG + ";padding:2px 6px;border-radius:4px;min-width:32px;text-align:center;'>"
                        + html.escape(ep["team"]) + "</span>"
                        # Position
                        + _pos_badge(ep["position"])
                        # Name
                        + "<span style='font-weight:800;font-size:1rem;min-width:160px;'>" + html.escape(ep["player"]) + "</span>"
                        # School
                        + "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;min-width:80px;'>"
                        + html.escape(ep.get("school", "")) + "</span>"
                        # Status
                        + _status_dot(ep["status"])
                        # Stats
                        + "<span style='margin-left:auto;display:flex;gap:12px;align-items:center;'>"
                        "<span style='font-size:" + str(UI_TEXT_XS) + "rem;color:" + TEXT_SEC + ";'>"
                        "AV: <span style='font-weight:700;color:" + TEXT_PRI + ";'>" + str(ep["career_av"]) + "</span>"
                        " / " + str(ep["expected_av"]) + " exp</span>"
                        "<span style='font-size:" + str(UI_TEXT_XS) + "rem;color:" + surplus_color + ";font-weight:700;'>"
                        + ("+" if ep["av_surplus"] > 0 else "") + str(ep["av_surplus"]) + " surplus</span>"
                        + _grade_badge(grade, "sm")
                        + "</span></div>",
                        unsafe_allow_html=True,
                    )

            with tabs[1]:
                st.markdown(_result_count_badge("Best/Worst pool", len(filtered_eval_picks)), unsafe_allow_html=True)
                col_best, col_worst = st.columns(2)
                with col_best:
                    _eyebrow("Best Value Pick")
                    if filtered_best:
                        bp = filtered_best
                        st.markdown(
                            "<div style='background:" + CARD_BG + ";border:2px solid " + ACCENT_GRN + "44;"
                            "border-radius:" + str(UI_RADIUS_MD) + "px;padding:" + str(UI_SPACE_4) + "px;text-align:center;'>"
                            + _grade_badge(bp["outcome_grade"], "lg")
                            + "<div style='font-size:1.3rem;font-weight:800;margin-top:8px;'>"
                            + html.escape(bp["player"]) + "</div>"
                            "<div style='margin-top:4px;'>" + _pos_badge(bp["position"])
                            + " <span style='color:" + TEXT_SEC + ";font-size:0.85rem;'>"
                            + html.escape(bp["team"]) + " - Pick " + str(bp["overall"]) + "</span></div>"
                            "<div style='color:" + SUCCESS_TX + ";font-size:1.1rem;font-weight:700;margin-top:8px;'>"
                            "+" + str(bp["av_surplus"]) + " AV surplus</div>"
                            "<div style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_SM) + "rem;margin-top:4px;'>"
                            "Career AV: " + str(bp["career_av"]) + " | Pro Bowls: " + str(bp["pro_bowls"])
                            + " | All-Pro: " + str(bp["all_pros"]) + "</div>"
                            + "<div style='margin-top:6px;'>" + _status_dot(bp["status"]) + "</div>"
                            "</div>",
                            unsafe_allow_html=True,
                        )
                with col_worst:
                    _eyebrow("Worst Value Pick")
                    if filtered_worst:
                        wp = filtered_worst
                        st.markdown(
                            "<div style='background:" + CARD_BG + ";border:2px solid " + ACCENT_RED + "44;"
                            "border-radius:" + str(UI_RADIUS_MD) + "px;padding:" + str(UI_SPACE_4) + "px;text-align:center;'>"
                            + _grade_badge(wp["outcome_grade"], "lg")
                            + "<div style='font-size:1.3rem;font-weight:800;margin-top:8px;'>"
                            + html.escape(wp["player"]) + "</div>"
                            "<div style='margin-top:4px;'>" + _pos_badge(wp["position"])
                            + " <span style='color:" + TEXT_SEC + ";font-size:0.85rem;'>"
                            + html.escape(wp["team"]) + " - Pick " + str(wp["overall"]) + "</span></div>"
                            "<div style='color:" + DANGER_TX + ";font-size:1.1rem;font-weight:700;margin-top:8px;'>"
                            + str(wp["av_surplus"]) + " AV surplus</div>"
                            "<div style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_SM) + "rem;margin-top:4px;'>"
                            "Career AV: " + str(wp["career_av"]) + " | Pro Bowls: " + str(wp["pro_bowls"])
                            + " | All-Pro: " + str(wp["all_pros"]) + "</div>"
                            + "<div style='margin-top:6px;'>" + _status_dot(wp["status"]) + "</div>"
                            "</div>",
                            unsafe_allow_html=True,
                        )

                # Stars and busts lists
                st.markdown("<div style='height:" + str(UI_SPACE_4) + "px;'></div>", unsafe_allow_html=True)
                star_col, bust_col = st.columns(2)
                with star_col:
                    _eyebrow("Stars (" + str(len(filtered_stars)) + ")")
                    for s in filtered_stars:
                        st.markdown(
                            "<div style='padding:4px 0;'>" + _pos_badge(s["position"])
                            + " <span style='font-weight:700;'>" + html.escape(s["player"]) + "</span>"
                            " <span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;'>"
                            + html.escape(s["team"]) + " #" + str(s["overall"])
                            + " | AV " + str(s["career_av"]) + "</span></div>",
                            unsafe_allow_html=True,
                        )
                with bust_col:
                    _eyebrow("Busts (" + str(len(filtered_busts)) + ")")
                    for b in filtered_busts:
                        st.markdown(
                            "<div style='padding:4px 0;'>" + _pos_badge(b["position"])
                            + " <span style='font-weight:700;'>" + html.escape(b["player"]) + "</span>"
                            " <span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;'>"
                            + html.escape(b["team"]) + " #" + str(b["overall"])
                            + " | AV " + str(b["career_av"]) + "</span></div>",
                            unsafe_allow_html=True,
                        )

            with tabs[2]:
                st.markdown(_result_count_badge("Position matches", len(filtered_eval_picks)), unsafe_allow_html=True)
                if not filtered_pos_groups:
                    st.info("No position groups match the current search.")
                for pos, players in sorted(filtered_pos_groups.items()):
                    with st.expander(pos + " (" + str(len(players)) + " picks)", expanded=False):
                        for ep in players:
                            surplus_color = SUCCESS_TX if ep["av_surplus"] > 0 else DANGER_TX
                            st.markdown(
                                "<div style='display:flex;align-items:center;gap:10px;padding:4px 0;"
                                "border-bottom:1px solid " + BORDER + ";'>"
                                "<span style='font-family:" + _MONO_FONT + ";color:" + TEXT_SEC + ";"
                                "font-size:0.8rem;min-width:36px;'>#" + str(ep["overall"]) + "</span>"
                                "<span style='font-weight:700;min-width:140px;'>" + html.escape(ep["player"]) + "</span>"
                                "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;min-width:36px;'>"
                                + html.escape(ep["team"]) + "</span>"
                                + _status_dot(ep["status"])
                                + "<span style='margin-left:auto;color:" + surplus_color + ";font-weight:700;"
                                "font-size:0.85rem;'>" + ("+" if ep["av_surplus"] > 0 else "") + str(ep["av_surplus"])
                                + " AV</span>"
                                + _grade_badge(ep["outcome_grade"], "sm")
                                + "</div>",
                                unsafe_allow_html=True,
                            )


# ===========================================================================
# MODE 3: PROSPECT EXPLORER
# ===========================================================================
elif st.session_state.pro_mode == "Prospect Explorer":
    _section_header("Prospect Explorer", "Browse the consensus big board, positional value, combine data, and transaction wire.")

    tabs = st.tabs(["Consensus Board", "Prospect Intelligence", "Positional Value", "Trade Value Chart", "Hit Rates"])

    # --- Consensus Board ---
    with tabs[0]:
        board_year = st.number_input("Board Year", min_value=2020, max_value=2030, value=2026, key="board_year")
        available_board_years = available_consensus_board_years()
        board = load_consensus_board(board_year)
        if board is None:
            st.warning("No consensus board found for " + str(board_year) + ". Add a file at `pro/data/consensus_board_" + str(board_year) + ".json`.")
            if available_board_years:
                st.caption("Available board years: " + ", ".join(str(y) for y in available_board_years))
        else:
            source_year = board.get("_source_year")
            requested_year = board.get("_requested_year")
            if source_year and requested_year and source_year != requested_year:
                st.info(
                    "Using " + str(source_year) + " consensus board as fallback for requested year " + str(requested_year) + ".",
                    icon="ℹ️",
                )
            excluded = board.get("_excluded_prospects", [])
            if excluded:
                st.caption(
                    "Excluded known non-eligible names for "
                    + str(requested_year or board_year)
                    + ": " + ", ".join(excluded[:5])
                    + (" ..." if len(excluded) > 5 else "")
                )
            overrides = board.get("_overrides_applied", [])
            if overrides:
                st.caption(
                    "Applied board corrections for "
                    + str(requested_year or board_year)
                    + ": " + ", ".join(overrides[:3])
                    + (" ..." if len(overrides) > 3 else "")
                )
            _render_remediation_messages(board, requested_year or board_year)
            _render_validation_messages(board, requested_year or board_year)
            st.caption("Last updated: " + board.get("last_updated", "Unknown") + " | Sources: " + ", ".join(board.get("sources", [])))

            # Apply transaction wire status to board (for display)
            apply_transaction_wire_to_board(board, board_year)

            # Filters row
            f_c1, f_c2, f_c3 = st.columns([2, 2, 3])
            with f_c1:
                all_tiers = sorted(set(p.get("tier", 0) for p in board["prospects"]))
                selected_tiers = st.multiselect("Filter by Tier", all_tiers, default=all_tiers, key="tier_filter")
            with f_c2:
                all_pos = sorted(set(p.get("position", "") for p in board["prospects"]))
                sel_pos = st.multiselect("Filter by Position", all_pos, default=all_pos, key="board_pos_filter")
            with f_c3:
                hide_ineligible = st.checkbox("Hide withdrawn / ineligible", value=True, key="hide_ineligible")

            filtered = [p for p in board["prospects"]
                        if p.get("tier") in selected_tiers
                        and p.get("position") in sel_pos]
            if hide_ineligible:
                filtered = [p for p in filtered
                            if p.get("eligibility", {}).get("status", "declared") == "declared"]
            filtered = [
                p for p in filtered
                if _matches_query(
                    search_query,
                    p.get("name", ""),
                    p.get("position", ""),
                    p.get("school", ""),
                    p.get("consensus_rank", ""),
                )
            ]
            st.markdown(_result_count_badge("Prospects shown", len(filtered)), unsafe_allow_html=True)

            if not filtered:
                st.info("No prospects match the current search/filters.")

            for p in filtered:
                tier_label = "Tier " + str(p.get("tier", "?"))
                meas = p.get("measurables", {})
                meas_parts = []
                if meas.get("height"):
                    meas_parts.append(str(meas["height"]))
                if meas.get("weight"):
                    meas_parts.append(str(meas["weight"]) + " lbs")
                if meas.get("forty"):
                    meas_parts.append(str(meas["forty"]) + "s 40")
                if meas.get("arm_length"):
                    meas_parts.append(str(meas["arm_length"]) + "\" arm")
                meas_str = " | ".join(meas_parts) if meas_parts else "—"

                grade_val = p.get("grade", 0)
                grade_color = ACCENT_GRN if grade_val >= 90 else (ACCENT_BLUE if grade_val >= 85 else (WARNING_TX if grade_val >= 80 else TEXT_SEC))

                # Inline signal badges
                elig_status = p.get("eligibility", {}).get("status", "declared")
                elig_html = _eligibility_badge(elig_status) if elig_status != "declared" else ""
                vel_html = _velocity_badge(p.get("board_velocity", {}))
                inj_html = _injury_flag_badge() if p.get("injury_history", {}).get("flag") else ""

                # Source confidence indicator
                src_conf = compute_source_confidence(p.get("source_ranks", {}))
                src_html = ""
                if src_conf < 0.85:
                    src_html = (
                        "<span style='color:#fbbf24;font-size:0.68rem;background:#fbbf2415;"
                        "padding:1px 5px;border-radius:4px;'>~" + str(int(src_conf * 100)) + "% consensus</span>"
                    )

                signals_row = " ".join(x for x in [elig_html, vel_html, inj_html, src_html] if x)
                signals_html = (
                    "<div style='display:flex;gap:5px;flex-wrap:wrap;margin-top:3px;'>" + signals_row + "</div>"
                    if signals_row else ""
                )

                st.markdown(
                    "<div style='padding:8px 12px;background:" + CARD_BG + ";border:1px solid " + BORDER + ";"
                    "border-radius:" + str(UI_RADIUS_SM) + "px;margin-bottom:3px;'>"
                    "<div style='display:flex;align-items:center;gap:10px;'>"
                    "<span style='color:" + TEXT_SEC + ";font-weight:700;font-family:" + _MONO_FONT + ";"
                    "font-size:0.85rem;min-width:28px;'>#" + str(p["consensus_rank"]) + "</span>"
                    + _pos_badge(p["position"])
                    + "<span style='font-weight:800;font-size:1rem;min-width:160px;'>" + html.escape(p["name"]) + "</span>"
                    "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;min-width:90px;'>"
                    + html.escape(p.get("school", "")) + "</span>"
                    "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;min-width:64px;'>"
                    + tier_label + "</span>"
                    "<span style='color:" + grade_color + ";font-weight:700;font-family:" + _MONO_FONT + ";"
                    "font-size:0.85rem;min-width:36px;'>" + str(grade_val) + "</span>"
                    "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;margin-left:auto;'>"
                    + html.escape(meas_str) + "</span>"
                    "</div>"
                    + signals_html
                    + "</div>",
                    unsafe_allow_html=True,
                )

    # --- Transaction Wire (hidden; tab removed) ---
    if False:
        wire_ctrl_1, wire_ctrl_2 = st.columns([2, 1])
        with wire_ctrl_1:
            wire_year = st.number_input("Draft Year", min_value=2020, max_value=2030, value=int(board_year), key="wire_year_input")
            espn_mock_url = st.text_input(
                "ESPN Mock URL",
                value="https://www.espn.com/nfl/draft2026/story/_/id/48299038/2026-nfl-mock-draft-seven-rounds-257-picks-projections-matt-miller",
                key="espn_mock_url_input",
                help="Optional: paste any ESPN 2026 mock article URL to merge rankings into the consensus board.",
            )
        with wire_ctrl_2:
            st.markdown("<div style='height:26px;'></div>", unsafe_allow_html=True)
            if st.button("Run Ingestion Now", width="stretch", key="wire_ingest_now", help="Pull NFL/team/media updates into the transaction wire"):
                try:
                    from ingest.run_ingest import run_ingestion
                    result = run_ingestion(year=int(wire_year), source_group="all", dry_run=False)
                    st.success(
                        "Ingestion complete: "
                        + str(result.get("num_events_discovered", 0))
                        + " new events scanned across "
                        + str(result.get("num_sources_attempted", 0))
                        + " sources."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error("Ingestion failed: " + str(exc))
            if st.button("Merge ESPN Mock", width="stretch", key="wire_merge_espn", help="Merge ESPN mock draft picks into the current consensus board file"):
                try:
                    from ingest.merge_espn_mock import run_merge
                    merge_result = run_merge(year=int(wire_year), url=espn_mock_url.strip(), dry_run=False, add_missing=True)
                    merge_meta = merge_result.get("merge", {})
                    st.success(
                        "Merged ESPN mock: "
                        + str(merge_result.get("num_picks_parsed", 0))
                        + " picks parsed, "
                        + str(merge_meta.get("num_matched_existing", 0))
                        + " matched, "
                        + str(merge_meta.get("num_added_new", 0))
                        + " added."
                    )
                    st.rerun()
                except Exception as exc:
                    st.error("ESPN merge failed: " + str(exc))

        wire_summary = _cached_transaction_wire(int(wire_year))
        if not any(wire_summary.values()):
            st.info("No transaction wire data found for " + str(wire_year) + ". Add `pro/data/transaction_wire_" + str(wire_year) + ".json` to populate.")
        else:
            declared = wire_summary.get("declared", [])
            withdrew = wire_summary.get("withdrew", [])
            medical = wire_summary.get("medical_retirement", [])
            transferred = wire_summary.get("transferred", [])

            w_c1, w_c2, w_c3, w_c4 = st.columns(4)
            with w_c1:
                st.markdown(_stat_card("Declared", str(len(declared)), ACCENT_GRN), unsafe_allow_html=True)
            with w_c2:
                st.markdown(_stat_card("Withdrew", str(len(withdrew)), WARNING_TX), unsafe_allow_html=True)
            with w_c3:
                st.markdown(_stat_card("Medical", str(len(medical)), ACCENT_RED), unsafe_allow_html=True)
            with w_c4:
                st.markdown(_stat_card("Transferred", str(len(transferred)), ACCENT_BLUE), unsafe_allow_html=True)

            st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

            wire_tabs = st.tabs(["Withdrew / Ineligible", "All Declared", "Transferred"])

            with wire_tabs[0]:
                st.caption("Players who have withdrawn declarations, are not yet eligible, or announced medical retirement. These should be removed from draft boards.")
                all_removed = [
                    e for e in (withdrew + medical)
                    if _matches_query(search_query, e.get("name", ""), e.get("school", ""), e.get("position", ""), e.get("notes", ""))
                ]
                st.markdown(_result_count_badge("Withdrew/Ineligible", len(all_removed)), unsafe_allow_html=True)
                if not all_removed:
                    st.info("No withdrawal or medical entries for this year.")
                else:
                    for e in all_removed:
                        status = e.get("status", "")
                        icon, color = ELIGIBILITY_ICONS.get(status, ("?", "#94a3b8"))
                        border_color = color
                        st.markdown(
                            "<div style='background:" + CARD_BG + ";border-left:3px solid " + border_color + ";"
                            "border:1px solid " + BORDER + ";border-left:3px solid " + border_color + ";"
                            "border-radius:" + str(UI_RADIUS_SM) + "px;padding:10px 14px;margin-bottom:4px;'>"
                            "<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;'>"
                            + _pos_badge(e.get("position", "?"))
                            + "<span style='font-weight:800;font-size:1rem;'>" + html.escape(e.get("name", "")) + "</span>"
                            "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;'>"
                            + html.escape(e.get("school", "")) + "</span>"
                            + _eligibility_badge(status)
                            + "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;margin-left:auto;'>"
                            + html.escape(e.get("date", "")) + "</span>"
                            "</div>"
                            "<div style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;margin-top:4px;'>"
                            + html.escape(e.get("notes", ""))
                            + "</div></div>",
                            unsafe_allow_html=True,
                        )

            with wire_tabs[1]:
                st.caption("Players who have officially declared for the " + str(wire_year) + " NFL Draft.")
                declared_filtered = [
                    e for e in declared
                    if _matches_query(search_query, e.get("name", ""), e.get("school", ""), e.get("position", ""), e.get("notes", ""))
                ]
                st.markdown(_result_count_badge("Declared", len(declared_filtered)), unsafe_allow_html=True)
                if not declared_filtered:
                    st.info("No declarations recorded yet.")
                else:
                    for e in declared_filtered:
                        st.markdown(
                            "<div style='display:flex;align-items:center;gap:10px;padding:6px 10px;"
                            "background:" + CARD_BG + ";border:1px solid " + BORDER + ";"
                            "border-radius:" + str(UI_RADIUS_SM) + "px;margin-bottom:2px;'>"
                            + _pos_badge(e.get("position", "?"))
                            + "<span style='font-weight:700;min-width:180px;'>" + html.escape(e.get("name", "")) + "</span>"
                            "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;min-width:120px;'>"
                            + html.escape(e.get("school", "")) + "</span>"
                            + _eligibility_badge("declared")
                            + "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;margin-left:auto;'>"
                            + html.escape(e.get("date", "")) + "</span>"
                            "</div>",
                            unsafe_allow_html=True,
                        )

            with wire_tabs[2]:
                st.caption("Transfer portal activity relevant to draft eligibility.")
                transferred_filtered = [
                    e for e in transferred
                    if _matches_query(search_query, e.get("name", ""), e.get("school", ""), e.get("position", ""), e.get("notes", ""))
                ]
                st.markdown(_result_count_badge("Transferred", len(transferred_filtered)), unsafe_allow_html=True)
                if not transferred_filtered:
                    st.info("No transfer entries for this year.")
                else:
                    for e in transferred_filtered:
                        st.markdown(
                            "<div style='background:" + CARD_BG + ";border:1px solid " + BORDER + ";"
                            "border-radius:" + str(UI_RADIUS_SM) + "px;padding:10px 14px;margin-bottom:4px;'>"
                            "<div style='display:flex;align-items:center;gap:10px;flex-wrap:wrap;'>"
                            + _pos_badge(e.get("position", "?"))
                            + "<span style='font-weight:800;'>" + html.escape(e.get("name", "")) + "</span>"
                            "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;'>"
                            + html.escape(e.get("school", "")) + "</span>"
                            + _eligibility_badge("transferred")
                            + "</div>"
                            "<div style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;margin-top:4px;'>"
                            + html.escape(e.get("notes", ""))
                            + "</div></div>",
                            unsafe_allow_html=True,
                        )

    # --- Prospect Intelligence ---
    with tabs[1]:
        intel_year = board_year
        intel_board = load_consensus_board(intel_year)
        if intel_board is None:
            st.warning("No board data for selected year.")
        else:
            apply_transaction_wire_to_board(intel_board, intel_year)
            _eyebrow("Combine & Athletic Data")
            st.caption("Combine / Pro Day verified testing — 40-yard dash, jumps, agility, size, arm length, hand size. Scores are position-adjusted z-scores vs. NFL starter baselines.")

            combine_rows = []
            for p in intel_board.get("prospects", []):
                if not _matches_query(search_query, p.get("name", ""), p.get("position", ""), p.get("school", "")):
                    continue
                meas = p.get("measurables", {})
                if not meas:
                    continue
                ath_score = compute_combine_score(meas, p.get("position", ""))
                if ath_score == 0.0 and not any(v for v in meas.values() if v is not None):
                    continue
                combine_rows.append({
                    "Rank": p["consensus_rank"],
                    "Name": p["name"],
                    "Pos": p["position"],
                    "School": p.get("school", ""),
                    "Ht": str(meas.get("height", "—")),
                    "Wt": str(meas.get("weight", "—")),
                    "40yd": str(meas.get("forty", "—")),
                    "10-split": str(meas.get("ten_split", "—")),
                    "Vert": str(meas.get("vertical", "—")),
                    "Broad": str(meas.get("broad_jump", "—")),
                    "3-cone": str(meas.get("three_cone", "—")),
                    "Shuttle": str(meas.get("short_shuttle", "—")),
                    "Arm\"": str(meas.get("arm_length", "—")),
                    "Hand\"": str(meas.get("hand_size", "—")),
                    "Ath Score": round(ath_score, 3),
                })

            if combine_rows:
                df_combine = pd.DataFrame(combine_rows)
                st.markdown(_result_count_badge("Combine rows", len(df_combine)), unsafe_allow_html=True)
                st.dataframe(df_combine, width="stretch", hide_index=True)
            else:
                st.info("No combine / Pro Day data on file yet for this board year. Data populates automatically once the combine runs (~late February).")

            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
            _eyebrow("CFB Production Stats")
            st.caption("Snap counts, usage share, efficiency metrics — adds real signal behind ranking vs. pure narrative.")

            cfb_rows = []
            for p in intel_board.get("prospects", []):
                if not _matches_query(search_query, p.get("name", ""), p.get("position", ""), p.get("school", "")):
                    continue
                cfb = p.get("cfb_stats", {})
                if not cfb:
                    continue
                prod_score = compute_cfb_production_score(cfb, p.get("position", ""))
                row = {
                    "Rank": p["consensus_rank"],
                    "Name": p["name"],
                    "Pos": p["position"],
                    "Prod Score": round(prod_score, 3),
                }
                row.update({k: v for k, v in cfb.items() if not k.startswith("_")})
                cfb_rows.append(row)

            if cfb_rows:
                df_cfb = pd.DataFrame(cfb_rows)
                st.markdown(_result_count_badge("CFB rows", len(df_cfb)), unsafe_allow_html=True)
                st.dataframe(df_cfb, width="stretch", hide_index=True)
            else:
                st.info("No CFB production stats on file yet. Stats populate after the college season ends and PFF / cfbfastR data is ingested.")

            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
            _eyebrow("Big Board Velocity (Rank Movement)")
            st.caption("Weekly rank change per player. Rising = durable consensus building. Falling / unstable = hype or concern.")

            vel_rows = []
            for p in intel_board.get("prospects", []):
                if not _matches_query(search_query, p.get("name", ""), p.get("position", ""), p.get("school", "")):
                    continue
                bv = p.get("board_velocity", {})
                if not bv:
                    continue
                weekly = bv.get("weekly_change", 0)
                stability = bv.get("stability", "—")
                peak = bv.get("peak_rank", "—")
                vel_rows.append({
                    "Rank": p["consensus_rank"],
                    "Name": p["name"],
                    "Pos": p["position"],
                    "Weekly Δ": weekly,
                    "Stability": stability,
                    "Peak Rank": peak,
                })

            if vel_rows:
                df_vel = pd.DataFrame(vel_rows)
                df_vel = df_vel.sort_values("Weekly Δ", ascending=False)
                st.markdown(_result_count_badge("Velocity rows", len(df_vel)), unsafe_allow_html=True)
                st.dataframe(df_vel, width="stretch", hide_index=True)
            else:
                st.info("No board velocity data yet. This updates weekly as consensus board scrapes are run.")

            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
            _eyebrow("Recruiting Pedigree & Age Model")
            st.caption("247Sports / On3 stars, composite rating, breakout age, and age at draft. Upside vs. readiness context.")

            rec_rows = []
            for p in intel_board.get("prospects", []):
                if not _matches_query(search_query, p.get("name", ""), p.get("position", ""), p.get("school", "")):
                    continue
                rec = p.get("recruiting", {})
                if not rec:
                    continue
                rec_sig = compute_recruiting_signal(rec)
                rec_rows.append({
                    "Rank": p["consensus_rank"],
                    "Name": p["name"],
                    "Pos": p["position"],
                    "Stars 247": rec.get("stars_247", "—"),
                    "Stars On3": rec.get("stars_on3", "—"),
                    "Composite": rec.get("composite_rating", "—"),
                    "Breakout Age": rec.get("breakout_age", "—"),
                    "Age at Draft": rec.get("age_at_draft", "—"),
                    "Upside Signal": round(rec_sig, 3),
                })

            if rec_rows:
                df_rec = pd.DataFrame(rec_rows)
                st.markdown(_result_count_badge("Recruiting rows", len(df_rec)), unsafe_allow_html=True)
                st.dataframe(df_rec, width="stretch", hide_index=True)
            else:
                st.info("No recruiting pedigree data on file yet.")

            st.markdown("<div style='height:20px;'></div>", unsafe_allow_html=True)
            _eyebrow("Injury History & Availability")
            st.caption("Public injury reports, games missed, availability percentage over last 2 seasons. High-risk flags downgrade bust probability.")

            inj_rows = []
            for p in intel_board.get("prospects", []):
                if not _matches_query(search_query, p.get("name", ""), p.get("position", ""), p.get("school", "")):
                    continue
                inj = p.get("injury_history", {})
                if not inj:
                    continue
                penalty = compute_injury_risk_penalty(inj)
                inj_rows.append({
                    "Rank": p["consensus_rank"],
                    "Name": p["name"],
                    "Pos": p["position"],
                    "Flag": "🩺 Yes" if inj.get("flag") else "No",
                    "Risk Level": inj.get("risk_level", "—"),
                    "Availability %": str(int(float(inj.get("availability_pct", 1.0)) * 100)) + "%"
                        if inj.get("availability_pct") is not None else "—",
                    "Grade Penalty": round(penalty, 3),
                    "Details": "; ".join(
                        d.get("type", "") + " " + str(d.get("year", ""))
                        for d in inj.get("details", [])
                    ) or "—",
                })

            if inj_rows:
                df_inj = pd.DataFrame(inj_rows)
                st.markdown(_result_count_badge("Injury rows", len(df_inj)), unsafe_allow_html=True)
                st.dataframe(df_inj, width="stretch", hide_index=True)
            else:
                st.info("No injury history data on file yet.")

    # --- Positional Value ---
    with tabs[2]:
        pos_values = load_position_values()
        multipliers = pos_values.get("positional_value_multiplier", {})

        _eyebrow("Positional Value Multipliers")
        st.caption("How much draft capital each position is worth relative to average. >1.0 = premium position.")

        numeric_multipliers = []
        for pos, raw_mult in multipliers.items():
            try:
                mult = float(raw_mult)
            except (TypeError, ValueError):
                continue
            numeric_multipliers.append((pos, mult))

        sorted_positions = sorted(numeric_multipliers, key=lambda x: x[1], reverse=True)
        for pos, mult in sorted_positions:
            bar_width = max(0, min(100, int(mult / 1.6 * 100)))
            bar_color = ACCENT_GRN if mult >= 1.1 else (ACCENT_BLUE if mult >= 0.9 else (WARNING_TX if mult >= 0.7 else ACCENT_RED))
            label = pos_values.get("position_labels", {}).get(pos, pos)
            st.markdown(
                "<div style='display:flex;align-items:center;gap:10px;margin-bottom:6px;'>"
                "<span style='min-width:40px;font-weight:700;font-size:0.85rem;'>" + _pos_badge(pos) + "</span>"
                "<span style='min-width:140px;color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_SM) + "rem;'>"
                + html.escape(label) + "</span>"
                "<div style='flex:1;background:" + STAT_BG + ";border-radius:4px;height:20px;overflow:hidden;'>"
                "<div style='width:" + str(bar_width) + "%;background:" + bar_color + ";height:100%;"
                "border-radius:4px;transition:width 0.3s;'></div></div>"
                "<span style='font-weight:800;font-family:" + _MONO_FONT + ";font-size:0.9rem;min-width:40px;"
                "text-align:right;color:" + bar_color + ";'>" + str(round(mult, 2)) + "x</span>"
                "</div>",
                unsafe_allow_html=True,
            )
        if not sorted_positions:
            st.info("No numeric positional multipliers available in the loaded dataset.", icon="ℹ️")

    # --- Trade Value Chart ---
    with tabs[3]:
        _eyebrow("Draft Pick Trade Value Chart")
        st.caption("Compare pick values and calculate trade fairness.")

        tv_c1, tv_c2 = st.columns(2)
        trade_chart = load_trade_value_chart()
        with tv_c1:
            pick_a = st.number_input("Pick A", min_value=1, max_value=257, value=1, key="tv_pick_a")
            val_a = get_pick_value(pick_a, trade_chart)
            st.markdown(_stat_card("Value", str(val_a), ACCENT_GRN), unsafe_allow_html=True)
        with tv_c2:
            pick_b = st.number_input("Pick B", min_value=1, max_value=257, value=32, key="tv_pick_b")
            val_b = get_pick_value(pick_b, trade_chart)
            st.markdown(_stat_card("Value", str(val_b), ACCENT_BLUE), unsafe_allow_html=True)

        diff = val_a - val_b
        diff_color = SUCCESS_TX if diff > 0 else DANGER_TX
        st.markdown(
            "<div style='text-align:center;margin:" + str(UI_SPACE_4) + "px 0;'>"
            "<span style='color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_SM) + "rem;'>Difference: </span>"
            "<span style='color:" + diff_color + ";font-size:1.3rem;font-weight:800;font-family:" + _MONO_FONT + ";'>"
            + ("+" if diff > 0 else "") + str(diff) + " pts</span>"
            "</div>",
            unsafe_allow_html=True,
        )

        # Value curve visualization
        with st.expander("Full Value Curve (Picks 1-100)"):
            curve_data = []
            for p in range(1, 101):
                curve_data.append({"Pick": p, "Value": get_pick_value(p, trade_chart)})
            chart_df = pd.DataFrame(curve_data).set_index("Pick")
            st.area_chart(chart_df, color="#10b981")

    # --- Hit Rates ---
    with tabs[4]:
        _eyebrow("Historical Hit Rates by Position & Round")
        st.caption("% of draft picks at each position that became quality starters, based on 2000-2022 data.")

        hit_summary = get_position_hit_rate_summary()
        pos_values = load_position_values()
        hit_rates = pos_values.get("historical_hit_rate_by_round", {})

        # Build a table
        rows = []
        for pos in NFL_POSITIONS:
            if pos not in hit_rates:
                continue
            pos_rounds = hit_rates.get(pos, {})
            if not isinstance(pos_rounds, dict):
                continue
            row = {"Position": pos}
            for rnd in range(1, 8):
                raw_rate = pos_rounds.get(str(rnd), 0)
                try:
                    rate = float(raw_rate)
                except (TypeError, ValueError):
                    rate = 0.0
                row["Rd " + str(rnd)] = str(int(rate * 100)) + "%"
            summary = hit_summary.get(pos, {})
            row["Avg"] = str(int(summary.get("avg_hit_rate", 0) * 100)) + "%"
            rows.append(row)

        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, width="stretch", hide_index=True)

        st.markdown("<div style='height:" + str(UI_SPACE_4) + "px;'></div>", unsafe_allow_html=True)
        st.caption("Hit rate = became a quality NFL starter (3+ years as starter or Pro Bowl caliber). "
                   "Higher hit rates at a position/round mean more reliable investment.")
