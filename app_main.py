import streamlit as st
import pandas as pd
import copy
import json
import math
import html
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import certifi
import io

from draft_engine import (
    FANTASY_POSITIONS, FLEX_ELIGIBLE, SFLEX_ELIGIBLE,
    ROSTER_PRESETS, VOR_BASELINE, GRADE_VALUES,
    BYE_WEEKS, SOS_TIERS, SOS_COLORS,
    REC_PPR_PREMIUM_EST,
    roster_total_slots, ordinal, utc_timestamp, norm_name,
    validate_player_pool, load_player_pool_from_file, save_player_pool_to_file,
    effective_fantasy_ppg, effective_vor_baseline, ppg_title_for_scoring_key,
    grade_player_adp, get_positional_needs, get_positional_scarcity,
    get_bye_week_conflicts, get_roster_bye_analysis,
    get_top_recommendations, simulate_opponent_pick,
    init_draft_state, advance_to_user_pick, make_user_pick, make_auto_pick,
    save_undo_snapshot, restore_undo_snapshot,
    picks_until_next_turn, get_players_likely_gone,
    compute_draft_recap,
    save_draft_result, load_draft_results, get_draft_trends,
    merge_sleeper_metadata, build_sleeper_name,
    PLAYER_POOL_FALLBACK_PATH, DEFAULT_PLAYERS_PATH,
)

# ---------------------------------------------------------------------------
# THEME PALETTES
# ---------------------------------------------------------------------------
THEMES = {
    "dark": {
        "BG": "#0a0a0f", "PANEL_BG": "#111116", "TEXT_PRI": "#f2f2f8",
        "TEXT_SEC": "#a0a8be", "GRID_LINE": "#1e1e2a", "BORDER": "#1e1e2a",
        "APP_BG": "#0a0a0f", "HDR_BG1": "#0e1a0e", "HDR_BG2": "#0a0a0f",
        "CARD_BG": "#111116", "STAT_BG": "#161620", "CARD_HOVER": "#18181f",
        "SURFACE": "#1a1a24",
    },
    "light": {
        "BG": "#f3f4f6", "PANEL_BG": "#ffffff", "TEXT_PRI": "#111827",
        "TEXT_SEC": "#4b5563", "GRID_LINE": "#e5e7eb", "BORDER": "#d1d5db",
        "APP_BG": "#f3f4f6", "HDR_BG1": "#ecfdf5", "HDR_BG2": "#f3f4f6",
        "CARD_BG": "#ffffff", "STAT_BG": "#f9fafb", "CARD_HOVER": "#f3f4f6",
        "SURFACE": "#f0f1f3",
    },
}

ACCENT_GOLD = "#facc15"
ACCENT_GRN  = "#10b981"
ACCENT_RED  = "#ef4444"
ACCENT_BLUE = "#3b82f6"

POS_COLORS = {"QB": "#a78bfa", "RB": "#34d399", "WR": "#60a5fa", "TE": "#fb923c", "K": "#f472b6", "DEF": "#f87171"}
POS_COLORS_BG = {
    "QB": "rgba(167,139,250,0.12)", "RB": "rgba(52,211,153,0.12)",
    "WR": "rgba(96,165,250,0.12)",  "TE": "rgba(251,146,60,0.12)",
    "K": "rgba(244,114,182,0.12)",  "DEF": "rgba(248,113,113,0.12)",
}

GRADE_COLORS = {
    "A+": "#10b981", "A": "#10b981", "A-": "#34d399",
    "B+": "#86efac", "B": "#86efac", "B-": "#bef264",
    "C+": "#facc15", "C": "#facc15", "C-": "#fbbf24",
    "D+": "#fb923c", "D": "#fb923c", "F": "#ef4444", "N/A": "#6b7280",
}
GRADE_COLORS_BG = {
    "A+": "rgba(16,185,129,0.15)", "A": "rgba(16,185,129,0.15)", "A-": "rgba(52,211,153,0.12)",
    "B+": "rgba(134,239,172,0.12)", "B": "rgba(134,239,172,0.12)", "B-": "rgba(190,242,100,0.10)",
    "C+": "rgba(250,204,21,0.12)", "C": "rgba(250,204,21,0.12)", "C-": "rgba(251,191,36,0.10)",
    "D+": "rgba(251,146,60,0.12)", "D": "rgba(251,146,60,0.12)",
    "F": "rgba(239,68,68,0.15)", "N/A": "rgba(107,114,128,0.10)",
}

# ---------------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="DRAFTi \u2014 Fantasy Draft Simulator",
    page_icon="\U0001f3c8",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# SESSION STATE INIT
# ---------------------------------------------------------------------------
_defaults = {
    "theme": "dark",
    "draft_state": None,
    "draft_history": [],
    "draft_started": False,
    "current_recs": [],
    "last_pick_result": None,
    "undo_stack": [],
    "league_num_teams": 12,
    "league_draft_format": "Snake",
    "league_scoring": "PPR",
    "league_user_slot": 1,
    "league_roster_preset": "Standard",
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------------------------
# ACTIVE THEME
# ---------------------------------------------------------------------------
_T = THEMES[st.session_state.theme]
BG       = _T["BG"];       PANEL_BG  = _T["PANEL_BG"]
TEXT_PRI  = _T["TEXT_PRI"]; TEXT_SEC  = _T["TEXT_SEC"]
GRID_LINE = _T["GRID_LINE"]; BORDER = _T["BORDER"]
HDR_BG1  = _T["HDR_BG1"];  HDR_BG2  = _T["HDR_BG2"]
CARD_BG  = _T["CARD_BG"];  STAT_BG  = _T["STAT_BG"]
CARD_HOVER = _T["CARD_HOVER"]; SURFACE = _T["SURFACE"]
IS_DARK_THEME = st.session_state.theme == "dark"

# Theme-aware accent text colors (small-label WCAG readability)
SUCCESS_TX = "#34d399" if IS_DARK_THEME else "#047857"
WARNING_TX = "#fbbf24" if IS_DARK_THEME else "#92400e"
INFO_TX = "#93c5fd" if IS_DARK_THEME else "#1d4ed8"
DANGER_TX = "#f87171" if IS_DARK_THEME else "#b91c1c"

# ---------------------------------------------------------------------------
# UI SCALE TOKENS (spacing / radius / typography rhythm)
# ---------------------------------------------------------------------------
UI_SPACE_1 = 4
UI_SPACE_2 = 8
UI_SPACE_3 = 12
UI_SPACE_4 = 16
UI_SPACE_5 = 24
UI_SPACE_6 = 32

UI_RADIUS_SM = 8
UI_RADIUS_MD = 12
UI_RADIUS_LG = 14

UI_TEXT_XS = 0.68
UI_TEXT_SM = 0.78
UI_TEXT_MD = 0.90
UI_TEXT_H3 = 1.50
UI_TEXT_2XS = 0.62
UI_TEXT_LABEL = 0.68

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
_btn_bg    = "#2e2e3a" if st.session_state.theme == "dark" else "#e8e8f0"
_btn_hover = "#3a3a4a" if st.session_state.theme == "dark" else "#d8d8e8"
_light_surface_text = "#111827"
_SYS_FONT  = "system-ui,sans-serif"
_MONO_FONT = "SFMono-Regular,Consolas,monospace"
st.markdown(f"""<style>
*{{font-family:{_SYS_FONT}}}
.stApp{{background:{BG};color:{TEXT_PRI}}}
.block-container{{padding-top:{UI_SPACE_3}px;padding-bottom:{UI_SPACE_4}px;max-width:1400px}}
h1,h2,h3,h4{{color:{TEXT_PRI};font-weight:800;letter-spacing:-.02em}}
h4,h5,h6{{text-transform:uppercase;letter-spacing:.08em;font-size:.75rem;color:{TEXT_SEC}}}
p,li,span{{color:{TEXT_PRI};line-height:1.45}}
div[data-testid="stMetricValue"]{{color:{TEXT_PRI};font-size:1.6rem;font-weight:800;font-variant-numeric:tabular-nums}}
div[data-testid="stMetricLabel"]{{color:{TEXT_SEC};font-size:{UI_TEXT_LABEL}rem;text-transform:uppercase;letter-spacing:.095em;font-weight:700}}
div[data-testid="stCaptionContainer"] p{{color:{TEXT_SEC};font-size:{UI_TEXT_XS}rem;letter-spacing:.01em;line-height:1.40}}
div[data-testid="stAlert"] p{{line-height:1.45}}
.stSelectbox label,.stTextInput label,.stSlider label{{color:{TEXT_SEC};font-size:.78rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
.stButton>button{{background:{_btn_bg};color:{TEXT_PRI};border:1px solid {BORDER};border-radius:{UI_RADIUS_SM}px;font-weight:600;transition:all .15s}}
.stButton>button:hover{{background:{_btn_hover};border-color:{ACCENT_GRN};color:{ACCENT_GRN}}}
.stButton>button:focus-visible,.stDownloadButton>button:focus-visible{{outline:2px solid {ACCENT_GRN};outline-offset:2px}}
.stButton>button:disabled,.stDownloadButton>button:disabled{{opacity:.48;cursor:not-allowed;border-color:{BORDER};color:{TEXT_SEC};background:{STAT_BG}}}
.stButton>button[kind="primary"],.stButton>button[data-testid="stBaseButton-primary"]{{background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none;font-weight:700;text-transform:uppercase;letter-spacing:.06em}}
.stButton>button[kind="primary"]:hover,.stButton>button[data-testid="stBaseButton-primary"]:hover{{background:linear-gradient(135deg,#059669,#047857);color:#fff}}
.stDownloadButton>button{{background:{_btn_bg};color:{TEXT_PRI};border:1px solid {BORDER};border-radius:{UI_RADIUS_SM}px;font-weight:600}}
.stDownloadButton>button:hover{{background:{_btn_hover};border-color:{ACCENT_GRN};color:{ACCENT_GRN}}}
.stTabs [data-baseweb="tab-list"]{{border-bottom:1px solid {BORDER}}}
.stTabs [data-baseweb="tab"]{{color:{TEXT_SEC};font-weight:600;text-transform:uppercase;letter-spacing:.06em}}
.stTabs [aria-selected="true"]{{color:{ACCENT_GRN}!important;border-bottom:2px solid {ACCENT_GRN}!important}}
div[data-testid="stDataFrame"]{{background:{PANEL_BG};border-radius:{UI_RADIUS_SM}px;border:1px solid {BORDER}}}
hr{{border-color:{BORDER};opacity:.5}}
code,.stCode{{font-family:{_MONO_FONT};font-variant-numeric:tabular-nums}}
::-webkit-scrollbar{{width:6px}}
::-webkit-scrollbar-thumb{{background:{BORDER};border-radius:3px}}
#MainMenu,footer,header{{visibility:hidden}}
.drafti-step{{opacity:.92}}
div[data-testid="stExpander"] details summary{{font-weight:600;font-size:0.9rem;border-radius:{UI_RADIUS_SM}px;transition:background .15s ease,color .15s ease}}
div[data-testid="stExpander"] details summary:hover{{background:{STAT_BG}}}
div[data-testid="stExpander"] details summary:focus-visible{{outline:2px solid {ACCENT_GRN};outline-offset:2px}}
div[data-testid="stExpander"] details summary span{{color:{TEXT_SEC}}}
div[data-testid="stPopover"] button:focus-visible{{outline:2px solid {ACCENT_GRN};outline-offset:2px}}
/* Keep modal/popover actions readable in dark mode */
div[data-testid="stPopoverContent"] .stButton>button,
div[data-testid="stModal"] .stButton>button{{background:{_btn_bg};color:{TEXT_PRI};border:1px solid {BORDER}}}
div[data-testid="stPopoverContent"] .stButton>button:hover,
div[data-testid="stModal"] .stButton>button:hover{{background:{_btn_hover};color:{TEXT_PRI};border-color:{ACCENT_GRN}}}
div[data-testid="stPopoverContent"] .stButton>button[kind="primary"],
div[data-testid="stModal"] .stButton>button[kind="primary"]{{background:linear-gradient(135deg,#10b981,#059669);color:#fff;border:none}}
div[data-testid="stPopoverContent"] .stButton>button * ,
div[data-testid="stModal"] .stButton>button *{{color:inherit !important}}
/* Streamlit data editor / popover utility controls use non-.stButton buttons */
div[data-testid="stPopoverContent"] button,
div[data-testid="stPopoverContent"] button span,
div[data-testid="stPopoverContent"] button svg,
div[data-testid="stDataFrame"] button,
div[data-testid="stDataFrame"] button span,
div[data-testid="stDataFrame"] button svg{{
  color:{_light_surface_text} !important;
  fill:{_light_surface_text} !important;
  opacity:1 !important;
}}
</style>""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# PLAYER POOL LOADING (#10: no more inline data)
# ---------------------------------------------------------------------------
SLEEPER_PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
SLEEPER_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

if "player_pool" not in st.session_state:
    file_pool = load_player_pool_from_file(PLAYER_POOL_FALLBACK_PATH)
    if file_pool:
        st.session_state.player_pool = file_pool
        st.session_state.player_pool_source = "players.json"
        st.session_state.player_pool_status = "Loaded player pool from players.json."
    else:
        default_pool = load_player_pool_from_file(DEFAULT_PLAYERS_PATH)
        if default_pool:
            st.session_state.player_pool = default_pool
            st.session_state.player_pool_source = "default_players.json"
            st.session_state.player_pool_status = "Loaded default player pool."
        else:
            st.session_state.player_pool = []
            st.session_state.player_pool_source = "empty"
            st.session_state.player_pool_status = "No player data found."
    st.session_state.player_pool_last_updated = utc_timestamp()

DRAFT_PLAYER_POOL = copy.deepcopy(st.session_state.player_pool)


# ---------------------------------------------------------------------------
# PHOTO HELPERS
# ---------------------------------------------------------------------------
def _player_photo_url(player):
    if not isinstance(player, dict):
        return None
    team = str(player.get("team") or "").strip().upper()
    pos = str(player.get("position") or "").strip().upper()
    if pos == "DEF":
        if team and team != "FA":
            return "https://sleepercdn.com/images/team_logos/nfl/" + team.lower() + ".png"
        return None
    sleeper_id = player.get("sleeper_id")
    if not sleeper_id:
        return None
    return "https://sleepercdn.com/content/nfl/players/" + str(sleeper_id).strip() + ".jpg"


def _photo_img_html(photo_url, size_px=48, border_color="#6b7280"):
    if not photo_url:
        return ""
    safe_url = html.escape(photo_url, quote=True)
    sp = str(size_px)
    bc = html.escape(border_color, quote=True)
    return (
        "<div style=\"width:" + sp + "px;height:" + sp + "px;min-width:" + sp + "px;border-radius:10px;"
        "overflow:hidden;border:1px solid " + bc + "55;flex-shrink:0;background:rgba(0,0,0,0.12);\">"
        "<img src=\"" + safe_url + "\" alt=\"\" loading=\"lazy\" referrerpolicy=\"no-referrer\" "
        "style=\"width:100%;height:100%;object-fit:cover;display:block;\"/></div>"
    )


def _photo_url_for_player_name(name, pool=None):
    name_key = str(name or "").strip()
    if not name_key:
        return None
    player_list = pool if pool is not None else DRAFT_PLAYER_POOL
    match = next((pl for pl in player_list if pl["name"] == name_key), None)
    return _player_photo_url(match) if match else None


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------
def _draft_scoring_key():
    ds = st.session_state.get("draft_state")
    if ds and ds.get("scoring"):
        return ds["scoring"]
    return st.session_state.get("league_scoring", "PPR")


def _draft_num_teams():
    ds = st.session_state.get("draft_state")
    if ds and ds.get("num_teams"):
        return int(ds["num_teams"])
    return max(6, min(16, int(st.session_state.get("league_num_teams", 12))))


def _roster_preset():
    ds = st.session_state.get("draft_state")
    if ds and ds.get("roster_preset"):
        return ds["roster_preset"]
    return st.session_state.get("league_roster_preset", "Standard")


def _ppg_column_label():
    return ppg_title_for_scoring_key(st.session_state.get("league_scoring", "PPR"))


def _scoring_adj_label():
    return "Format vs PPR pool"


def _player_pool_json_cache_key():
    return json.dumps(st.session_state.player_pool, default=str)


def _fetch_live_player_pool(base_pool):
    request = Request(SLEEPER_PLAYERS_URL, headers={"User-Agent": "Drafti/1.0"})
    with urlopen(request, timeout=15, context=SLEEPER_SSL_CONTEXT) as response:
        sleeper_payload = json.load(response)
    return merge_sleeper_metadata(base_pool, sleeper_payload)


# ---------------------------------------------------------------------------
# CACHED DISPLAY FRAMES
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def _cached_pool_display_dataframe(players_json: str, scoring_key: str):
    pool = json.loads(players_json)
    if not pool:
        return pd.DataFrame()
    pool_df = pd.DataFrame(pool)
    pool_df.insert(0, "Photo", [_player_photo_url(pl) for pl in pool])
    pool_df["sort_adp"] = pd.to_numeric(pool_df["adp"], errors="coerce").fillna(9999.0)
    pool_df = pool_df.sort_values("sort_adp", ascending=True).drop(columns=["sort_adp"])
    pool_df["rank"] = range(1, len(pool_df) + 1)
    pool_df["ppg"] = pool_df.apply(
        lambda r: round(effective_fantasy_ppg(float(r["ppg"]), r["position"], scoring_key, r.to_dict()), 2),
        axis=1,
    )
    pool_df["bye"] = pool_df["team"].map(BYE_WEEKS).fillna("--")
    pool_df["sos"] = pool_df["team"].map(SOS_TIERS).fillna("Medium")
    pool_df = pool_df[["Photo", "rank", "name", "position", "team", "bye", "sos", "adp", "ppg"]]
    ppg_title = ppg_title_for_scoring_key(scoring_key)
    pool_df.columns = ["Photo", "Rank", "Player", "Pos", "Team", "Bye", "SOS", "ADP", ppg_title]
    return pool_df


@st.cache_data(show_spinner=False)
def _cached_sorted_player_names(players_json: str):
    pool = json.loads(players_json)
    return sorted(p["name"] for p in pool)


@st.cache_data(show_spinner=False)
def _cached_lookup_stats_tables(players_json: str, scoring_key: str, num_teams: int):
    stats_df_pool = pd.DataFrame(json.loads(players_json))
    if stats_df_pool.empty:
        return pd.DataFrame(), pd.DataFrame()
    stats_df_pool["ppg_eff"] = stats_df_pool.apply(
        lambda r: effective_fantasy_ppg(r["ppg"], r["position"], scoring_key, r.to_dict()), axis=1,
    )
    top10 = stats_df_pool[stats_df_pool["ppg_eff"] > 0].nlargest(10, "ppg_eff")[
        ["name", "position", "team", "adp", "ppg_eff"]
    ].copy()
    top10["ppg_eff"] = top10["ppg_eff"].round(2)
    top10.columns = ["Player", "Pos", "Team", "ADP", "PPG"]
    stats_df2 = stats_df_pool[stats_df_pool["ppg_eff"] > 0].copy()
    stats_df2["adp_round"] = (stats_df2["adp"] / float(num_teams)).apply(math.ceil)
    stats_df2["vor"] = stats_df2.apply(
        lambda r: r["ppg_eff"] - effective_vor_baseline(r["position"], scoring_key), axis=1,
    )
    top_vor = stats_df2.nlargest(10, "vor")[
        ["name", "position", "team", "adp", "ppg_eff", "vor"]
    ].copy()
    top_vor["ppg_eff"] = top_vor["ppg_eff"].round(2)
    top_vor["vor"] = top_vor["vor"].round(2)
    top_vor.columns = ["Player", "Pos", "Team", "ADP", "PPG", "VOR"]
    return top10, top_vor


def _empty_table_state(message: str):
    """Consistent empty-state copy for tables with no rows."""
    st.info(message, icon="📭")


def _render_section_header(title: str, subtitle: str):
    """Shared section header treatment for all major panels."""
    st.markdown(
        "<div style=\"margin-bottom:" + str(UI_SPACE_4) + "px;\">"
        "<h3 style=\"color:" + TEXT_PRI + ";font-family:system-ui;font-weight:800;font-size:" + str(UI_TEXT_H3) + "rem;"
        "letter-spacing:-0.02em;margin:0;\">" + html.escape(title) + "</h3>"
        "<p style=\"color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_SM) + "rem;line-height:1.42;margin:" + str(UI_SPACE_1) + "px 0 0;\">"
        + subtitle + "</p></div>",
        unsafe_allow_html=True,
    )


def _render_context_chips(chips):
    """Compact context chips for persistent league state visibility."""
    if not chips:
        return
    _chips_html = ""
    for label, value in chips:
        _chips_html += (
            "<span style=\"color:" + TEXT_SEC + ";font-size:" + str(UI_TEXT_XS) + "rem;font-family:system-ui;"
            "font-weight:600;text-transform:uppercase;letter-spacing:0.08em;background:" + STAT_BG + ";"
            "padding:" + str(UI_SPACE_1 - 1) + "px " + str(UI_SPACE_2) + "px;border-radius:999px;border:1px solid " + BORDER + ";\">"
            + html.escape(str(label)) + ": "
            + "<span style=\"color:" + TEXT_PRI + ";font-weight:700;\">" + html.escape(str(value)) + "</span></span>"
        )
    st.markdown(
        "<div style=\"display:flex;align-items:center;gap:" + str(UI_SPACE_1 + 2) + "px;flex-wrap:wrap;margin-bottom:" + str(UI_SPACE_3) + "px;\">" + _chips_html + "</div>",
        unsafe_allow_html=True,
    )


def _render_eyebrow(text: str, margin_bottom: int = UI_SPACE_2):
    """Uniform small uppercase heading for subsection hierarchy."""
    st.markdown(
        "<h5 style=\"color:" + TEXT_SEC + ";margin:0 0 " + str(margin_bottom) + "px;font-family:system-ui;"
        "font-weight:700;text-transform:uppercase;letter-spacing:0.10em;font-size:" + str(UI_TEXT_2XS) + "rem;\">"
        + html.escape(text) + "</h5>",
        unsafe_allow_html=True,
    )


def _render_key_findings_panel(state, roster, recs, pick_num: int):
    """Show three concrete, data-backed draft insights."""
    scoring_key = state.get("scoring", _draft_scoring_key())
    scarcity = get_positional_scarcity(state["available_players"], scoring_key)
    needs = get_positional_needs(roster, _roster_preset())
    ahead = picks_until_next_turn(state)
    likely_gone = get_players_likely_gone(state, max_show=max(6, ahead))

    # Insight 1: Positional scarcity signal
    core_pos = ("RB", "WR", "TE", "QB")
    scarce_pos = sorted(core_pos, key=lambda p: scarcity.get(p, {}).get("startable", 999))[0]
    scarce_left = scarcity.get(scarce_pos, {}).get("startable", 0)
    insight_1 = {
        "title": "Scarcity Pressure",
        "body": (
            "Pick #" + str(pick_num) + ": " + str(scarce_left) + " startable " + scarce_pos + "s remain in pool; "
            + str(ahead) + " opponent pick" + ("s" if ahead != 1 else "") + " before your next turn."
        ),
        "accent": WARNING_TX if scarce_left <= 6 else INFO_TX,
    }

    # Insight 2: Value edge from top recommendation
    if recs:
        top_rec = recs[0]
        adp_round = max(1, math.ceil(float(top_rec["adp"]) / float(max(6, _draft_num_teams()))))
        round_now = max(1, int(state.get("current_round", 1)))
        round_edge = adp_round - round_now
        next_gap = 0.0
        if len(recs) >= 2:
            next_gap = float(recs[0]["vor"]) - float(recs[1]["vor"])
        insight_2 = {
            "title": "Best Value Edge",
            "body": (
                top_rec["player"] + " grades " + top_rec["grade"]
                + " with VOR " + str(round(float(top_rec["vor"]), 2))
                + "; ADP round edge "
                + ("+" if round_edge >= 0 else "")
                + str(round_edge)
                + (" and +" + str(round(next_gap, 2)) + " VOR vs next option." if next_gap > 0 else ".")
            ),
            "accent": SUCCESS_TX,
        }
    else:
        insight_2 = {
            "title": "Best Value Edge",
            "body": "No recommendation signal available yet; make a pick to generate value deltas.",
            "accent": TEXT_SEC,
        }

    # Insight 3: Bye-week concentration risk
    bye_counts, bye_conflicts = get_roster_bye_analysis(roster)
    if bye_conflicts:
        busiest_week = max(bye_conflicts.items(), key=lambda x: len(x[1]))
        week_n = busiest_week[0]
        ct = len(busiest_week[1])
        insight_3 = {
            "title": "Bye Week Concentration",
            "body": "Week " + str(week_n) + " already holds " + str(ct) + " roster players; avoid stacking more from that bye.",
            "accent": DANGER_TX,
        }
    elif bye_counts:
        busiest_week = max(bye_counts.items(), key=lambda x: len(x[1]))
        week_n = busiest_week[0]
        ct = len(busiest_week[1])
        insight_3 = {
            "title": "Bye Week Concentration",
            "body": "Current max bye overlap is Week " + str(week_n) + " with " + str(ct) + " player" + ("s" if ct != 1 else "") + ".",
            "accent": INFO_TX,
        }
    else:
        at_risk_names = [p["name"] for p in likely_gone[:3]]
        insight_3 = {
            "title": "Board Volatility",
            "body": (
                str(len(likely_gone[:ahead])) + " likely gone before your next pick"
                + (": " + ", ".join(at_risk_names) if at_risk_names else ".")
            ),
            "accent": INFO_TX,
        }

    findings = [insight_1, insight_2, insight_3]
    _render_eyebrow("Key Findings", margin_bottom=10)
    cols = st.columns(3)
    for idx, finding in enumerate(findings):
        with cols[idx]:
            st.markdown(
                "<div style=\"background:" + CARD_BG + ";border:1px solid " + BORDER + ";"
                "border-radius:" + str(UI_RADIUS_MD) + "px;padding:" + str(UI_SPACE_4) + "px;min-height:142px;\">"
                "<div style=\"color:" + finding["accent"] + ";font-size:0.65rem;font-weight:800;"
                "text-transform:uppercase;letter-spacing:0.1em;margin-bottom:8px;\">"
                + html.escape(finding["title"]) + "</div>"
                "<div style=\"color:" + TEXT_PRI + ";font-size:" + str(UI_TEXT_SM) + "rem;line-height:1.45;\">"
                + html.escape(finding["body"]) + "</div></div>",
                unsafe_allow_html=True,
            )


def _roster_to_csv_bytes(roster, scoring_key: str) -> bytes:
    """Serialize current roster to UTF-8 CSV bytes."""
    rows = []
    for p in roster or []:
        rows.append({
            "Name": p.get("name", ""),
            "Pos": p.get("position", ""),
            "Team": p.get("team", ""),
            "ADP": p.get("adp", ""),
            "Proj PPG": round(
                effective_fantasy_ppg(
                    float(p.get("ppg", 0)), p.get("position", ""), scoring_key, p,
                ),
                2,
            ),
        })
    df = pd.DataFrame(rows, columns=["Name", "Pos", "Team", "ADP", "Proj PPG"])
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


def _history_to_csv_bytes(draft_history) -> bytes:
    """Serialize pick history to UTF-8 CSV bytes."""
    if not draft_history:
        buf = io.StringIO()
        pd.DataFrame(
            columns=["Round", "Pick", "Player", "Pos", "Team", "ADP", "PPG", "Grade"],
        ).to_csv(buf, index=False)
        return buf.getvalue().encode("utf-8")
    df = pd.DataFrame(draft_history)
    df = df.rename(columns={
        "round": "Round", "pick": "Pick", "player": "Player",
        "position": "Pos", "team": "Team", "adp": "ADP", "ppg": "PPG", "grade": "Grade",
    })
    order = ["Round", "Pick", "Player", "Pos", "Team", "ADP", "PPG", "Grade"]
    df = df[[c for c in order if c in df.columns]]
    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# POOL BROWSER FRAGMENT
# ---------------------------------------------------------------------------
@st.fragment
def _render_pool_browser_fragment():
    _pool_sk = st.session_state.get("league_scoring", "PPR")
    _ppg_col = ppg_title_for_scoring_key(_pool_sk)
    pool_df = _cached_pool_display_dataframe(_player_pool_json_cache_key(), _pool_sk)
    if pool_df.empty:
        st.warning("No players in pool.")
        return

    with st.expander("How PPG & scoring work", expanded=False):
        st.markdown(
            "- **Headshots**: Sleeper CDN when `sleeper_id` is set; **DEF** uses NFL team logos.\n"
            "- **PPG**: Converted from PPR-shaped projections using per-game **`rec`** / **`targets`** when present, else position heuristics.\n"
            "- **Bye**: NFL bye week for the 2025 season.\n"
            "- **SOS**: Simplified strength-of-schedule tier (Easy/Medium/Hard) based on opponent defense quality."
        )

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        pos_filter = st.multiselect("Filter by Position", options=["QB", "RB", "WR", "TE", "K", "DEF"], default=[], key="pool_pos_filter")
    with fc2:
        team_filter = st.text_input("Filter by Team (e.g. KC, PHI)", key="pool_team_filter").upper().strip()
    with fc3:
        search_filter = st.text_input("Search by Name", key="pool_name_filter").strip().lower()

    filtered_df = pool_df.copy()
    if pos_filter:
        filtered_df = filtered_df[filtered_df["Pos"].isin(pos_filter)]
    if team_filter:
        filtered_df = filtered_df[filtered_df["Team"].str.upper().str.contains(team_filter, na=False)]
    if search_filter:
        filtered_df = filtered_df[filtered_df["Player"].str.lower().str.contains(search_filter, na=False)]

    pos_counts = pool_df["Pos"].value_counts()
    _pos_bar_html = ""
    for pos2 in ["QB", "RB", "WR", "TE", "K", "DEF"]:
        _pc = int(pos_counts.get(pos2, 0))
        _pcol = POS_COLORS.get(pos2, TEXT_SEC)
        _pos_bar_html += (
            "<div style=\"background:" + CARD_BG + ";border-radius:8px;padding:10px 14px;text-align:center;"
            "border:1px solid " + BORDER + ";\">"
            "<div style=\"color:" + _pcol + ";font-size:1.2rem;font-weight:900;font-family:system-ui;\">" + str(_pc) + "</div>"
            "<div style=\"color:" + _pcol + ";font-size:0.6rem;font-weight:700;font-family:system-ui;"
            "text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;\">" + pos2 + "</div></div>"
        )
    st.markdown(
        "<div style=\"display:grid;grid-template-columns:repeat(6,1fr);gap:8px;margin-bottom:16px;\">" + _pos_bar_html + "</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style=\"color:" + TEXT_SEC + ";font-size:0.75rem;font-family:system-ui;margin-bottom:8px;\">"
        "Showing <b style=\"color:" + TEXT_PRI + ";\">" + str(len(filtered_df)) + "</b> of " + str(len(pool_df)) + " players</p>",
        unsafe_allow_html=True,
    )

    if filtered_df.empty:
        _empty_table_state(
            "No players match your filters. Clear position filters, team code, or search text to see the full pool.",
        )
        return

    _mx_adp = max(float(pool_df["ADP"].max()), 80.0) if len(pool_df) else 200.0
    _adpn = pd.to_numeric(filtered_df["ADP"], errors="coerce").fillna(_mx_adp)
    display_df = filtered_df.copy()
    display_df["__brd"] = (100.0 * (1.0 - _adpn.clip(lower=0.0, upper=_mx_adp) / _mx_adp)).clip(0.0, 100.0).round(1)
    _cols_show = ["Photo", "Rank", "Player", "Pos", "Team", "Bye", "SOS", "__brd", "ADP", _ppg_col]
    display_df = display_df[[c for c in _cols_show if c in display_df.columns]]
    display_df.columns = ["Photo", "Rank", "Player", "Pos", "Team", "Bye", "SOS", "Board value", "ADP", _ppg_col]

    st.dataframe(
        display_df,
        width="stretch",
        height=600,
        hide_index=True,
        column_config={
            "Photo": st.column_config.ImageColumn("Photo", width="small", help="Sleeper headshot when available."),
            "Rank": st.column_config.NumberColumn("Rank", format="%d", width="small", help="ADP rank in pool."),
            "Player": st.column_config.TextColumn("Player", width="medium", help="Player name."),
            "Pos": st.column_config.TextColumn("Pos", width="small", help="Fantasy position."),
            "Team": st.column_config.TextColumn("Team", width="small", help="NFL team abbreviation."),
            "Bye": st.column_config.TextColumn("Bye", width="small", help="2025 bye week."),
            "SOS": st.column_config.TextColumn("SOS", width="small", help="Strength of schedule tier."),
            "Board value": st.column_config.ProgressColumn(
                "Board value", help="Higher % = earlier ADP (better draft capital).", format="%d%%", min_value=0, max_value=100,
            ),
            "ADP": st.column_config.NumberColumn("ADP", format="%.1f", help="Average draft position."),
            _ppg_col: st.column_config.NumberColumn(_ppg_col, format="%.2f", help="Projected fantasy PPG for your scoring view."),
        },
    )


# ---------------------------------------------------------------------------
# LOOKUP FRAGMENT
# ---------------------------------------------------------------------------
@st.fragment
def _render_lookup_fragment():
    pool = st.session_state.player_pool
    _pk = _player_pool_json_cache_key()
    all_names = _cached_sorted_player_names(_pk)

    lookup_name = st.selectbox("Select a player", options=["\u2014 Select a player \u2014"] + all_names, key="lookup_player_select")
    lookup_round = st.slider("Draft Round (for value verdict)", min_value=1, max_value=20, value=5, step=1, key="lookup_round_slider")

    if lookup_name != "\u2014 Select a player \u2014":
        player_data = next((p for p in pool if p["name"] == lookup_name), None)
        if player_data:
            _lookup_sk = _draft_scoring_key()
            grade, verdict, proj_ppg, conf = grade_player_adp(
                player_data["name"], player_data["position"], player_data["ppg"],
                player_data["adp"], lookup_round, _draft_num_teams(), _lookup_sk, player_data,
            )

            pos_col = POS_COLORS.get(player_data["position"], "#6b7280")
            pos_bg = POS_COLORS_BG.get(player_data["position"], "rgba(107,114,128,0.1)")
            grade_col = GRADE_COLORS.get(grade, "#6b7280")
            grade_bg = GRADE_COLORS_BG.get(grade, "rgba(107,114,128,0.1)")
            verdict_col = SUCCESS_TX if verdict == "Great Value" else DANGER_TX if verdict == "Overpriced" else WARNING_TX

            _pd_name = player_data["name"]
            _pd_pos = player_data["position"]
            _pd_team = player_data["team"]
            _raw_pool_ppg = float(player_data["ppg"])
            _pd_adp = str(int(player_data["adp"]))
            _pd_ppg = str(round(proj_ppg, 1))
            _pd_rd = str(math.ceil(player_data["adp"] / float(max(6, _draft_num_teams()))))
            _vor_b_raw = effective_vor_baseline(player_data["position"], _lookup_sk)
            _vz = effective_fantasy_ppg(_raw_pool_ppg, player_data["position"], _lookup_sk, player_data) - _vor_b_raw
            _vor_base = str(round(_vor_b_raw, 1))
            _vor_val = ("+" if _vz >= 0 else "") + str(round(_vz, 2))
            _conf_str = str(round(conf, 2))
            _fmt_delta_n = round(proj_ppg - _raw_pool_ppg, 2)
            _ppr_adj = ("+" if _fmt_delta_n >= 0 else "") + str(_fmt_delta_n)
            _adj_lbl = _scoring_adj_label()
            _lookup_photo = _photo_img_html(_player_photo_url(player_data), size_px=88, border_color=BORDER)

            # SOS + Bye info
            _sos = SOS_TIERS.get(_pd_team, "Medium")
            _sos_col = SOS_COLORS.get(_sos, WARNING_TX)
            _bye = BYE_WEEKS.get(_pd_team, "--")
            _bye_str = "Week " + str(_bye) if isinstance(_bye, int) else "--"

            st.markdown(
                "<div style=\"background:" + CARD_BG + ";border-radius:14px;padding:0;margin-top:12px;overflow:hidden;"
                "border:1px solid " + BORDER + ";\">"
                "<div style=\"background:linear-gradient(135deg," + pos_col + "20 0%,transparent 100%);"
                "padding:24px 28px 20px;border-bottom:1px solid " + BORDER + ";\">"
                "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;\">"
                "<div style=\"display:flex;align-items:flex-start;gap:16px;min-width:0;\">"
                + _lookup_photo
                + "<div style=\"min-width:0;\">"
                "<div style=\"display:flex;align-items:center;gap:10px;margin-bottom:6px;\">"
                "<span style=\"color:" + pos_col + ";font-size:0.72rem;font-weight:700;"
                "background:" + pos_bg + ";padding:3px 10px;border-radius:5px;font-family:system-ui;"
                "letter-spacing:0.06em;border:1px solid " + pos_col + "40;\">" + _pd_pos + "</span>"
                "<span style=\"color:" + TEXT_SEC + ";font-size:0.82rem;font-family:monospace;\">" + _pd_team + "</span>"
                "</div>"
                "<h2 style=\"color:" + TEXT_PRI + ";margin:0;font-size:1.8rem;font-weight:900;font-family:system-ui;"
                "letter-spacing:-0.03em;line-height:1.1;\">" + _pd_name + "</h2>"
                "</div></div>"
                "<div style=\"text-align:center;background:" + grade_bg + ";border:2px solid " + grade_col + ";"
                "border-radius:14px;padding:14px 22px;min-width:70px;\">"
                "<div style=\"color:" + grade_col + ";font-size:2.8rem;font-weight:900;line-height:1;font-family:system-ui;\">" + grade + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:system-ui;"
                "text-transform:uppercase;letter-spacing:0.12em;margin-top:4px;font-weight:600;\">Draft Grade</div>"
                "</div></div></div>"
                # Stats grid (6 items now: ADP, PPG, Round, Verdict, Bye, SOS)
                "<div style=\"padding:20px 28px;\">"
                "<div style=\"display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:18px;\">"
                # ADP
                "<div style=\"background:" + STAT_BG + ";border-radius:10px;padding:14px;text-align:center;border:1px solid " + BORDER + ";\">"
                "<div style=\"color:" + TEXT_PRI + ";font-size:1.5rem;font-weight:900;font-family:system-ui;\">" + _pd_adp + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;font-weight:600;\">ADP Rank</div></div>"
                # PPG
                "<div style=\"background:" + STAT_BG + ";border-radius:10px;padding:14px;text-align:center;border:1px solid " + BORDER + ";\">"
                "<div style=\"color:" + SUCCESS_TX + ";font-size:1.5rem;font-weight:900;font-family:system-ui;\">" + _pd_ppg + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;font-weight:600;\">Proj PPG</div></div>"
                # Verdict
                "<div style=\"background:" + STAT_BG + ";border-radius:10px;padding:14px;text-align:center;border:1px solid " + BORDER + ";\">"
                "<div style=\"color:" + verdict_col + ";font-size:1.1rem;font-weight:800;font-family:system-ui;\">" + verdict + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;font-weight:600;\">Round " + str(lookup_round) + " Value</div></div>"
                # ADP Round
                "<div style=\"background:" + STAT_BG + ";border-radius:10px;padding:14px;text-align:center;border:1px solid " + BORDER + ";\">"
                "<div style=\"color:" + TEXT_PRI + ";font-size:1.5rem;font-weight:900;font-family:system-ui;\">Rd " + _pd_rd + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;font-weight:600;\">ADP Round</div></div>"
                # Bye Week (#9)
                "<div style=\"background:" + STAT_BG + ";border-radius:10px;padding:14px;text-align:center;border:1px solid " + BORDER + ";\">"
                "<div style=\"color:" + INFO_TX + ";font-size:1.5rem;font-weight:900;font-family:system-ui;\">" + _bye_str + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;font-weight:600;\">Bye Week</div></div>"
                # SOS (#7)
                "<div style=\"background:" + STAT_BG + ";border-radius:10px;padding:14px;text-align:center;border:1px solid " + BORDER + ";\">"
                "<div style=\"color:" + _sos_col + ";font-size:1.3rem;font-weight:900;font-family:system-ui;\">" + _sos + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;font-weight:600;\">Schedule</div></div>"
                "</div>"
                # Analysis section
                "<div style=\"background:" + STAT_BG + ";border-radius:10px;padding:18px 20px;border:1px solid " + BORDER + ";\">"
                "<h5 style=\"color:" + TEXT_SEC + ";margin:0 0 12px;font-family:system-ui;"
                "font-weight:600;text-transform:uppercase;letter-spacing:0.12em;font-size:0.62rem;\">Analysis</h5>"
                "<div style=\"display:grid;grid-template-columns:1fr 1fr;gap:8px 24px;\">"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.78rem;font-family:system-ui;\">"
                "VOR Baseline <span style=\"color:" + TEXT_PRI + ";font-weight:600;float:right;font-family:monospace;font-size:0.8rem;\">" + _vor_base + " PPG</span></div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.78rem;font-family:system-ui;\">"
                "Value Over Repl. <span style=\"color:" + TEXT_PRI + ";font-weight:600;float:right;font-family:monospace;font-size:0.8rem;\">" + _vor_val + "</span></div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.78rem;font-family:system-ui;\">"
                "Confidence <span style=\"color:" + TEXT_PRI + ";font-weight:600;float:right;font-family:monospace;font-size:0.8rem;\">" + _conf_str + "</span></div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.78rem;font-family:system-ui;\">"
                + html.escape(_adj_lbl) + " <span style=\"color:" + TEXT_PRI + ";font-weight:600;float:right;font-family:monospace;font-size:0.8rem;\">" + _ppr_adj + " PPG</span></div>"
                "</div></div></div></div>",
                unsafe_allow_html=True,
            )

            # Similar Players
            st.markdown("<div style=\"margin-top:20px;\"></div>", unsafe_allow_html=True)
            _render_eyebrow("Similar Players by Position & ADP", margin_bottom=10)
            pos_pool = [p for p in pool if p["position"] == player_data["position"] and p["name"] != player_data["name"]]
            pos_pool.sort(key=lambda p: abs(p["adp"] - player_data["adp"]))
            similar = pos_pool[:8]
            if not similar:
                _empty_table_state("No other players at this position in the pool to compare.")
            else:
                sim_df = pd.DataFrame(similar)[["name", "team", "adp", "ppg"]].copy()
                sim_df.insert(0, "Photo", [_player_photo_url(p0) for p0 in similar])
                sim_df["bye"] = [BYE_WEEKS.get(p0["team"], "--") for p0 in similar]
                sim_df["sos"] = [SOS_TIERS.get(p0["team"], "Medium") for p0 in similar]
                sim_df.columns = ["Photo", "Player", "Team", "ADP", "PPG", "Bye", "SOS"]
                sim_df["ADP"] = sim_df["ADP"].round(1)
                sim_df["PPG"] = [round(effective_fantasy_ppg(p0["ppg"], p0["position"], _lookup_sk, p0), 2) for p0 in similar]
                st.dataframe(
                    sim_df, width="stretch", hide_index=True,
                    column_config={
                        "Photo": st.column_config.ImageColumn("Photo", width="small"),
                        "Player": st.column_config.TextColumn("Player", width="large"),
                        "Team": st.column_config.TextColumn("Team", width="small"),
                        "ADP": st.column_config.NumberColumn("ADP", format="%.1f"),
                        "PPG": st.column_config.NumberColumn("PPG", format="%.2f"),
                        "Bye": st.column_config.TextColumn("Bye", width="small"),
                        "SOS": st.column_config.TextColumn("SOS", width="small"),
                    },
                )
        else:
            st.warning("Player '" + lookup_name + "' not found in the pool.")

    # Pool Statistics
    st.markdown("<div style=\"margin-top:20px;\"></div>", unsafe_allow_html=True)
    _render_eyebrow("Pool Statistics", margin_bottom=10)
    _stats_sk = st.session_state.get("league_scoring", "PPR")
    _stats_nt = max(6, _draft_num_teams())
    top10, top_vor = _cached_lookup_stats_tables(_pk, _stats_sk, _stats_nt)
    sc1, sc2 = st.columns(2)
    _cfg_top10 = {
        "Player": st.column_config.TextColumn("Player", width="large"),
        "Pos": st.column_config.TextColumn("Pos", width="small"),
        "Team": st.column_config.TextColumn("Team", width="small"),
        "ADP": st.column_config.NumberColumn("ADP", format="%.1f"),
        "PPG": st.column_config.NumberColumn("PPG", format="%.2f"),
    }
    _cfg_top_vor = {
        "Player": st.column_config.TextColumn("Player", width="large"),
        "Pos": st.column_config.TextColumn("Pos", width="small"),
        "Team": st.column_config.TextColumn("Team", width="small"),
        "ADP": st.column_config.NumberColumn("ADP", format="%.1f"),
        "PPG": st.column_config.NumberColumn("PPG", format="%.2f"),
        "VOR": st.column_config.NumberColumn("VOR", format="%.2f"),
    }
    with sc1:
        _render_eyebrow("Top 10 by Projected PPG", margin_bottom=8)
        if top10.empty:
            _empty_table_state("No players with positive projected PPG in the pool.")
        else:
            st.dataframe(top10, width="stretch", hide_index=True, column_config=_cfg_top10)
    with sc2:
        _render_eyebrow("Best ADP Value (VOR)", margin_bottom=8)
        if top_vor.empty:
            _empty_table_state("No VOR data — check that the player pool has projections.")
        else:
            st.dataframe(top_vor, width="stretch", hide_index=True, column_config=_cfg_top_vor)


# ---------------------------------------------------------------------------
# THEME TOGGLE
# ---------------------------------------------------------------------------
def _render_theme_toggle(key_suffix):
    _tc1, _tc2 = st.columns([10, 1])
    with _tc2:
        _icon = "\u2600\ufe0f" if st.session_state.theme == "dark" else "\U0001f319"
        _tip = "Switch to Light Mode" if st.session_state.theme == "dark" else "Switch to Dark Mode"
        if st.button(_icon, key="theme_toggle_" + key_suffix, help=_tip):
            st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
            st.rerun()


# ===========================================================================
# HEADER
# ===========================================================================
_hdr_teams = int(st.session_state.league_num_teams)
_hdr_scoring = st.session_state.league_scoring
_hdr_format = st.session_state.league_draft_format
_hdr_preset = st.session_state.league_roster_preset
_hdr_col, _about_col, _toggle_col = st.columns([10, 1, 1])
_is_dark = st.session_state.theme == "dark"
_hdr_accent = ACCENT_GRN
_hdr_glow = "rgba(16,185,129,0.08)" if _is_dark else "rgba(16,185,129,0.05)"
with _hdr_col:
    st.markdown(
        "<div style=\"background:linear-gradient(135deg," + HDR_BG1 + " 0%," + HDR_BG2 + " 100%);"
        "border-radius:" + str(UI_RADIUS_LG) + "px;padding:" + str(UI_SPACE_5 + 4) + "px " + str(UI_SPACE_6 + 4) + "px " + str(UI_SPACE_5) + "px;margin-bottom:" + str(UI_SPACE_5 - 4) + "px;"
        "border:1px solid " + BORDER + ";box-shadow:0 0 40px " + _hdr_glow + ";\">"
        "<div style=\"display:flex;align-items:center;gap:14px;margin-bottom:8px;\">"
        "<div style=\"width:40px;height:40px;border-radius:10px;"
        "background:linear-gradient(135deg," + _hdr_accent + " 0%,#059669 100%);"
        "display:flex;align-items:center;justify-content:center;"
        "font-size:1.2rem;box-shadow:0 2px 8px rgba(16,185,129,0.3);\">&#127944;</div>"
        "<div>"
        "<h1 style=\"color:" + TEXT_PRI + ";margin:0;font-size:2.2rem;font-weight:900;letter-spacing:-0.04em;"
        "font-family:system-ui;line-height:1;\">"
        "DRAFT<span style=\"color:" + _hdr_accent + ";\">i</span></h1></div></div>"
        "<div style=\"display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;\">"
        "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;font-family:system-ui;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;"
        "background:" + STAT_BG + ";padding:3px 10px;border-radius:4px;border:1px solid " + BORDER + ";\">2025 NFL</span>"
        "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;font-family:system-ui;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;"
        "background:" + STAT_BG + ";padding:3px 10px;border-radius:4px;border:1px solid " + BORDER + ";\">"
        + str(_hdr_teams) + "-Team " + html.escape(_hdr_scoring) + "</span>"
        "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;font-family:system-ui;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;"
        "background:" + STAT_BG + ";padding:3px 10px;border-radius:4px;border:1px solid " + BORDER + ";\">"
        + html.escape(_hdr_format) + " Draft</span>"
        "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;font-family:system-ui;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;"
        "background:" + STAT_BG + ";padding:3px 10px;border-radius:4px;border:1px solid " + BORDER + ";\">"
        + html.escape(_hdr_preset) + " Roster</span>"
        "<span style=\"color:" + _hdr_accent + ";font-size:0.72rem;font-family:system-ui;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;"
        "background:rgba(16,185,129,0.1);padding:3px 10px;border-radius:4px;border:1px solid rgba(16,185,129,0.2);\">AI-Powered</span>"
        "</div></div>",
        unsafe_allow_html=True
    )
with _about_col:
    st.markdown("<div style=\"padding-top:28px;\">", unsafe_allow_html=True)
    with st.popover("About", help="Data sources, scoring, and APIs"):
        st.markdown(
            "**Player pool** — Loaded from `players.json` with optional **Sleeper** live sync for NFL metadata and headshots.\n\n"
            "**Projections** — Stored in a PPR-shaped `ppg`; Half PPR and Standard adjust using per-game **`rec`** / **`targets`** when available, else position heuristics.\n\n"
            "**Grades & VOR** — Heuristic value vs ADP and value over replacement; for mock drafts only, not professional advice.\n\n"
            "**APIs** — [Sleeper](https://sleeper.app/) public API for avatars and player data."
        )
    st.markdown("</div>", unsafe_allow_html=True)
with _toggle_col:
    st.markdown("<div style=\"padding-top:28px;\">", unsafe_allow_html=True)
    _icon_hdr = "\u2600\ufe0f" if _is_dark else "\U0001f319"
    if st.button(_icon_hdr, key="theme_toggle_header", help="Toggle theme"):
        st.session_state.theme = "light" if _is_dark else "dark"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


# ===========================================================================
# TABS (added DRAFT HISTORY tab for #8)
# ===========================================================================
tab_draft, tab_pool, tab_lookup, tab_history = st.tabs([
    "MOCK DRAFT", "PLAYER POOL", "PLAYER LOOKUP", "DRAFT HISTORY",
])

_ds_step = st.session_state.get("draft_state")
if not st.session_state.draft_started:
    st.caption("Step 1 \u2014 Configure league in **Mock Draft**, then start.")
elif _ds_step and _ds_step.get("draft_complete"):
    st.caption("Step 3 \u2014 Draft complete. Review your recap and start a **New Draft**.")
else:
    st.caption("Step 2 \u2014 Live mock: recommendations refresh each pick.")


# ===========================================================================
# PICK HANDLER (shared helper)
# ===========================================================================
def _handle_pick(state, player_name, pick_num, player_data=None):
    """Execute a user pick, saving undo state and updating session."""
    # Save undo snapshot (#2)
    st.session_state.undo_stack.append(
        save_undo_snapshot(state, st.session_state.draft_history)
    )
    if len(st.session_state.undo_stack) > 15:
        st.session_state.undo_stack = st.session_state.undo_stack[-15:]

    result = make_user_pick(state, player_name, _roster_preset())
    if "error" in result:
        st.session_state.undo_stack.pop()
        return result

    if player_data is None:
        player_data = result["picked"]

    grade_v, _, proj_ppg_v, _ = grade_player_adp(
        player_data["name"], player_data["position"], player_data["ppg"],
        player_data["adp"], result["round"], _draft_num_teams(), _draft_scoring_key(), player_data,
    )
    st.session_state.draft_history.append({
        "round": result["round"], "pick": pick_num,
        "player": player_data["name"], "position": player_data["position"],
        "team": player_data["team"], "adp": player_data["adp"],
        "ppg": player_data["ppg"], "grade": grade_v,
    })

    if not state.get("draft_complete"):
        st.session_state.current_recs = get_top_recommendations(
            state["available_players"], state["rosters"][state["user_team"]],
            state["picks_made"] + 1, n=5,
            scoring_key=_draft_scoring_key(), num_teams=_draft_num_teams(),
            roster_preset=_roster_preset(),
        )
    else:
        # Save completed draft (#8)
        roster = state["rosters"][state["user_team"]]
        save_draft_result(st.session_state.draft_history, roster, {
            "num_teams": _draft_num_teams(), "scoring": _draft_scoring_key(),
            "format": "Snake" if state.get("snake") else "Linear",
            "roster_preset": _roster_preset(), "user_slot": state["user_team"],
        })

    return result


# ===========================================================================
# SCREEN 1: MOCK DRAFT SIMULATOR
# ===========================================================================
with tab_draft:
    _render_theme_toggle("draft")
    _render_context_chips([
        ("Scoring", st.session_state.get("league_scoring", "PPR")),
        ("Format", st.session_state.get("league_draft_format", "Snake")),
        ("Slot", ordinal(int(st.session_state.get("league_user_slot", 1)))),
        ("Roster", st.session_state.get("league_roster_preset", "Standard")),
    ])
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        if not st.session_state.draft_started:
            # --- CONFIG PANEL ---
            _pool_size = len(DRAFT_PLAYER_POOL)
            _draft_pool_source = st.session_state.get("player_pool_source", "embedded fallback")
            _draft_pool_updated = st.session_state.get("player_pool_last_updated", "Unknown")
            with st.container(border=True):
                st.markdown(
                    "<div style=\"text-align:center;padding:20px 16px 8px;\">"
                    "<h2 style=\"color:" + TEXT_PRI + ";font-family:system-ui;font-weight:800;"
                    "font-size:1.8rem;letter-spacing:-0.03em;margin:0;\">YOUR DRAFT ROOM</h2>"
                    "<p style=\"color:" + TEXT_SEC + ";font-size:0.82rem;margin:6px 0 0;\">Configure and launch your mock draft simulation</p></div>",
                    unsafe_allow_html=True,
                )
                _cfg1, _cfg2, _cfg3, _cfg4 = st.columns(4)
                with _cfg1:
                    st.slider("Teams in league", min_value=6, max_value=16, step=1, key="league_num_teams")
                with _cfg2:
                    st.selectbox("Draft format", options=("Snake", "Linear"), key="league_draft_format")
                with _cfg3:
                    st.selectbox("Scoring", options=("PPR", "Half PPR", "Standard"), key="league_scoring")
                with _cfg4:
                    # #3: Customizable roster presets
                    st.selectbox("Roster format", options=list(ROSTER_PRESETS.keys()), key="league_roster_preset",
                                 help="Standard=1QB/2RB/2WR/1TE/FLEX/K/DEF/6BN. Superflex adds a SFLEX slot.")

                _nt2 = max(6, min(16, int(st.session_state.league_num_teams)))
                _slot_opts = list(range(1, _nt2 + 1))
                _cur_slot = max(1, min(_nt2, int(st.session_state.league_user_slot)))
                if _cur_slot != st.session_state.league_user_slot:
                    st.session_state.league_user_slot = _cur_slot
                _slot_idx = _slot_opts.index(_cur_slot)
                st.selectbox("Your draft slot", options=_slot_opts, index=_slot_idx, format_func=ordinal, key="league_user_slot")

                # Config summary
                _sum_fmt = st.session_state.league_scoring + " \u00b7 " + st.session_state.league_draft_format
                _sum_slot = ordinal(int(st.session_state.league_user_slot))
                _preset = st.session_state.league_roster_preset
                _preset_slots = ROSTER_PRESETS.get(_preset, ROSTER_PRESETS["Standard"])
                _roster_desc = " ".join(
                    "<span style=\"color:" + POS_COLORS.get(k, TEXT_SEC) + ";\">" + k + "</span>&#xd7;" + str(v)
                    for k, v in _preset_slots.items() if k != "BN"
                ) + " BN&#xd7;" + str(_preset_slots.get("BN", 6))
                _total_rds = roster_total_slots(_preset)

                st.markdown(
                    "<div style=\"background:" + CARD_BG + ";border-radius:" + str(UI_RADIUS_MD) + "px;padding:" + str(UI_SPACE_5) + "px;border:1px solid " + BORDER + ";margin-bottom:" + str(UI_SPACE_4) + "px;\">"
                    "<h5 style=\"color:" + TEXT_SEC + ";margin:0 0 " + str(UI_SPACE_4) + "px;font-family:system-ui;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;font-size:0.72rem;\">League Configuration</h5>"
                    "<div style=\"display:grid;grid-template-columns:1fr 1fr;gap:" + str(UI_SPACE_3) + "px;\">"
                    "<div style=\"background:" + STAT_BG + ";border-radius:" + str(UI_RADIUS_SM) + "px;padding:" + str(UI_SPACE_3 + 2) + "px;\">"
                    "<div style=\"color:" + TEXT_SEC + ";font-size:0.65rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;\">Format</div>"
                    "<div style=\"color:" + TEXT_PRI + ";font-size:1rem;font-weight:700;font-family:system-ui;margin-top:4px;\">" + html.escape(_sum_fmt) + "</div></div>"
                    "<div style=\"background:" + STAT_BG + ";border-radius:" + str(UI_RADIUS_SM) + "px;padding:" + str(UI_SPACE_3 + 2) + "px;\">"
                    "<div style=\"color:" + TEXT_SEC + ";font-size:0.65rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;\">Your slot</div>"
                    "<div style=\"color:" + ACCENT_GRN + ";font-size:1rem;font-weight:700;font-family:system-ui;margin-top:4px;\">" + _sum_slot + " each round</div></div>"
                    "<div style=\"background:" + STAT_BG + ";border-radius:" + str(UI_RADIUS_SM) + "px;padding:" + str(UI_SPACE_3 + 2) + "px;\">"
                    "<div style=\"color:" + TEXT_SEC + ";font-size:0.65rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;\">Roster (" + html.escape(_preset) + ")</div>"
                    "<div style=\"color:" + TEXT_PRI + ";font-size:0.82rem;font-weight:500;font-family:system-ui;margin-top:4px;line-height:1.5;\">"
                    + _roster_desc + "</div></div>"
                    "<div style=\"background:" + STAT_BG + ";border-radius:" + str(UI_RADIUS_SM) + "px;padding:" + str(UI_SPACE_3 + 2) + "px;\">"
                    "<div style=\"color:" + TEXT_SEC + ";font-size:0.65rem;font-family:system-ui;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;\">Player Pool</div>"
                    "<div style=\"color:" + TEXT_PRI + ";font-size:1rem;font-weight:700;font-family:system-ui;margin-top:4px;\">"
                    + str(_pool_size) + " <span style=\"font-weight:400;font-size:0.82rem;color:" + TEXT_SEC + ";\">players &middot; " + str(_total_rds) + " rounds</span></div></div>"
                    "</div></div>",
                    unsafe_allow_html=True,
                )

                if st.button("Start Mock Draft", type="primary", width="stretch"):
                    st.session_state.draft_state = init_draft_state(
                        st.session_state.get("player_pool", DRAFT_PLAYER_POOL),
                        num_teams=int(st.session_state.league_num_teams),
                        user_team=int(st.session_state.league_user_slot),
                        snake=st.session_state.league_draft_format == "Snake",
                        scoring=st.session_state.league_scoring,
                        roster_preset=st.session_state.league_roster_preset,
                    )
                    st.session_state.draft_started = True
                    st.session_state.draft_history = []
                    st.session_state.undo_stack = []
                    _s = st.session_state.draft_state
                    st.session_state.current_recs = get_top_recommendations(
                        _s["available_players"], _s["rosters"][_s["user_team"]], _s["picks_made"] + 1,
                        n=5, scoring_key=_s["scoring"], num_teams=int(_s["num_teams"]),
                        roster_preset=_s["roster_preset"],
                    )
                    st.toast("Draft started \u2014 good luck!", icon="\U0001f3c8")
                    st.rerun()

        else:
            state = st.session_state.draft_state
            total_rounds = state.get("total_rounds", 15)
            total_slots = roster_total_slots(state.get("roster_preset", "Standard"))

            if state.get("draft_complete"):
                # =========== DRAFT RECAP (#4) ===========
                roster = state["rosters"][state["user_team"]]
                recap = compute_draft_recap(
                    roster, st.session_state.draft_history,
                    scoring_key=state.get("scoring", "PPR"),
                    num_teams=int(state["num_teams"]),
                )

                st.markdown(
                    "<div style=\"background:linear-gradient(135deg,rgba(16,185,129,0.08) 0%,rgba(16,185,129,0.02) 100%);"
                    "border-radius:12px;padding:28px;border:1px solid rgba(16,185,129,0.25);margin-bottom:16px;text-align:center;\">"
                    "<div style=\"font-size:2.5rem;margin-bottom:8px;\">&#127942;</div>"
                    "<h3 style=\"color:" + ACCENT_GRN + ";margin:0;font-family:system-ui;font-weight:800;"
                    "font-size:1.6rem;letter-spacing:-0.02em;\">DRAFT COMPLETE</h3>"
                    "<p style=\"color:" + TEXT_SEC + ";margin:8px 0 0;font-size:0.85rem;\">Your " + str(total_rounds) + "-round draft is finished.</p>"
                    "</div>",
                    unsafe_allow_html=True
                )

                if recap:
                    _og = recap["overall_grade"]
                    _og_col = GRADE_COLORS.get(_og, "#6b7280")
                    _og_bg = GRADE_COLORS_BG.get(_og, "rgba(107,114,128,0.1)")

                    # Overall grade + summary metrics
                    rc1, rc2, rc3, rc4 = st.columns(4)
                    with rc1:
                        st.markdown(
                            "<div style=\"background:" + _og_bg + ";border:2px solid " + _og_col + ";border-radius:14px;padding:20px;text-align:center;\">"
                            "<div style=\"color:" + _og_col + ";font-size:3rem;font-weight:900;font-family:system-ui;\">" + _og + "</div>"
                            "<div style=\"color:" + TEXT_SEC + ";font-size:0.6rem;text-transform:uppercase;letter-spacing:0.12em;margin-top:4px;font-weight:600;\">Overall Grade</div></div>",
                            unsafe_allow_html=True
                        )
                    with rc2:
                        st.metric("Total Proj PPG", recap["total_ppg"])
                    with rc3:
                        st.metric("Steals", len(recap["steals"]))
                    with rc4:
                        st.metric("Reaches", len(recap["reaches"]))

                    # Best & worst picks
                    bp = recap.get("best_pick")
                    wp = recap.get("worst_pick")
                    if bp or wp:
                        bpc, wpc = st.columns(2)
                        with bpc:
                            if bp:
                                st.markdown(
                                    "<div style=\"background:rgba(16,185,129,0.08);border-radius:10px;padding:16px;border:1px solid rgba(16,185,129,0.2);\">"
                                    "<div style=\"color:" + SUCCESS_TX + ";font-size:0.6rem;text-transform:uppercase;letter-spacing:0.1em;font-weight:700;margin-bottom:6px;\">Best Pick (Biggest Steal)</div>"
                                    "<div style=\"color:" + TEXT_PRI + ";font-size:1rem;font-weight:700;\">" + bp["player"] + "</div>"
                                    "<div style=\"color:" + TEXT_SEC + ";font-size:0.78rem;\">Rd " + str(bp["round"]) + " &middot; ADP Rd " + str(round(bp["adp"] / max(6, int(state["num_teams"])), 1)) + " &middot; +" + str(bp["value_diff"]) + " rounds of value</div>"
                                    "</div>", unsafe_allow_html=True
                                )
                        with wpc:
                            if wp:
                                st.markdown(
                                    "<div style=\"background:rgba(239,68,68,0.08);border-radius:10px;padding:16px;border:1px solid rgba(239,68,68,0.2);\">"
                                    "<div style=\"color:" + DANGER_TX + ";font-size:0.6rem;text-transform:uppercase;letter-spacing:0.1em;font-weight:700;margin-bottom:6px;\">Biggest Reach</div>"
                                    "<div style=\"color:" + TEXT_PRI + ";font-size:1rem;font-weight:700;\">" + wp["player"] + "</div>"
                                    "<div style=\"color:" + TEXT_SEC + ";font-size:0.78rem;\">Rd " + str(wp["round"]) + " &middot; ADP Rd " + str(round(wp["adp"] / max(6, int(state["num_teams"])), 1)) + " &middot; " + str(wp["value_diff"]) + " rounds</div>"
                                    "</div>", unsafe_allow_html=True
                                )

                    # Bye week conflicts in recap
                    if recap["bye_conflicts"]:
                        st.markdown("<h5 style=\"color:" + DANGER_TX + ";margin:16px 0 8px;\">Bye Week Conflicts</h5>", unsafe_allow_html=True)
                        for wk, names in recap["bye_conflicts"].items():
                            st.warning("Week " + str(wk) + " bye: " + ", ".join(names) + " (" + str(len(names)) + " players)")

                    # Position breakdown
                    st.markdown("<h5 style=\"color:" + TEXT_SEC + ";margin:16px 0 8px;\">Position Breakdown</h5>", unsafe_allow_html=True)
                    _pb_html = ""
                    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
                        _pg = recap["pos_groups"].get(pos, [])
                        _pcol = POS_COLORS.get(pos, TEXT_SEC)
                        _pb_html += (
                            "<div style=\"background:" + CARD_BG + ";border-radius:8px;padding:12px;text-align:center;border:1px solid " + BORDER + ";\">"
                            "<div style=\"color:" + _pcol + ";font-size:1.4rem;font-weight:900;\">" + str(len(_pg)) + "</div>"
                            "<div style=\"color:" + _pcol + ";font-size:0.6rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;\">" + pos + "</div></div>"
                        )
                    st.markdown("<div style=\"display:grid;grid-template-columns:repeat(6,1fr);gap:8px;\">" + _pb_html + "</div>", unsafe_allow_html=True)

                if st.button("\U0001f504 New Draft", width="stretch"):
                    st.session_state.draft_started = False
                    st.session_state.draft_state = None
                    st.session_state.draft_history = []
                    st.session_state.current_recs = []
                    st.session_state.last_pick_result = None
                    st.session_state.undo_stack = []
                    st.rerun()

            else:
                # =========== LIVE DRAFT ===========
                pick_num = state["picks_made"] + 1
                rnd_num = state["current_round"]
                avail_cnt = len(state["available_players"])
                roster = state["rosters"][state["user_team"]]
                needs = get_positional_needs(roster, _roster_preset())

                _pct_complete = int((len(roster) / total_slots) * 100)
                _dm1, _dm2, _dm3, _dm4 = st.columns(4)
                with _dm1:
                    st.metric("Overall pick", "#" + str(pick_num))
                with _dm2:
                    st.metric("Round", str(rnd_num) + " / " + str(total_rounds))
                with _dm3:
                    st.metric("Available", str(avail_cnt))
                with _dm4:
                    st.metric("Roster", str(len(roster)) + " / " + str(total_slots), delta=str(_pct_complete) + "%", delta_color="off")

                _fmt_lbl = "Snake" if state.get("snake") else "Linear"
                st.caption(
                    str(int(state["num_teams"])) + "-team \u00b7 " + str(state.get("scoring", "PPR"))
                    + " \u00b7 " + _fmt_lbl + " \u00b7 " + state.get("roster_preset", "Standard")
                    + " \u00b7 Your slot: " + ordinal(int(state["user_team"]))
                )

                # --- POSITIONAL SCARCITY (#5) ---
                scarcity = get_positional_scarcity(state["available_players"], _draft_scoring_key())
                _scar_html = ""
                for pos in ("QB", "RB", "WR", "TE"):
                    sc = scarcity.get(pos, {"total": 0, "startable": 0})
                    _pcol = POS_COLORS.get(pos, TEXT_SEC)
                    _alert = DANGER_TX if sc["startable"] <= 3 else (WARNING_TX if sc["startable"] <= 6 else _pcol)
                    _scar_html += (
                        "<div style=\"background:" + CARD_BG + ";border-radius:6px;padding:8px 12px;text-align:center;border:1px solid " + BORDER + ";\">"
                        "<div style=\"color:" + _alert + ";font-size:1rem;font-weight:900;font-family:system-ui;\">" + str(sc["startable"]) + "</div>"
                        "<div style=\"color:" + TEXT_SEC + ";font-size:0.55rem;font-weight:600;text-transform:uppercase;letter-spacing:0.1em;\">" + pos + " startable</div></div>"
                    )
                st.markdown(
                    "<div style=\"display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin:8px 0 12px;\">" + _scar_html + "</div>",
                    unsafe_allow_html=True
                )

                # --- RECOMMENDATIONS ---
                recs = st.session_state.current_recs
                if not recs:
                    recs = get_top_recommendations(
                        state["available_players"], roster, pick_num, n=5,
                        scoring_key=_draft_scoring_key(), num_teams=_draft_num_teams(),
                        roster_preset=_roster_preset(),
                    )
                    st.session_state.current_recs = recs

                # --- KEY FINDINGS (data-backed insights) ---
                _render_key_findings_panel(state, roster, recs, pick_num)
                st.markdown("<div style=\"margin-top:12px;\"></div>", unsafe_allow_html=True)

                st.markdown(
                    "<h4 style=\"color:" + TEXT_SEC + ";margin:0 0 12px;font-family:system-ui;"
                    "font-weight:600;text-transform:uppercase;letter-spacing:0.1em;font-size:0.72rem;\">"
                    "Top Recommendations &mdash; Pick #" + str(pick_num) + "</h4>",
                    unsafe_allow_html=True
                )
                for idx, rec in enumerate(recs):
                    pos_color = POS_COLORS.get(rec["position"], "#6b7280")
                    pos_bg = POS_COLORS_BG.get(rec["position"], "rgba(107,114,128,0.1)")
                    grade_col = GRADE_COLORS.get(rec["grade"], "#6b7280")
                    grade_bg = GRADE_COLORS_BG.get(rec["grade"], "rgba(107,114,128,0.1)")
                    verdict_color = SUCCESS_TX if rec["verdict"] == "Great Value" else (DANGER_TX if rec["verdict"] == "Overpriced" else WARNING_TX)
                    _rank = str(idx + 1)
                    _player = rec["player"]
                    _pos = rec["position"]
                    _team = rec["team"]
                    _grade = rec["grade"]
                    _adp_str = str(int(rec["adp"]))
                    _ppg_str = str(round(rec["proj_ppg"], 1))
                    _vor_str = str(round(rec["vor"], 1))
                    _verdict = rec["verdict"]
                    _ctx = rec["ctx"]
                    _photo_tag = _photo_img_html(_photo_url_for_player_name(_player), size_px=48, border_color=BORDER)
                    # Bye + SOS badges (#7, #9)
                    _bye_wk = rec.get("bye_week")
                    _bye_warn = rec.get("bye_warning", "")
                    _sos = rec.get("sos", "Medium")
                    _sos_col = SOS_COLORS.get(_sos, WARNING_TX)
                    _extra_badges = ""
                    if _bye_wk:
                        _extra_badges += "<span style=\"color:" + INFO_TX + ";font-size:0.65rem;font-family:system-ui;\">Bye " + str(_bye_wk) + "</span>"
                    _extra_badges += "<span style=\"color:" + _sos_col + ";font-size:0.65rem;font-weight:700;font-family:system-ui;\">" + _sos + " SOS</span>"
                    _bye_warn_html = ""
                    if _bye_warn:
                        _bye_warn_html = "<div style=\"color:" + DANGER_TX + ";font-size:0.62rem;margin-top:2px;\">&#9888; " + html.escape(_bye_warn) + "</div>"

                    st.markdown(
                        "<div style=\"background:" + CARD_BG + ";border-radius:10px;padding:0;"
                        "border:1px solid " + BORDER + ";margin-bottom:8px;overflow:hidden;\">"
                        "<div style=\"display:flex;align-items:stretch;\">"
                        "<div style=\"background:" + pos_color + ";width:36px;min-width:36px;display:flex;align-items:center;justify-content:center;\">"
                        "<span style=\"color:#fff;font-weight:900;font-size:0.85rem;font-family:system-ui;\">" + _rank + "</span></div>"
                        "<div style=\"flex:1;padding:12px 14px;\">"
                        "<div style=\"display:flex;align-items:center;gap:10px;\">"
                        + _photo_tag +
                        "<div style=\"display:flex;flex-direction:column;gap:4px;min-width:0;\">"
                        "<div style=\"display:flex;align-items:center;gap:8px;flex-wrap:wrap;\">"
                        "<span style=\"color:" + TEXT_PRI + ";font-weight:700;font-size:1.05rem;font-family:system-ui;\">" + _player + "</span>"
                        "<span style=\"color:" + pos_color + ";font-size:0.7rem;font-weight:700;background:" + pos_bg + ";padding:2px 8px;border-radius:4px;font-family:system-ui;\">" + _pos + "</span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.75rem;font-family:monospace;\">" + _team + "</span></div>"
                        "<div style=\"display:flex;gap:14px;margin-top:6px;align-items:center;flex-wrap:wrap;\">"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;\">ADP <span style=\"color:" + TEXT_PRI + ";font-weight:700;font-size:0.82rem;\">" + _adp_str + "</span></span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;\">PPG <span style=\"color:" + TEXT_PRI + ";font-weight:700;font-size:0.82rem;\">" + _ppg_str + "</span></span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;\">VOR <span style=\"color:" + TEXT_PRI + ";font-weight:700;font-size:0.82rem;\">" + _vor_str + "</span></span>"
                        "<span style=\"color:" + verdict_color + ";font-size:0.7rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;\">" + _verdict + "</span>"
                        + _extra_badges + "</div>"
                        "<div style=\"color:" + TEXT_SEC + ";font-size:0.68rem;margin-top:4px;font-style:italic;\">" + _ctx + "</div>"
                        + _bye_warn_html +
                        "</div></div></div>"
                        "<div style=\"display:flex;align-items:center;padding:0 16px;\">"
                        "<div style=\"background:" + grade_bg + ";border:1px solid " + grade_col + ";border-radius:8px;padding:6px 12px;text-align:center;min-width:48px;\">"
                        "<div style=\"color:" + grade_col + ";font-size:1.3rem;font-weight:900;font-family:system-ui;line-height:1;\">" + _grade + "</div>"
                        "<div style=\"color:" + TEXT_SEC + ";font-size:0.5rem;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;\">Grade</div>"
                        "</div></div></div></div>",
                        unsafe_allow_html=True
                    )

                # --- MAKE YOUR PICK ---
                st.markdown(
                    "<div style=\"margin:16px 0 10px;\"><h4 style=\"color:" + TEXT_SEC + ";margin:0;font-family:system-ui;"
                    "font-weight:600;text-transform:uppercase;letter-spacing:0.1em;font-size:0.72rem;\">Make Your Pick</h4></div>",
                    unsafe_allow_html=True
                )
                avail_names = [p["name"] for p in state["available_players"]]

                if recs:
                    st.markdown("**Quick Pick:**")
                    btn_cols = st.columns(min(5, len(recs)))
                    for bi, rec in enumerate(recs[:5]):
                        with btn_cols[bi]:
                            _btn_label = rec["player"] + "\n" + rec["position"] + " \u00b7 " + rec["grade"]
                            if st.button(_btn_label, key="qpick_" + str(bi) + "_" + str(pick_num), width="stretch"):
                                p_data = next((p for p in state["available_players"] if p["name"] == rec["player"]), None)
                                result = _handle_pick(state, rec["player"], pick_num, p_data)
                                if "error" not in result:
                                    st.toast("Drafted " + rec["player"], icon="\U0001f3c8")
                                    st.rerun()

                # Manual pick
                selected_player = st.selectbox(
                    "Or search all available players:",
                    options=["\u2014 Select a player \u2014"] + sorted(avail_names),
                    key="pick_select_" + str(pick_num),
                )

                # Action buttons row: Confirm, Auto-Pick (#6), Undo (#2)
                _act1, _act2, _act3 = st.columns([3, 2, 2])
                with _act1:
                    if st.button("\u2705 Confirm Pick", width="stretch", disabled=(selected_player == "\u2014 Select a player \u2014")):
                        if selected_player != "\u2014 Select a player \u2014":
                            p_data = next((p for p in state["available_players"] if p["name"] == selected_player), None)
                            result = _handle_pick(state, selected_player, pick_num, p_data)
                            if "error" in result:
                                st.error(result["error"])
                            else:
                                st.toast("Drafted " + selected_player, icon="\U0001f3c8")
                                st.rerun()
                with _act2:
                    # #6: Auto-pick (trade-down simulation)
                    if st.button("\U0001f916 Auto-Pick", width="stretch", help="Let the AI draft the best available player for you"):
                        st.session_state.undo_stack.append(save_undo_snapshot(state, st.session_state.draft_history))
                        result = make_auto_pick(state, _roster_preset())
                        if "error" not in result:
                            picked = result["picked"]
                            grade_v, _, _, _ = grade_player_adp(
                                picked["name"], picked["position"], picked["ppg"], picked["adp"],
                                result["round"], _draft_num_teams(), _draft_scoring_key(), picked,
                            )
                            st.session_state.draft_history.append({
                                "round": result["round"], "pick": pick_num,
                                "player": picked["name"], "position": picked["position"],
                                "team": picked["team"], "adp": picked["adp"],
                                "ppg": picked["ppg"], "grade": grade_v,
                            })
                            if not state.get("draft_complete"):
                                st.session_state.current_recs = get_top_recommendations(
                                    state["available_players"], state["rosters"][state["user_team"]],
                                    state["picks_made"] + 1, n=5,
                                    scoring_key=_draft_scoring_key(), num_teams=_draft_num_teams(),
                                    roster_preset=_roster_preset(),
                                )
                            else:
                                save_draft_result(st.session_state.draft_history, state["rosters"][state["user_team"]], {
                                    "num_teams": _draft_num_teams(), "scoring": _draft_scoring_key(),
                                    "format": "Snake" if state.get("snake") else "Linear",
                                    "roster_preset": _roster_preset(), "user_slot": state["user_team"],
                                })
                            st.toast("Auto-drafted " + picked["name"], icon="\U0001f916")
                            st.rerun()
                with _act3:
                    # #2: Undo
                    if st.button("\u21a9 Undo", width="stretch",
                                 disabled=len(st.session_state.undo_stack) == 0,
                                 help="Undo last pick"):
                        if st.session_state.undo_stack:
                            snapshot = st.session_state.undo_stack.pop()
                            st.session_state.draft_state, st.session_state.draft_history = restore_undo_snapshot(snapshot)
                            state = st.session_state.draft_state
                            st.session_state.current_recs = get_top_recommendations(
                                state["available_players"], state["rosters"][state["user_team"]],
                                state["picks_made"] + 1, n=5,
                                scoring_key=_draft_scoring_key(), num_teams=_draft_num_teams(),
                                roster_preset=_roster_preset(),
                            )
                            st.toast("Pick undone", icon="\u21a9")
                            st.rerun()

                # --- LIKELY GONE BEFORE NEXT PICK (#6 trade awareness) ---
                likely_gone = get_players_likely_gone(state, max_show=6)
                if likely_gone:
                    _picks_away = picks_until_next_turn(state)
                    with st.expander("Players likely gone before your next pick (" + str(_picks_away) + " opponent picks)", expanded=False):
                        _lg_html = ""
                        for lgp in likely_gone:
                            _lgcol = POS_COLORS.get(lgp["position"], TEXT_SEC)
                            _lg_html += (
                                "<div style=\"display:flex;align-items:center;gap:8px;padding:4px 0;border-bottom:1px solid " + BORDER + ";\">"
                                "<span style=\"color:" + _lgcol + ";font-size:0.65rem;font-weight:700;background:" + POS_COLORS_BG.get(lgp["position"], "rgba(107,114,128,0.1)") + ";"
                                "padding:1px 6px;border-radius:3px;\">" + lgp["position"] + "</span>"
                                "<span style=\"color:" + TEXT_PRI + ";font-size:0.82rem;font-weight:600;\">" + lgp["name"] + "</span>"
                                "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;margin-left:auto;\">ADP " + str(int(lgp["adp"])) + "</span></div>"
                            )
                        st.markdown(_lg_html, unsafe_allow_html=True)

                st.markdown("---")
                with st.popover("Reset Draft", help="Clear the active mock and start over"):
                    st.caption("This removes the current mock from the live session.")
                    if st.button("\U0001f5d1 Confirm Reset", width="stretch"):
                        st.session_state.draft_started = False
                        st.session_state.draft_state = None
                        st.session_state.draft_history = []
                        st.session_state.current_recs = []
                        st.session_state.undo_stack = []
                        st.rerun()

    # =========== RIGHT COLUMN: ROSTER ===========
    with col_right:
        st.markdown(
            "<div style=\"display:flex;align-items:center;gap:8px;margin-bottom:12px;\">"
            "<h3 style=\"color:" + TEXT_PRI + ";margin:0;font-family:system-ui;font-weight:700;"
            "font-size:1.2rem;letter-spacing:-0.01em;\">YOUR ROSTER</h3></div>",
            unsafe_allow_html=True
        )

        if st.session_state.draft_started and st.session_state.draft_state:
            roster = st.session_state.draft_state["rosters"][st.session_state.draft_state["user_team"]]
            _dl_sk = st.session_state.draft_state.get("scoring", "PPR")
            _dl_roster_bytes = _roster_to_csv_bytes(roster, _dl_sk)
            _dl_hist_bytes = _history_to_csv_bytes(st.session_state.draft_history)
            _dl1, _dl2 = st.columns(2)
            with _dl1:
                st.download_button(
                    label="Roster CSV",
                    data=_dl_roster_bytes,
                    file_name="drafti_roster.csv",
                    mime="text/csv",
                    width="stretch",
                    key="download_roster_csv",
                )
            with _dl2:
                st.download_button(
                    label="Pick history CSV",
                    data=_dl_hist_bytes,
                    file_name="drafti_pick_history.csv",
                    mime="text/csv",
                    width="stretch",
                    key="download_history_csv",
                    disabled=len(st.session_state.draft_history) == 0,
                )
            needs = get_positional_needs(roster, _roster_preset())

            if needs:
                _need_html = ""
                for k, v in sorted(needs.items()):
                    _npos_color = POS_COLORS.get(k, TEXT_SEC)
                    _npos_bg = POS_COLORS_BG.get(k, "rgba(107,114,128,0.08)")
                    if k in ("FLEX", "SFLEX", "BN"):
                        _npos_color = TEXT_SEC
                        _npos_bg = "rgba(107,114,128,0.08)"
                    _need_html += (
                        "<span style=\"display:inline-flex;align-items:center;gap:4px;"
                        "background:" + _npos_bg + ";color:" + _npos_color + ";"
                        "font-size:0.65rem;font-weight:700;font-family:system-ui;"
                        "padding:3px 8px;border-radius:4px;letter-spacing:0.06em;text-transform:uppercase;\">"
                        + k + "&thinsp;&times;&thinsp;" + str(v) + "</span>"
                    )
                st.markdown(
                    "<div style=\"margin-bottom:14px;\">"
                    "<div style=\"color:" + TEXT_SEC + ";font-size:0.58rem;font-family:system-ui;"
                    "text-transform:uppercase;letter-spacing:0.12em;font-weight:600;margin-bottom:6px;\">Needs</div>"
                    "<div style=\"display:flex;gap:5px;flex-wrap:wrap;\">" + _need_html + "</div></div>",
                    unsafe_allow_html=True
                )

            if roster:
                for ri, p in enumerate(roster):
                    pos_col = POS_COLORS.get(p["position"], "#6b7280")
                    pos_bg = POS_COLORS_BG.get(p["position"], "rgba(107,114,128,0.1)")
                    _pname = p["name"]
                    _ppos = p["position"]
                    _pteam = p["team"]
                    _psk = st.session_state.draft_state.get("scoring", "PPR")
                    _pppg = str(round(effective_fantasy_ppg(p["ppg"], p["position"], _psk, p), 1))
                    _pick_label = "Rd " + str(ri + 1)
                    _rphoto = _photo_img_html(_player_photo_url(p), size_px=40, border_color=BORDER)
                    _bye = BYE_WEEKS.get(_pteam)
                    _bye_tag = ""
                    if _bye:
                        _bye_tag = "<span style=\"color:" + INFO_TX + ";font-size:0.55rem;margin-left:4px;\">Bye " + str(_bye) + "</span>"
                    st.markdown(
                        "<div style=\"display:flex;align-items:center;gap:0;"
                        "background:" + CARD_BG + ";border-radius:8px;margin-bottom:4px;overflow:hidden;"
                        "border:1px solid " + BORDER + ";\">"
                        "<div style=\"width:4px;min-width:4px;align-self:stretch;background:" + pos_col + ";\"></div>"
                        "<div style=\"padding:8px 10px;min-width:38px;text-align:center;\">"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.6rem;font-family:monospace;\">" + _pick_label + "</span></div>"
                        + _rphoto +
                        "<div style=\"flex:1;padding:8px 4px;\">"
                        "<div style=\"display:flex;align-items:center;gap:6px;\">"
                        "<span style=\"color:" + TEXT_PRI + ";font-weight:600;font-size:0.85rem;font-family:system-ui;\">" + _pname + "</span>"
                        "<span style=\"color:" + pos_col + ";font-size:0.6rem;font-weight:700;"
                        "background:" + pos_bg + ";padding:1px 5px;border-radius:3px;font-family:system-ui;\">" + _ppos + "</span>"
                        + _bye_tag + "</div></div>"
                        "<div style=\"padding:8px 12px;text-align:right;white-space:nowrap;\">"
                        "<span style=\"color:" + TEXT_PRI + ";font-size:0.75rem;font-weight:600;font-family:monospace;\">" + _pppg + "</span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.6rem;margin-left:2px;\">PPG</span></div></div>",
                        unsafe_allow_html=True
                    )
            else:
                st.markdown(
                    "<div style=\"background:" + CARD_BG + ";border-radius:" + str(UI_RADIUS_MD) + "px;padding:" + str(UI_SPACE_6 + 8) + "px " + str(UI_SPACE_5 - 4) + "px;text-align:center;"
                    "border:1px dashed " + BORDER + ";\">"
                    "<div style=\"font-size:1.5rem;margin-bottom:8px;opacity:0.5;\">&#127944;</div>"
                    "<p style=\"color:" + TEXT_SEC + ";font-size:0.85rem;margin:0;\">Make your first pick to build your roster</p></div>",
                    unsafe_allow_html=True
                )

        elif not st.session_state.draft_started:
            st.markdown(
                "<div style=\"background:" + CARD_BG + ";border-radius:" + str(UI_RADIUS_MD) + "px;padding:" + str(UI_SPACE_6 + 8) + "px " + str(UI_SPACE_5 - 4) + "px;text-align:center;"
                "border:1px dashed " + BORDER + ";\">"
                "<div style=\"font-size:2rem;margin-bottom:10px;opacity:0.4;\">&#127944;</div>"
                "<p style=\"color:" + TEXT_SEC + ";font-size:0.9rem;margin:0;\">Start a mock draft to build your roster</p></div>",
                unsafe_allow_html=True
            )

        # Pick History
        if st.session_state.draft_history:
            st.markdown("<div style=\"margin-top:20px;\"></div>", unsafe_allow_html=True)
            _render_eyebrow("Pick History", margin_bottom=10)
            for ph in reversed(st.session_state.draft_history[-10:]):
                pos_col = POS_COLORS.get(ph["position"], "#6b7280")
                pos_bg = POS_COLORS_BG.get(ph["position"], "rgba(107,114,128,0.1)")
                grade_col = GRADE_COLORS.get(ph.get("grade", "F"), "#6b7280")
                grade_bg = GRADE_COLORS_BG.get(ph.get("grade", "F"), "rgba(107,114,128,0.1)")
                _ph_photo = _photo_img_html(_photo_url_for_player_name(ph["player"]), size_px=32, border_color=BORDER)
                st.markdown(
                    "<div style=\"display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid " + BORDER + ";\">"
                    "<div style=\"display:flex;align-items:center;gap:8px;\">"
                    + _ph_photo +
                    "<span style=\"color:" + TEXT_SEC + ";font-size:0.65rem;font-family:monospace;min-width:52px;\">R" + str(ph["round"]) + " #" + str(ph["pick"]) + "</span>"
                    "<span style=\"color:" + TEXT_PRI + ";font-size:0.82rem;font-weight:600;\">" + ph["player"] + "</span>"
                    "<span style=\"color:" + pos_col + ";font-size:0.58rem;font-weight:700;background:" + pos_bg + ";padding:1px 5px;border-radius:3px;\">" + ph["position"] + "</span></div>"
                    "<span style=\"color:" + grade_col + ";font-size:0.75rem;font-weight:800;background:" + grade_bg + ";padding:2px 8px;border-radius:4px;\">" + ph.get("grade", "?") + "</span></div>",
                    unsafe_allow_html=True
                )


# ===========================================================================
# SCREEN 2: PLAYER POOL BROWSER
# ===========================================================================
with tab_pool:
    _render_theme_toggle("pool")
    _render_section_header(
        "PLAYER POOL",
        str(len(DRAFT_PLAYER_POOL)) + " players &middot; 2025 Sleeper ADP &middot; "
        + html.escape(st.session_state.league_scoring) + " view",
    )
    _pool_source = st.session_state.get("player_pool_source", "embedded fallback")
    _pool_status = st.session_state.get("player_pool_status", "")
    _pool_updated = st.session_state.get("player_pool_last_updated", "Unknown")
    _render_context_chips([
        ("Scoring", st.session_state.get("league_scoring", "PPR")),
        ("Pool source", _pool_source),
    ])

    _pool_meta_col, _pool_action_col = st.columns([4, 1])
    with _pool_meta_col:
        st.caption("Source: " + _pool_source + " | Last sync: " + _pool_updated)
    with _pool_action_col:
        if st.button("Live Update from Sleeper", key="pool_live_update"):
            base_pool = load_player_pool_from_file(PLAYER_POOL_FALLBACK_PATH) or load_player_pool_from_file(DEFAULT_PLAYERS_PATH) or []
            try:
                with st.status("Syncing from Sleeper API...", expanded=True) as _sync_st:
                    _sync_st.write("Downloading NFL player metadata...")
                    updated_pool = _fetch_live_player_pool(base_pool)
                    _sync_st.write("Saving merged pool...")
                    save_player_pool_to_file(updated_pool, PLAYER_POOL_FALLBACK_PATH)
                    st.session_state.player_pool = updated_pool
                    st.session_state.player_pool_source = "Sleeper live data + players.json"
                    st.session_state.player_pool_last_updated = utc_timestamp()
                    st.session_state.player_pool_status = "Live update succeeded."
                    _sync_st.update(label="Sleeper sync complete", state="complete", expanded=False)
                st.toast("Player pool updated from Sleeper.", icon="\u2705")
                st.rerun()
            except (HTTPError, URLError, ValueError, OSError) as exc:
                fallback_pool = load_player_pool_from_file(PLAYER_POOL_FALLBACK_PATH) or load_player_pool_from_file(DEFAULT_PLAYERS_PATH) or []
                st.session_state.player_pool = fallback_pool
                st.session_state.player_pool_source = "fallback"
                st.session_state.player_pool_last_updated = utc_timestamp()
                st.session_state.player_pool_status = "Sleeper update failed (" + str(exc) + ")."
                st.toast("Sleeper sync failed; using fallback.", icon="\u26a0\ufe0f")
                st.rerun()

    if _pool_status:
        if "failed" in _pool_status.lower():
            st.warning(_pool_status)
        elif _pool_status.startswith("Loaded"):
            st.info(_pool_status)
        else:
            st.success(_pool_status)

    _render_pool_browser_fragment()


# ===========================================================================
# SCREEN 3: PLAYER LOOKUP
# ===========================================================================
with tab_lookup:
    _render_theme_toggle("lookup")
    _render_section_header(
        "PLAYER LOOKUP",
        "Get projected PPG, ADP analysis, strength of schedule, and draft grades for any player.",
    )
    _render_context_chips([
        ("Scoring", st.session_state.get("league_scoring", "PPR")),
        ("Teams", _draft_num_teams()),
        ("Roster", _roster_preset()),
    ])
    _render_lookup_fragment()


# ===========================================================================
# SCREEN 4: DRAFT HISTORY (#8)
# ===========================================================================
with tab_history:
    _render_theme_toggle("history")
    past_results = load_draft_results()
    _render_section_header(
        "DRAFT HISTORY",
        "Track your drafting tendencies and improve your strategy across multiple mocks.",
    )
    _render_context_chips([
        ("Saved drafts", len(past_results)),
        ("Current scoring", st.session_state.get("league_scoring", "PPR")),
    ])
    trends = get_draft_trends(past_results)

    if not past_results:
        st.markdown(
            "<div style=\"background:" + CARD_BG + ";border-radius:12px;padding:40px 20px;text-align:center;"
            "border:1px dashed " + BORDER + ";\">"
            "<div style=\"font-size:2rem;margin-bottom:10px;opacity:0.4;\">&#128202;</div>"
            "<p style=\"color:" + TEXT_SEC + ";font-size:0.9rem;margin:0;\">Complete a mock draft to see your history and trends here.</p></div>",
            unsafe_allow_html=True
        )
    else:
        # Trend metrics
        if trends:
            tc1, tc2, tc3 = st.columns(3)
            with tc1:
                st.metric("Total Drafts", trends["total_drafts"])
            with tc2:
                # Map avg grade value back to letter
                _avg_g = trends["avg_draft_grade"]
                _avg_letter = "F"
                for val, letter in sorted([(v, k) for k, v in GRADE_VALUES.items()], reverse=True):
                    if _avg_g >= val - 0.5:
                        _avg_letter = letter
                        break
                st.metric("Avg Draft Grade", _avg_letter)
            with tc3:
                _first_pos = trends["avg_pos_round"]
                _earliest = min(_first_pos.items(), key=lambda x: x[1]) if _first_pos else ("--", 0)
                st.metric("Earliest Pos (Avg)", _earliest[0] + " Rd " + str(_earliest[1]))

            # Most Drafted Players
            st.markdown("<div style=\"margin-top:16px;\"></div>", unsafe_allow_html=True)
            _render_eyebrow("Most Drafted Players", margin_bottom=8)
            if trends["most_drafted"]:
                _md_rows = []
                for i, (name, count) in enumerate(trends["most_drafted"][:8]):
                    _pct = int(count / max(trends["total_drafts"], 1) * 100)
                    _md_rows.append({"#": i + 1, "Player": name, "Times": count, "% of mocks": _pct})
                _md_df = pd.DataFrame(_md_rows)
                st.dataframe(
                    _md_df,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "#": st.column_config.NumberColumn("#", format="%d", width="small"),
                        "Player": st.column_config.TextColumn("Player", width="large"),
                        "Times": st.column_config.NumberColumn("Times drafted", format="%d"),
                        "% of mocks": st.column_config.NumberColumn("% of mocks", format="%d"),
                    },
                )
            else:
                _empty_table_state("No drafted player names recorded yet — complete a mock with picks.")

            # Avg round per position
            st.markdown("<div style=\"margin-top:16px;\"></div>", unsafe_allow_html=True)
            _render_eyebrow("Avg Round by Position", margin_bottom=8)
            _ap_html = ""
            for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
                avg_rd = trends["avg_pos_round"].get(pos, "--")
                _pcol = POS_COLORS.get(pos, TEXT_SEC)
                _ap_html += (
                    "<div style=\"background:" + CARD_BG + ";border-radius:8px;padding:12px;text-align:center;border:1px solid " + BORDER + ";\">"
                    "<div style=\"color:" + _pcol + ";font-size:1.2rem;font-weight:900;\">" + str(avg_rd) + "</div>"
                    "<div style=\"color:" + _pcol + ";font-size:0.6rem;font-weight:700;text-transform:uppercase;letter-spacing:0.1em;margin-top:2px;\">" + pos + "</div></div>"
                )
            st.markdown("<div style=\"display:grid;grid-template-columns:repeat(6,1fr);gap:8px;\">" + _ap_html + "</div>", unsafe_allow_html=True)

        # Recent drafts list
        st.markdown("<div style=\"margin-top:20px;\"></div>", unsafe_allow_html=True)
        _render_eyebrow("Recent Drafts", margin_bottom=8)
        _recent_rows = []
        for draft in reversed(past_results[-10:]):
            settings = draft.get("settings", {})
            history = draft.get("history", [])
            grades = [GRADE_VALUES.get(p.get("grade", "F"), 1) for p in history]
            avg_g = sum(grades) / max(len(grades), 1) if grades else 0
            _g_letter = "F"
            for val, letter in sorted([(v, k) for k, v in GRADE_VALUES.items()], reverse=True):
                if avg_g >= val - 0.5:
                    _g_letter = letter
                    break
            _ts = draft.get("timestamp", "Unknown")
            _fmt = str(settings.get("num_teams", "?")) + "-team " + settings.get("scoring", "?") + " " + settings.get("roster_preset", "Standard")
            _recent_rows.append({
                "League": _fmt,
                "When": _ts,
                "Grade": _g_letter,
                "Picks": len(history),
            })
        if _recent_rows:
            _recent_df = pd.DataFrame(_recent_rows)
            st.dataframe(
                _recent_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "League": st.column_config.TextColumn("League", width="large"),
                    "When": st.column_config.TextColumn("When", width="medium"),
                    "Grade": st.column_config.TextColumn("Grade", width="small"),
                    "Picks": st.column_config.NumberColumn("Picks", format="%d"),
                },
            )
        else:
            _empty_table_state("No saved drafts in history yet.")
