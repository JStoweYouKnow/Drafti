import streamlit as st
import copy
import random
import re
import math
import json

# ─────────────────────────────────────────────────────────────────────────────
# -- THEME PALETTES --
# ─────────────────────────────────────────────────────────────────────────────
THEMES = {
    "dark": {
        "BG":         "#0f0f12",
        "PANEL_BG":   "#141418",
        "TEXT_PRI":   "#f0f0f5",
        "TEXT_SEC":   "#9a9aaa",
        "GRID_LINE":  "#2e2e3a",
        "BORDER":     "#2e2e3a",
        "APP_BG":     "#0f0f12",
        "HDR_BG1":    "#141418",
        "HDR_BG2":    "#1c1c24",
        "CARD_BG":    "#141418",
        "STAT_BG":    "#1c1c24",
    },
    "light": {
        "BG":         "#f5f5f7",
        "PANEL_BG":   "#ffffff",
        "TEXT_PRI":   "#1a1a22",
        "TEXT_SEC":   "#5a5a6a",
        "GRID_LINE":  "#e0e0e8",
        "BORDER":     "#d8d8e2",
        "APP_BG":     "#f5f5f7",
        "HDR_BG1":    "#ffffff",
        "HDR_BG2":    "#f0f0f8",
        "CARD_BG":    "#ffffff",
        "STAT_BG":    "#f0f0f8",
    },
}

ACCENT_GOLD = "#ffd400"
ACCENT_GRN  = "#22c97a"
ACCENT_RED  = "#f04438"

POS_COLORS = {
    "QB":  "#D0BBFF",
    "RB":  "#8DE5A1",
    "WR":  "#A1C9F4",
    "TE":  "#FFB482",
    "K":   "#F7B6D2",
    "DEF": "#FF9F9B",
}

GRADE_COLORS = {
    "A+": "#22c97a", "A": "#22c97a", "A-": "#3dd68c",
    "B+": "#a6e3a1", "B": "#a6e3a1", "B-": "#d9f99d",
    "C+": "#ffd400", "C": "#ffd400", "C-": "#facc15",
    "D+": "#fb923c", "D": "#fb923c",
    "F":  "#f04438", "N/A": "#9a9aaa",
}

# ─────────────────────────────────────────────────────────────────────────────
# -- STREAMLIT PAGE CONFIG (must be first st call) --
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="\U0001f3c8 Fantasy Draft Simulator",
    page_icon="\U0001f3c8",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────────────────────────────────────
# -- SESSION STATE INIT --
# ─────────────────────────────────────────────────────────────────────────────
if "theme" not in st.session_state:
    st.session_state.theme = "dark"
if "draft_state" not in st.session_state:
    st.session_state.draft_state        = None
if "draft_history" not in st.session_state:
    st.session_state.draft_history      = []
if "draft_started" not in st.session_state:
    st.session_state.draft_started      = False
if "current_recs" not in st.session_state:
    st.session_state.current_recs       = []
if "last_pick_result" not in st.session_state:
    st.session_state.last_pick_result   = None

# ─────────────────────────────────────────────────────────────────────────────
# -- ACTIVE THEME --
# ─────────────────────────────────────────────────────────────────────────────
_T = THEMES[st.session_state.theme]
BG       = _T["BG"]
PANEL_BG = _T["PANEL_BG"]
TEXT_PRI = _T["TEXT_PRI"]
TEXT_SEC = _T["TEXT_SEC"]
GRID_LINE = _T["GRID_LINE"]
BORDER    = _T["BORDER"]

# ─────────────────────────────────────────────────────────────────────────────
# -- CSS injection (theme-aware) --
# ─────────────────────────────────────────────────────────────────────────────
_btn_hover_border = ACCENT_GOLD
_btn_bg    = "#2e2e3a" if st.session_state.theme == "dark" else "#e8e8f0"
_btn_hover = "#3a3a4a" if st.session_state.theme == "dark" else "#d8d8e8"
_df_bg     = PANEL_BG
_sidebar_bg = PANEL_BG

st.markdown(f"""
<style>
@import url(\'https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=DM+Mono:wght@400;500&family=Barlow:wght@400;500;600;700&display=swap\');

html, body, [class*="css"] {{
    font-family: \'Barlow\', sans-serif;
}}
.stApp {{ background-color: {BG}; color: {TEXT_PRI}; }}
.block-container {{ padding-top: 1rem; padding-bottom: 1rem; }}
div[data-testid="stMetricValue"] {{ color: {TEXT_PRI}; font-size: 1.4rem; font-weight: 700; font-family: \'Barlow Condensed\', sans-serif; }}
div[data-testid="stMetricLabel"] {{ color: {TEXT_SEC}; font-size: 0.75rem; }}
.stSelectbox label, .stTextInput label, .stSlider label {{ color: {TEXT_SEC}; }}
.stButton > button {{
    background-color: {_btn_bg};
    color: {TEXT_PRI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-weight: 600;
    font-family: \'Barlow\', sans-serif;
    transition: all 0.2s;
}}
.stButton > button:hover {{ background-color: {_btn_hover}; border-color: {ACCENT_GOLD}; color: {ACCENT_GOLD}; }}
.stTabs [data-baseweb="tab"] {{ color: {TEXT_SEC}; font-family: \'Barlow\', sans-serif; }}
.stTabs [aria-selected="true"] {{ color: {TEXT_PRI}; border-bottom: 2px solid {ACCENT_GOLD}; }}
div[data-testid="stDataFrame"] {{ background-color: {_df_bg}; }}
.css-1d391kg {{ background-color: {_df_bg}; }}
hr {{ border-color: {BORDER}; }}
code, .stCode {{ font-family: \'DM Mono\', monospace; }}
p, li, span {{ color: {TEXT_PRI}; }}
h1, h2, h3, h4, h5, h6 {{ color: {TEXT_PRI}; }}
</style>
""", unsafe_allow_html=True)
DRAFT_PLAYER_POOL = [
  {
    "name": "Christian McCaffrey",
    "position": "RB",
    "team": "SF",
    "adp": 1.4,
    "ppg": 23.17
  },
  {
    "name": "De'Von Achane",
    "position": "RB",
    "team": "MIA",
    "adp": 3.2,
    "ppg": 20.9
  },
  {
    "name": "Jonathan Taylor",
    "position": "RB",
    "team": "IND",
    "adp": 7.0,
    "ppg": 19.95
  },
  {
    "name": "Ja'Marr Chase",
    "position": "WR",
    "team": "CIN",
    "adp": 10.4,
    "ppg": 18.19
  },
  {
    "name": "Greg Olsen",
    "position": "TE",
    "team": "FA",
    "adp": 30.2,
    "ppg": 0.0
  },
  {
    "name": "Ladd McConkey",
    "position": "WR",
    "team": "LAC",
    "adp": 32.8,
    "ppg": 14.53
  },
  {
    "name": "Javonte Williams",
    "position": "RB",
    "team": "DAL",
    "adp": 33.0,
    "ppg": 15.74
  },
  {
    "name": "Tetairoa McMillan",
    "position": "WR",
    "team": "CAR",
    "adp": 35.3,
    "ppg": 14.32
  },
  {
    "name": "George Pickens",
    "position": "WR",
    "team": "DAL",
    "adp": 41.1,
    "ppg": 14.15
  },
  {
    "name": "Chris Olave",
    "position": "WR",
    "team": "NO",
    "adp": 41.3,
    "ppg": 13.96
  },
  {
    "name": "Chase Brown",
    "position": "RB",
    "team": "CIN",
    "adp": 44.0,
    "ppg": 14.64
  },
  {
    "name": "Tyler Warren",
    "position": "TE",
    "team": "IND",
    "adp": 44.3,
    "ppg": 12.4
  },
  {
    "name": "Patrick Mahomes",
    "position": "QB",
    "team": "KC",
    "adp": 46.0,
    "ppg": 22.84
  },
  {
    "name": "Courtland Sutton",
    "position": "WR",
    "team": "DEN",
    "adp": 46.2,
    "ppg": 13.46
  },
  {
    "name": "Jaylen Waddle",
    "position": "WR",
    "team": "MIA",
    "adp": 50.9,
    "ppg": 13.33
  },
  {
    "name": "Alvin Kamara",
    "position": "RB",
    "team": "NO",
    "adp": 52.0,
    "ppg": 13.65
  },
  {
    "name": "J.K. Dobbins",
    "position": "RB",
    "team": "DEN",
    "adp": 56.6,
    "ppg": 13.16
  },
  {
    "name": "Travis Kelce",
    "position": "TE",
    "team": "KC",
    "adp": 57.1,
    "ppg": 11.23
  },
  {
    "name": "Cole Hikutini",
    "position": "TE",
    "team": "FA",
    "adp": 57.8,
    "ppg": 0.0
  },
  {
    "name": "Tee Higgins",
    "position": "WR",
    "team": "CIN",
    "adp": 60.4,
    "ppg": 12.54
  },
  {
    "name": "Michael Pittman",
    "position": "WR",
    "team": "IND",
    "adp": 62.6,
    "ppg": 12.56
  },
  {
    "name": "Keenan Allen",
    "position": "WR",
    "team": "LAC",
    "adp": 62.8,
    "ppg": 12.5
  },
  {
    "name": "Jake Ferguson",
    "position": "TE",
    "team": "DAL",
    "adp": 64.1,
    "ppg": 11.09
  },
  {
    "name": "Dak Prescott",
    "position": "QB",
    "team": "DAL",
    "adp": 68.2,
    "ppg": 21.18
  },
  {
    "name": "Justin Herbert",
    "position": "QB",
    "team": "LAC",
    "adp": 69.1,
    "ppg": 21.01
  },
  {
    "name": "Stefon Diggs",
    "position": "WR",
    "team": "NE",
    "adp": 69.3,
    "ppg": 12.26
  },
  {
    "name": "Tony Pollard",
    "position": "RB",
    "team": "TEN",
    "adp": 72.0,
    "ppg": 12.2
  },
  {
    "name": "Drake Maye",
    "position": "QB",
    "team": "NE",
    "adp": 75.1,
    "ppg": 20.82
  },
  {
    "name": "Wan'Dale Robinson",
    "position": "WR",
    "team": "NYG",
    "adp": 78.4,
    "ppg": 11.61
  },
  {
    "name": "Bo Nix",
    "position": "QB",
    "team": "DEN",
    "adp": 83.1,
    "ppg": 20.23
  },
  {
    "name": "Hunter Henry",
    "position": "TE",
    "team": "NE",
    "adp": 83.4,
    "ppg": 9.68
  },
  {
    "name": "Rashid Shaheed",
    "position": "WR",
    "team": "NO",
    "adp": 90.7,
    "ppg": 10.87
  },
  {
    "name": "Zach Ertz",
    "position": "TE",
    "team": "WAS",
    "adp": 91.4,
    "ppg": 9.36
  },
  {
    "name": "Jacory Croskey-Merritt",
    "position": "RB",
    "team": "WAS",
    "adp": 91.4,
    "ppg": 11.53
  },
  {
    "name": "Juwan Johnson",
    "position": "TE",
    "team": "NO",
    "adp": 91.4,
    "ppg": 9.28
  },
  {
    "name": "Daniel Jones",
    "position": "QB",
    "team": "IND",
    "adp": 98.1,
    "ppg": 19.37
  },
  {
    "name": "TreVeyon Henderson",
    "position": "RB",
    "team": "NE",
    "adp": 101.7,
    "ppg": 10.65
  },
  {
    "name": "Tua Tagovailoa",
    "position": "QB",
    "team": "MIA",
    "adp": 114.0,
    "ppg": 18.54
  },
  {
    "name": "Elic Ayomanor",
    "position": "WR",
    "team": "TEN",
    "adp": 115.8,
    "ppg": 9.4
  },
  {
    "name": "Bijan Robinson",
    "position": "RB",
    "team": "ATL",
    "adp": 116.1,
    "ppg": 20.03
  },
  {
    "name": "Jahmyr Gibbs",
    "position": "RB",
    "team": "DET",
    "adp": 116.6,
    "ppg": 19.37
  },
  {
    "name": "Chig Okonkwo",
    "position": "TE",
    "team": "TEN",
    "adp": 118.9,
    "ppg": 7.69
  },
  {
    "name": "Jaxon Smith-Njigba",
    "position": "WR",
    "team": "SEA",
    "adp": 120.4,
    "ppg": 18.69
  },
  {
    "name": "Saquon Barkley",
    "position": "RB",
    "team": "PHI",
    "adp": 121.0,
    "ppg": 17.97
  },
  {
    "name": "Amon-Ra St. Brown",
    "position": "WR",
    "team": "DET",
    "adp": 121.3,
    "ppg": 18.06
  },
  {
    "name": "Marquise Brown",
    "position": "WR",
    "team": "KC",
    "adp": 121.9,
    "ppg": 8.88
  },
  {
    "name": "Rico Dowdle",
    "position": "RB",
    "team": "CAR",
    "adp": 122.2,
    "ppg": 9.73
  },
  {
    "name": "Trey McBride",
    "position": "TE",
    "team": "ARI",
    "adp": 124.1,
    "ppg": 15.57
  },
  {
    "name": "Josh Jacobs",
    "position": "RB",
    "team": "GB",
    "adp": 124.6,
    "ppg": 17.68
  },
  {
    "name": "Justin Jefferson",
    "position": "WR",
    "team": "MIN",
    "adp": 126.3,
    "ppg": 16.71
  },
  {
    "name": "Derrick Henry",
    "position": "RB",
    "team": "BAL",
    "adp": 128.6,
    "ppg": 16.95
  },
  {
    "name": "James Cook",
    "position": "RB",
    "team": "BUF",
    "adp": 130.0,
    "ppg": 16.88
  },
  {
    "name": "Josh Allen",
    "position": "QB",
    "team": "BUF",
    "adp": 130.1,
    "ppg": 25.15
  },
  {
    "name": "Theo Johnson",
    "position": "TE",
    "team": "NYG",
    "adp": 132.6,
    "ppg": 7.07
  },
  {
    "name": "Kyren Williams",
    "position": "RB",
    "team": "LAR",
    "adp": 134.1,
    "ppg": 16.2
  },
  {
    "name": "Ashton Jeanty",
    "position": "RB",
    "team": "LV",
    "adp": 134.6,
    "ppg": 16.42
  },
  {
    "name": "Troy Franklin",
    "position": "WR",
    "team": "DEN",
    "adp": 136.8,
    "ppg": 8.08
  },
  {
    "name": "Kayshon Boutte",
    "position": "WR",
    "team": "NE",
    "adp": 139.7,
    "ppg": 7.98
  },
  {
    "name": "Brian Thomas",
    "position": "WR",
    "team": "JAX",
    "adp": 139.9,
    "ppg": 14.92
  },
  {
    "name": "Davante Adams",
    "position": "WR",
    "team": "LAR",
    "adp": 140.9,
    "ppg": 14.79
  },
  {
    "name": "Kareem Hunt",
    "position": "RB",
    "team": "KC",
    "adp": 143.7,
    "ppg": 8.21
  },
  {
    "name": "DK Metcalf",
    "position": "WR",
    "team": "PIT",
    "adp": 145.2,
    "ppg": 14.2
  },
  {
    "name": "Kendrick Bourne",
    "position": "WR",
    "team": "SF",
    "adp": 145.3,
    "ppg": 7.97
  },
  {
    "name": "Zay Flowers",
    "position": "WR",
    "team": "BAL",
    "adp": 146.0,
    "ppg": 14.44
  },
  {
    "name": "RJ Harvey",
    "position": "RB",
    "team": "DEN",
    "adp": 146.2,
    "ppg": 7.93
  },
  {
    "name": "Breece Hall",
    "position": "RB",
    "team": "NYJ",
    "adp": 147.8,
    "ppg": 14.6
  },
  {
    "name": "Malik Washington",
    "position": "WR",
    "team": "MIA",
    "adp": 148.9,
    "ppg": 7.31
  },
  {
    "name": "Jalen Hurts",
    "position": "QB",
    "team": "PHI",
    "adp": 150.1,
    "ppg": 22.83
  },
  {
    "name": "Deebo Samuel",
    "position": "WR",
    "team": "WAS",
    "adp": 150.3,
    "ppg": 13.79
  },
  {
    "name": "Emeka Egbuka",
    "position": "WR",
    "team": "TB",
    "adp": 150.8,
    "ppg": 14.19
  },
  {
    "name": "Sam LaPorta",
    "position": "TE",
    "team": "DET",
    "adp": 155.0,
    "ppg": 11.79
  },
  {
    "name": "DeVonta Smith",
    "position": "WR",
    "team": "PHI",
    "adp": 159.8,
    "ppg": 13.07
  },
  {
    "name": "Rome Odunze",
    "position": "WR",
    "team": "CHI",
    "adp": 160.0,
    "ppg": 13.18
  },
  {
    "name": "Cam Ward",
    "position": "QB",
    "team": "TEN",
    "adp": 160.3,
    "ppg": 15.96
  },
  {
    "name": "Tucker Kraft",
    "position": "TE",
    "team": "GB",
    "adp": 165.1,
    "ppg": 11.18
  },
  {
    "name": "Marvin Harrison",
    "position": "WR",
    "team": "ARI",
    "adp": 166.3,
    "ppg": 12.64
  },
  {
    "name": "Baker Mayfield",
    "position": "QB",
    "team": "TB",
    "adp": 166.7,
    "ppg": 21.34
  },
  {
    "name": "Jordan Mason",
    "position": "RB",
    "team": "MIN",
    "adp": 168.6,
    "ppg": 12.96
  },
  {
    "name": "Kenneth Walker",
    "position": "RB",
    "team": "SEA",
    "adp": 170.3,
    "ppg": 12.93
  },
  {
    "name": "DJ Moore",
    "position": "WR",
    "team": "CHI",
    "adp": 170.8,
    "ppg": 12.08
  },
  {
    "name": "Jerry Jeudy",
    "position": "WR",
    "team": "CLE",
    "adp": 173.2,
    "ppg": 11.8
  },
  {
    "name": "Travis Etienne",
    "position": "RB",
    "team": "JAX",
    "adp": 178.2,
    "ppg": 12.2
  },
  {
    "name": "Jameson Williams",
    "position": "WR",
    "team": "DET",
    "adp": 179.9,
    "ppg": 11.66
  },
  {
    "name": "Younghoe Koo",
    "position": "K",
    "team": "FA",
    "adp": 180.0,
    "ppg": 0.0
  },
  {
    "name": "Dan Bailey",
    "position": "K",
    "team": "FA",
    "adp": 181.5,
    "ppg": 0.0
  },
  {
    "name": "David Montgomery",
    "position": "RB",
    "team": "DET",
    "adp": 181.6,
    "ppg": 11.9
  },
  {
    "name": "Stephen Gostkowski",
    "position": "K",
    "team": "FA",
    "adp": 183.0,
    "ppg": 0.0
  },
  {
    "name": "Justin Tucker",
    "position": "K",
    "team": "FA",
    "adp": 184.5,
    "ppg": 0.0
  },
  {
    "name": "Jared Goff",
    "position": "QB",
    "team": "DET",
    "adp": 185.2,
    "ppg": 20.2
  },
  {
    "name": "Robbie Gould",
    "position": "K",
    "team": "FA",
    "adp": 186.0,
    "ppg": 0.0
  },
  {
    "name": "Cameron Dicker",
    "position": "K",
    "team": "LAC",
    "adp": 187.5,
    "ppg": 9.72
  },
  {
    "name": "Mark Andrews",
    "position": "TE",
    "team": "BAL",
    "adp": 187.6,
    "ppg": 9.49
  },
  {
    "name": "DeMario Douglas",
    "position": "WR",
    "team": "NE",
    "adp": 187.8,
    "ppg": 5.33
  },
  {
    "name": "Texans",
    "position": "DEF",
    "team": "HOU",
    "adp": 188.0,
    "ppg": 6.93
  },
  {
    "name": "JuJu Smith-Schuster",
    "position": "WR",
    "team": "KC",
    "adp": 188.9,
    "ppg": 5.23
  },
  {
    "name": "Quinn Nordin",
    "position": "K",
    "team": "FA",
    "adp": 189.0,
    "ppg": 0.0
  },
  {
    "name": "Patriots",
    "position": "DEF",
    "team": "NE",
    "adp": 189.5,
    "ppg": 6.9
  },
  {
    "name": "Gunnar Helm",
    "position": "TE",
    "team": "TEN",
    "adp": 189.8,
    "ppg": 3.7
  },
  {
    "name": "Quentin Johnston",
    "position": "WR",
    "team": "LAC",
    "adp": 190.0,
    "ppg": 11.05
  },
  {
    "name": "Ryan Succop",
    "position": "K",
    "team": "FA",
    "adp": 190.5,
    "ppg": 0.0
  },
  {
    "name": "Ravens",
    "position": "DEF",
    "team": "BAL",
    "adp": 191.0,
    "ppg": 6.79
  },
  {
    "name": "T.J. Hockenson",
    "position": "TE",
    "team": "MIN",
    "adp": 191.4,
    "ppg": 9.33
  },
  {
    "name": "Khalil Shakir",
    "position": "WR",
    "team": "BUF",
    "adp": 191.7,
    "ppg": 10.97
  },
  {
    "name": "Cam Skattebo",
    "position": "RB",
    "team": "NYG",
    "adp": 192.0,
    "ppg": 11.83
  },
  {
    "name": "Alex Kessman",
    "position": "K",
    "team": "CAR",
    "adp": 192.0,
    "ppg": 0.0
  },
  {
    "name": "Tommy Tremble",
    "position": "TE",
    "team": "CAR",
    "adp": 192.1,
    "ppg": 3.72
  },
  {
    "name": "Noah Gray",
    "position": "TE",
    "team": "KC",
    "adp": 192.2,
    "ppg": 3.59
  },
  {
    "name": "Jeremy McNichols",
    "position": "RB",
    "team": "WAS",
    "adp": 192.4,
    "ppg": 5.73
  },
  {
    "name": "Steelers",
    "position": "DEF",
    "team": "PIT",
    "adp": 192.5,
    "ppg": 7.15
  },
  {
    "name": "Andrei Iosivas",
    "position": "WR",
    "team": "CIN",
    "adp": 193.2,
    "ppg": 4.91
  },
  {
    "name": "Tyler Bass",
    "position": "K",
    "team": "BUF",
    "adp": 193.5,
    "ppg": 0.0
  },
  {
    "name": "Colts",
    "position": "DEF",
    "team": "IND",
    "adp": 194.0,
    "ppg": 6.87
  },
  {
    "name": "Jordan Love",
    "position": "QB",
    "team": "GB",
    "adp": 194.3,
    "ppg": 19.61
  },
  {
    "name": "Ollie Gordon",
    "position": "RB",
    "team": "MIA",
    "adp": 194.6,
    "ppg": 5.4
  },
  {
    "name": "Tucker McCann",
    "position": "K",
    "team": "FA",
    "adp": 195.0,
    "ppg": 0.0
  },
  {
    "name": "Cardinals",
    "position": "DEF",
    "team": "ARI",
    "adp": 195.5,
    "ppg": 6.65
  },
  {
    "name": "Harold Fannin",
    "position": "TE",
    "team": "CLE",
    "adp": 196.3,
    "ppg": 8.83
  },
  {
    "name": "Charlie Smyth",
    "position": "K",
    "team": "NO",
    "adp": 196.5,
    "ppg": 0.0
  },
  {
    "name": "Seahawks",
    "position": "DEF",
    "team": "SEA",
    "adp": 197.0,
    "ppg": 6.84
  },
  {
    "name": "Keon Coleman",
    "position": "WR",
    "team": "BUF",
    "adp": 197.1,
    "ppg": 10.37
  },
  {
    "name": "Chris Boswell",
    "position": "K",
    "team": "PIT",
    "adp": 198.0,
    "ppg": 8.93
  },
  {
    "name": "Jalen Tolbert",
    "position": "WR",
    "team": "DAL",
    "adp": 198.2,
    "ppg": 5.04
  },
  {
    "name": "Raiders",
    "position": "DEF",
    "team": "LV",
    "adp": 198.5,
    "ppg": 5.97
  },
  {
    "name": "Rachaad White",
    "position": "RB",
    "team": "WAS",
    "adp": 199.0,
    "ppg": 12.1
  },
  {
    "name": "Jaylin Lane",
    "position": "WR",
    "team": "WAS",
    "adp": 199.1,
    "ppg": 4.86
  },
  {
    "name": "Sam Ficken",
    "position": "K",
    "team": "FA",
    "adp": 199.5,
    "ppg": 0.0
  },
  {
    "name": "Brandin Cooks",
    "position": "WR",
    "team": "NO",
    "adp": 199.8,
    "ppg": 4.58
  },
  {
    "name": "Jets",
    "position": "DEF",
    "team": "NYJ",
    "adp": 200.0,
    "ppg": 6.15
  },
  {
    "name": "Kyle Pitts",
    "position": "TE",
    "team": "ATL",
    "adp": 200.9,
    "ppg": 8.83
  },
  {
    "name": "Alex Quevedo",
    "position": "K",
    "team": "FA",
    "adp": 201.0,
    "ppg": 0.0
  },
  {
    "name": "Sam Darnold",
    "position": "QB",
    "team": "SEA",
    "adp": 201.4,
    "ppg": 19.21
  },
  {
    "name": "Cowboys",
    "position": "DEF",
    "team": "DAL",
    "adp": 201.5,
    "ppg": 6.26
  },
  {
    "name": "Aldrick Rosas",
    "position": "K",
    "team": "FA",
    "adp": 202.5,
    "ppg": 0.0
  },
  {
    "name": "Nick Westbrook-Ikhine",
    "position": "WR",
    "team": "MIA",
    "adp": 202.9,
    "ppg": 4.65
  },
  {
    "name": "Commanders",
    "position": "DEF",
    "team": "WAS",
    "adp": 203.0,
    "ppg": 6.42
  },
  {
    "name": "Chargers",
    "position": "DEF",
    "team": "LAC",
    "adp": 204.5,
    "ppg": 6.77
  },
  {
    "name": "Buccaneers",
    "position": "DEF",
    "team": "TB",
    "adp": 206.0,
    "ppg": 6.67
  },
  {
    "name": "Trevor Lawrence",
    "position": "QB",
    "team": "JAX",
    "adp": 206.6,
    "ppg": 18.93
  },
  {
    "name": "Caleb Williams",
    "position": "QB",
    "team": "CHI",
    "adp": 207.1,
    "ppg": 18.87
  },
  {
    "name": "Browns",
    "position": "DEF",
    "team": "CLE",
    "adp": 207.5,
    "ppg": 5.62
  },
  {
    "name": "Geno Smith",
    "position": "QB",
    "team": "LV",
    "adp": 208.0,
    "ppg": 18.89
  },
  {
    "name": "Jonnu Smith",
    "position": "TE",
    "team": "PIT",
    "adp": 208.7,
    "ppg": 8.38
  },
  {
    "name": "Falcons",
    "position": "DEF",
    "team": "ATL",
    "adp": 209.0,
    "ppg": 6.17
  },
  {
    "name": "Samaje Perine",
    "position": "RB",
    "team": "CIN",
    "adp": 210.1,
    "ppg": 5.0
  },
  {
    "name": "Dalton Schultz",
    "position": "TE",
    "team": "HOU",
    "adp": 210.3,
    "ppg": 8.31
  },
  {
    "name": "Panthers",
    "position": "DEF",
    "team": "CAR",
    "adp": 210.5,
    "ppg": 5.6
  },
  {
    "name": "Romeo Doubs",
    "position": "WR",
    "team": "GB",
    "adp": 210.9,
    "ppg": 9.75
  },
  {
    "name": "Josh Downs",
    "position": "WR",
    "team": "IND",
    "adp": 211.8,
    "ppg": 9.48
  },
  {
    "name": "Nick Chubb",
    "position": "RB",
    "team": "HOU",
    "adp": 212.3,
    "ppg": 9.86
  },
  {
    "name": "Evan Engram",
    "position": "TE",
    "team": "DEN",
    "adp": 212.9,
    "ppg": 7.96
  },
  {
    "name": "Mack Hollins",
    "position": "WR",
    "team": "NE",
    "adp": 213.0,
    "ppg": 4.21
  },
  {
    "name": "Tyquan Thornton",
    "position": "WR",
    "team": "KC",
    "adp": 214.4,
    "ppg": 4.18
  },
  {
    "name": "Austin Hooper",
    "position": "TE",
    "team": "NE",
    "adp": 214.9,
    "ppg": 2.53
  },
  {
    "name": "Luke McCaffrey",
    "position": "WR",
    "team": "WAS",
    "adp": 215.1,
    "ppg": 4.3
  },
  {
    "name": "Brian Robinson",
    "position": "RB",
    "team": "SF",
    "adp": 215.6,
    "ppg": 4.36
  },
  {
    "name": "Rhamondre Stevenson",
    "position": "RB",
    "team": "NE",
    "adp": 215.6,
    "ppg": 9.91
  },
  {
    "name": "Matthew Stafford",
    "position": "QB",
    "team": "LAR",
    "adp": 219.4,
    "ppg": 18.2
  },
  {
    "name": "Adam Trautman",
    "position": "TE",
    "team": "DEN",
    "adp": 219.8,
    "ppg": 2.39
  },
  {
    "name": "Aaron Rodgers",
    "position": "QB",
    "team": "PIT",
    "adp": 220.9,
    "ppg": 18.06
  },
  {
    "name": "Cade Otton",
    "position": "TE",
    "team": "TB",
    "adp": 221.4,
    "ppg": 7.32
  },
  {
    "name": "Chimere Dike",
    "position": "WR",
    "team": "TEN",
    "adp": 221.8,
    "ppg": 4.1
  },
  {
    "name": "Tyler Conklin",
    "position": "TE",
    "team": "LAC",
    "adp": 223.4,
    "ppg": 2.45
  },
  {
    "name": "Bryce Young",
    "position": "QB",
    "team": "CAR",
    "adp": 223.6,
    "ppg": 17.97
  },
  {
    "name": "Kenneth Gainwell",
    "position": "RB",
    "team": "PIT",
    "adp": 223.6,
    "ppg": 9.23
  },
  {
    "name": "Matthew Golden",
    "position": "WR",
    "team": "GB",
    "adp": 224.0,
    "ppg": 8.75
  },
  {
    "name": "Mason Taylor",
    "position": "TE",
    "team": "NYJ",
    "adp": 225.6,
    "ppg": 7.05
  },
  {
    "name": "Puka Nacua",
    "position": "WR",
    "team": "LAR",
    "adp": 226.8,
    "ppg": 20.04
  },
  {
    "name": "Luke Schoonmaker",
    "position": "TE",
    "team": "DAL",
    "adp": 226.8,
    "ppg": 2.09
  },
  {
    "name": "Isiah Pacheco",
    "position": "RB",
    "team": "DET",
    "adp": 227.6,
    "ppg": 9.05
  },
  {
    "name": "Joe Flacco",
    "position": "QB",
    "team": "CIN",
    "adp": 227.7,
    "ppg": 17.79
  },
  {
    "name": "Tre Tucker",
    "position": "WR",
    "team": "LV",
    "adp": 229.2,
    "ppg": 8.43
  },
  {
    "name": "Drew Sample",
    "position": "TE",
    "team": "CIN",
    "adp": 230.7,
    "ppg": 1.99
  },
  {
    "name": "Rashod Bateman",
    "position": "WR",
    "team": "BAL",
    "adp": 232.6,
    "ppg": 8.16
  },
  {
    "name": "C.J. Stroud",
    "position": "QB",
    "team": "HOU",
    "adp": 235.6,
    "ppg": 17.03
  },
  {
    "name": "Pat Freiermuth",
    "position": "TE",
    "team": "PIT",
    "adp": 236.2,
    "ppg": 6.71
  },
  {
    "name": "Nico Collins",
    "position": "WR",
    "team": "HOU",
    "adp": 236.8,
    "ppg": 16.46
  },
  {
    "name": "Luke Farrell",
    "position": "TE",
    "team": "SF",
    "adp": 237.6,
    "ppg": 1.81
  },
  {
    "name": "AJ Barner",
    "position": "TE",
    "team": "SEA",
    "adp": 238.3,
    "ppg": 6.45
  },
  {
    "name": "Marvin Mims",
    "position": "WR",
    "team": "DEN",
    "adp": 238.7,
    "ppg": 7.9
  },
  {
    "name": "Devin Singletary",
    "position": "RB",
    "team": "NYG",
    "adp": 240.8,
    "ppg": 3.6
  },
  {
    "name": "Spencer Rattler",
    "position": "QB",
    "team": "NO",
    "adp": 241.2,
    "ppg": 16.63
  },
  {
    "name": "Woody Marks",
    "position": "RB",
    "team": "HOU",
    "adp": 243.8,
    "ppg": 8.12
  },
  {
    "name": "Drake London",
    "position": "WR",
    "team": "ATL",
    "adp": 244.4,
    "ppg": 15.4
  },
  {
    "name": "Noah Fant",
    "position": "TE",
    "team": "CIN",
    "adp": 245.7,
    "ppg": 5.86
  },
  {
    "name": "Brevyn Spann-Ford",
    "position": "TE",
    "team": "DAL",
    "adp": 248.2,
    "ppg": 1.39
  },
  {
    "name": "Brashard Smith",
    "position": "RB",
    "team": "KC",
    "adp": 249.3,
    "ppg": 3.45
  },
  {
    "name": "Pat Bryant",
    "position": "WR",
    "team": "DEN",
    "adp": 250.1,
    "ppg": 2.86
  },
  {
    "name": "Van Jefferson",
    "position": "WR",
    "team": "TEN",
    "adp": 252.0,
    "ppg": 2.9
  },
  {
    "name": "A.J. Brown",
    "position": "WR",
    "team": "PHI",
    "adp": 253.4,
    "ppg": 14.16
  },
  {
    "name": "Mitchell Evans",
    "position": "TE",
    "team": "CAR",
    "adp": 254.6,
    "ppg": 1.18
  },
  {
    "name": "Jakobi Meyers",
    "position": "WR",
    "team": "LV",
    "adp": 256.0,
    "ppg": 13.89
  },
  {
    "name": "Ben Sinnott",
    "position": "TE",
    "team": "WAS",
    "adp": 257.7,
    "ppg": 1.14
  },
  {
    "name": "Tyler Allgeier",
    "position": "RB",
    "team": "ATL",
    "adp": 258.0,
    "ppg": 6.85
  },
  {
    "name": "Tre' Harris",
    "position": "WR",
    "team": "LAC",
    "adp": 259.2,
    "ppg": 2.56
  },
  {
    "name": "Sterling Shepard",
    "position": "WR",
    "team": "TB",
    "adp": 259.9,
    "ppg": 6.61
  },
  {
    "name": "Michael Wilson",
    "position": "WR",
    "team": "ARI",
    "adp": 262.6,
    "ppg": 6.29
  },
  {
    "name": "Jaylen Warren",
    "position": "RB",
    "team": "PIT",
    "adp": 263.2,
    "ppg": 13.41
  },
  {
    "name": "Drew Ogletree",
    "position": "TE",
    "team": "IND",
    "adp": 263.9,
    "ppg": 0.89
  },
  {
    "name": "Tory Horton",
    "position": "WR",
    "team": "SEA",
    "adp": 266.3,
    "ppg": 6.17
  },
  {
    "name": "Jerome Ford",
    "position": "RB",
    "team": "WAS",
    "adp": 266.6,
    "ppg": 6.53
  },
  {
    "name": "Xavier Worthy",
    "position": "WR",
    "team": "KC",
    "adp": 266.6,
    "ppg": 12.6
  },
  {
    "name": "Bhayshul Tuten",
    "position": "RB",
    "team": "JAX",
    "adp": 267.0,
    "ppg": 6.41
  },
  {
    "name": "Mo Alie-Cox",
    "position": "TE",
    "team": "IND",
    "adp": 269.3,
    "ppg": 0.73
  },
  {
    "name": "Chris Manhertz",
    "position": "TE",
    "team": "NYG",
    "adp": 270.8,
    "ppg": 0.66
  },
  {
    "name": "Jake Tonges",
    "position": "TE",
    "team": "SF",
    "adp": 271.0,
    "ppg": 4.37
  },
  {
    "name": "D'Andre Swift",
    "position": "RB",
    "team": "CHI",
    "adp": 273.0,
    "ppg": 12.77
  },
  {
    "name": "Kyle Williams",
    "position": "WR",
    "team": "NE",
    "adp": 273.3,
    "ppg": 1.86
  },
  {
    "name": "Justice Hill",
    "position": "RB",
    "team": "BAL",
    "adp": 273.7,
    "ppg": 6.1
  },
  {
    "name": "Chuba Hubbard",
    "position": "RB",
    "team": "CAR",
    "adp": 277.1,
    "ppg": 12.5
  },
  {
    "name": "Olamide Zaccheaus",
    "position": "WR",
    "team": "CHI",
    "adp": 277.2,
    "ppg": 5.45
  },
  {
    "name": "Trevor Etienne",
    "position": "RB",
    "team": "CAR",
    "adp": 277.8,
    "ppg": 2.14
  },
  {
    "name": "Justin Fields",
    "position": "QB",
    "team": "KC",
    "adp": 278.2,
    "ppg": 20.91
  }
]

# ─────────────────────────────────────────────────────────────────────────────
# DRAFT CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────
DRAFT_TOTAL_TEAMS  = 12
DRAFT_USER_TEAM    = 1
DRAFT_TOTAL_ROUNDS = 15

DRAFT_ROSTER_SLOTS = {
    "QB":   1,
    "RB":   2,
    "WR":   2,
    "TE":   1,
    "FLEX": 1,
    "K":    1,
    "DEF":  1,
    "BN":   6,
}
DRAFT_TOTAL_SLOTS = 15

VOR_BASELINE = {"QB": 18.0, "RB": 8.0, "WR": 9.0, "TE": 5.0, "K": 6.0, "DEF": 6.0}
FLEX_ELIGIBLE = {"RB", "WR", "TE"}

# ─────────────────────────────────────────────────────────────────────────────
# GRADE ENGINE
# ─────────────────────────────────────────────────────────────────────────────
_GRADE_THRESHOLDS = [
    (12.0, "A+"), (9.0, "A"), (7.0, "A-"), (5.5, "B+"), (4.0, "B"),
    (3.0, "B-"),  (2.2, "C+"), (1.5, "C"), (0.9, "C-"), (0.5, "D+"),
    (0.2, "D"),   (0.0, "F"),
]
_PPR_BUMP = {"QB": 1.0, "WR": 2.0, "TE": 2.0, "RB": 0.5, "K": 0.0, "DEF": 0.0}
_SUFFIX_RE = re.compile(r"\b(jr\.?|sr\.?|ii+|iv|v)\b", re.IGNORECASE)
_PUNCT_RE  = re.compile(r"[\'.\-]")


def _norm_name(name):
    n = str(name).lower().strip()
    n = _PUNCT_RE.sub(" ", n)
    n = _SUFFIX_RE.sub("", n)
    return re.sub(r"\s+", " ", n).strip()


def grade_player_adp(player_name, position, ppg, adp, draft_round):
    bump       = _PPR_BUMP.get(position, 0.5)
    proj_ppg   = ppg + bump
    confidence = max(0.15, 0.70 - (adp / 150.0) * 0.35)
    composite  = confidence * proj_ppg
    grade = "F"
    for thresh, g in _GRADE_THRESHOLDS:
        if composite >= thresh:
            grade = g
            break
    adp_rd  = adp / 12.0
    verdict = (
        "Great Value" if (adp_rd - draft_round) >= 1.5 else
        "Overpriced"  if (adp_rd - draft_round) <= -1.5 else
        "Fair Value"
    )
    return grade, verdict, round(proj_ppg, 2), round(confidence, 2)


# ─────────────────────────────────────────────────────────────────────────────
# DRAFT SIMULATOR FUNCTIONS
# ─────────────────────────────────────────────────────────────────────────────

def get_positional_needs(roster):
    counts = {}
    for p in roster:
        counts[p["position"]] = counts.get(p["position"], 0) + 1
    needs = {}
    for slot, max_n in [("QB", 1), ("RB", 2), ("WR", 2), ("TE", 1), ("K", 1), ("DEF", 1)]:
        rem = max(0, max_n - counts.get(slot, 0))
        if rem > 0:
            needs[slot] = rem
    flex_filled = min(1,
        max(0, counts.get("RB", 0) - DRAFT_ROSTER_SLOTS["RB"]) +
        max(0, counts.get("WR", 0) - DRAFT_ROSTER_SLOTS["WR"]) +
        max(0, counts.get("TE", 0) - DRAFT_ROSTER_SLOTS["TE"])
    )
    if flex_filled < 1:
        needs["FLEX"] = 1
    starters_filled = sum(
        min(counts.get(s, 0), DRAFT_ROSTER_SLOTS.get(s, 0))
        for s in ["QB", "RB", "WR", "TE", "K", "DEF"]
    ) + flex_filled
    bench_rem = max(0, DRAFT_ROSTER_SLOTS["BN"] - max(0, len(roster) - starters_filled))
    if bench_rem > 0:
        needs["BN"] = bench_rem
    return needs


def get_top_recommendations(available, roster, pick_number, n=3):
    needs  = get_positional_needs(roster)
    scored = []
    for p in available:
        pos  = p["position"]
        vor  = p["ppg"] - VOR_BASELINE.get(pos, 5.0)
        if pos in needs and needs[pos] >= 2:
            mult = 2.0
        elif pos in needs or (pos in FLEX_ELIGIBLE and "FLEX" in needs):
            mult = 1.5
        else:
            mult = 1.0
        scored.append((vor * mult, p))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max(n * 2, 8)]
    recs  = []
    seen  = set()
    rnd   = max(1, math.ceil(pick_number / DRAFT_TOTAL_TEAMS))
    for score, p in top:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        grade, verdict, proj_ppg, conf = grade_player_adp(p["name"], p["position"], p["ppg"], p["adp"], rnd)
        _ppos = p["position"]
        pos_ctx = "Fills: " + _ppos
        if _ppos in needs:
            s = needs[_ppos]
            pos_ctx += " (" + str(s) + " slot" + ("s" if s > 1 else "") + " remaining)"
        elif _ppos in FLEX_ELIGIBLE and "FLEX" in needs:
            pos_ctx += " (FLEX eligible)"
        else:
            pos_ctx += " (bench depth)"
        recs.append({
            "player":   p["name"],
            "position": p["position"],
            "team":     p["team"],
            "adp":      p["adp"],
            "ppg":      p["ppg"],
            "proj_ppg": proj_ppg,
            "vor":      round(score, 2),
            "grade":    grade,
            "verdict":  verdict,
            "ctx":      pos_ctx,
        })
        if len(recs) >= n:
            break
    return recs


def simulate_opponent_pick(available):
    if not available:
        return None
    window  = min(len(available), 7)
    chosen  = random.choice(available[:window])
    available.remove(chosen)
    return chosen


def advance_to_user_pick(state):
    while True:
        rnd      = state["current_round"]
        pick_in  = state["pick_in_round"]
        if rnd > DRAFT_TOTAL_ROUNDS:
            state["draft_complete"] = True
            break
        team_slot = pick_in if (rnd % 2 == 1) else (DRAFT_TOTAL_TEAMS + 1 - pick_in)
        if team_slot == DRAFT_USER_TEAM:
            break
        picked = simulate_opponent_pick(state["available_players"])
        if picked:
            state["rosters"][team_slot].append(picked)
            state["picks_made"] += 1
        pick_in += 1
        if pick_in > DRAFT_TOTAL_TEAMS:
            pick_in = 1
            state["current_round"] += 1
        state["pick_in_round"] = pick_in
        if state["current_round"] > DRAFT_TOTAL_ROUNDS:
            state["draft_complete"] = True
            break


def make_user_pick(state, player_name):
    name_lower = player_name.lower().strip()
    found = next((p for p in state["available_players"]
                  if p["name"].lower().strip() == name_lower), None)
    if found is None:
        return {"error": "Player \'" + player_name + "\' not available or already drafted."}
    state["available_players"].remove(found)
    state["rosters"][DRAFT_USER_TEAM].append(found)
    state["picks_made"] += 1
    round_now = state["current_round"]
    nxt = state["pick_in_round"] + 1
    if nxt > DRAFT_TOTAL_TEAMS:
        nxt = 1
        state["current_round"] += 1
    state["pick_in_round"] = nxt
    advance_to_user_pick(state)
    user_roster = state["rosters"][DRAFT_USER_TEAM]
    next_pick   = state["picks_made"] + 1
    if state.get("draft_complete"):
        return {"picked": found, "round": round_now, "draft_complete": True, "user_roster": user_roster}
    return {
        "picked":        found,
        "round":         round_now,
        "next_pick":     next_pick,
        "next_round":    state["current_round"],
        "needs":         get_positional_needs(user_roster),
        "recs":          get_top_recommendations(state["available_players"], user_roster, next_pick),
        "user_roster":   user_roster,
    }


def init_draft_state():
    pool = copy.deepcopy(DRAFT_PLAYER_POOL)
    pool.sort(key=lambda p: p["adp"])
    state = {
        "current_round":     1,
        "pick_in_round":     1,
        "picks_made":        0,
        "draft_complete":    False,
        "available_players": pool,
        "rosters":           {t: [] for t in range(1, DRAFT_TOTAL_TEAMS + 1)},
    }
    advance_to_user_pick(state)
    return state


# ─────────────────────────────────────────────────────────────────────────────
# THEME TOGGLE HELPER
# ─────────────────────────────────────────────────────────────────────────────
def _render_theme_toggle():
    """Render a 🌙/☀️ toggle button in the top-right corner using st.columns."""
    _tc1, _tc2 = st.columns([10, 1])
    with _tc2:
        _icon = "\u2600\ufe0f" if st.session_state.theme == "dark" else "\U0001f319"
        _tip  = "Switch to Light Mode" if st.session_state.theme == "dark" else "Switch to Dark Mode"
        if st.button(_icon, key="theme_toggle_" + st.session_state.theme, help=_tip):
            st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# TABS
# ─────────────────────────────────────────────────────────────────────────────
# Re-read active theme vars (after session state init above)
_T      = THEMES[st.session_state.theme]
BG      = _T["BG"]
PANEL_BG = _T["PANEL_BG"]
TEXT_PRI = _T["TEXT_PRI"]
TEXT_SEC = _T["TEXT_SEC"]
GRID_LINE = _T["GRID_LINE"]
BORDER   = _T["BORDER"]
HDR_BG1  = _T["HDR_BG1"]
HDR_BG2  = _T["HDR_BG2"]
CARD_BG  = _T["CARD_BG"]
STAT_BG  = _T["STAT_BG"]

# ─────────────────────────────────────────────────────────────────────────────
# HEADER
# ─────────────────────────────────────────────────────────────────────────────
_hdr_col, _toggle_col = st.columns([11, 1])
with _hdr_col:
    st.markdown(
        "<div style=\"background:linear-gradient(135deg," + HDR_BG1 + " 0%," + HDR_BG2 + " 100%);"
        "border-radius:12px;padding:24px 32px;margin-bottom:16px;"
        "border:1px solid " + BORDER + ";\">"
        "<h1 style=\"color:" + TEXT_PRI + ";margin:0;font-size:2rem;font-weight:800;letter-spacing:-0.5px;font-family:\'Barlow Condensed\',sans-serif;\">"
        "\U0001f3c8 Fantasy Draft Simulator"
        "</h1>"
        "<p style=\"color:" + TEXT_SEC + ";margin:6px 0 0;font-size:0.95rem;\">"
        "2025 NFL Season &#xb7; 12-Team PPR &#xb7; Snake Draft &#xb7; 15 Rounds &#xb7; AI-Powered Recommendations"
        "</p></div>",
        unsafe_allow_html=True
    )
with _toggle_col:
    st.markdown("<div style=\"padding-top:24px;\">", unsafe_allow_html=True)
    _icon_hdr = "\u2600\ufe0f" if st.session_state.theme == "dark" else "\U0001f319"
    _tip_hdr  = "Switch to Light Mode" if st.session_state.theme == "dark" else "Switch to Dark Mode"
    if st.button(_icon_hdr, key="theme_toggle_header", help=_tip_hdr):
        st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
        st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


tab_draft, tab_pool, tab_lookup = st.tabs([
    "\U0001f3af Mock Draft Simulator",
    "\U0001f4cb Player Pool",
    "\U0001f50d Player Lookup",
])


# ═══════════════════════════════════════════════════════════════════════════════
# SCREEN 1: MOCK DRAFT SIMULATOR
# ═══════════════════════════════════════════════════════════════════════════════
with tab_draft:
    _render_theme_toggle()
    col_left, col_right = st.columns([3, 2], gap="large")

    with col_left:
        if not st.session_state.draft_started:
            st.markdown("### Start Your Mock Draft")
            _pool_size = len(DRAFT_PLAYER_POOL)
            st.markdown(
                "<div style=\"background:" + CARD_BG + ";border-radius:10px;padding:20px;border:1px solid " + BORDER + ";margin-bottom:16px;\">"
                "<h4 style=\"color:" + TEXT_PRI + ";margin:0 0 12px;\">\u2699\ufe0f League Settings</h4>"
                "<p style=\"color:" + TEXT_SEC + ";font-size:0.9rem;margin:0;\">"
                "&#x2022; <b style=\"color:" + TEXT_PRI + ";\">Format:</b> 12-team PPR Snake Draft<br>"
                "&#x2022; <b style=\"color:" + TEXT_PRI + ";\">Rounds:</b> 15 (QB&#xd7;1, RB&#xd7;2, WR&#xd7;2, TE&#xd7;1, FLEX&#xd7;1, K&#xd7;1, DEF&#xd7;1, BN&#xd7;6)<br>"
                "&#x2022; <b style=\"color:" + TEXT_PRI + ";\">Your slot:</b> Pick 1 (1st overall)<br>"
                "&#x2022; <b style=\"color:" + TEXT_PRI + ";\">Opponents:</b> ADP &#xb1;3 pick variance<br>"
                "&#x2022; <b style=\"color:" + TEXT_PRI + ";\">Pool:</b> " + str(_pool_size) + " players ranked by 2025 Sleeper ADP"
                "</p></div>",
                unsafe_allow_html=True
            )

            if st.button("Start Mock Draft", type="primary", use_container_width=True):
                st.session_state.draft_state   = init_draft_state()
                st.session_state.draft_started = True
                st.session_state.draft_history = []
                _s = st.session_state.draft_state
                _pn = _s["picks_made"] + 1
                st.session_state.current_recs = get_top_recommendations(
                    _s["available_players"], _s["rosters"][DRAFT_USER_TEAM], _pn, n=5
                )
                st.rerun()

        else:
            state = st.session_state.draft_state

            if state.get("draft_complete"):
                st.markdown(
                    "<div style=\"background:linear-gradient(135deg,#0d2818 0%,#0a1f12 100%);"
                    "border-radius:10px;padding:20px;border:1px solid #22c97a;margin-bottom:16px;\">"
                    "<h3 style=\"color:#22c97a;margin:0;\">\u2705 Draft Complete!</h3>"
                    "<p style=\"color:" + TEXT_SEC + ";margin:6px 0 0;\">Your 15-round draft is finished. Review your roster below.</p>"
                    "</div>",
                    unsafe_allow_html=True
                )
                if st.button("\U0001f504 New Draft", use_container_width=True):
                    st.session_state.draft_started      = False
                    st.session_state.draft_state        = None
                    st.session_state.draft_history      = []
                    st.session_state.current_recs       = []
                    st.session_state.last_pick_result   = None
                    st.rerun()

            else:
                pick_num   = state["picks_made"] + 1
                rnd_num    = state["current_round"]
                avail_cnt  = len(state["available_players"])
                roster     = state["rosters"][DRAFT_USER_TEAM]
                needs      = get_positional_needs(roster)

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("\U0001f4cd Overall Pick", "#" + str(pick_num))
                m2.metric("\U0001f3af Round",        str(rnd_num) + " of " + str(DRAFT_TOTAL_ROUNDS))
                m3.metric("\U0001f4e6 Available",    str(avail_cnt))
                m4.metric("\U0001f464 Roster",       str(len(roster)) + "/" + str(DRAFT_TOTAL_SLOTS))

                st.markdown("---")

                recs = st.session_state.current_recs
                if not recs:
                    recs = get_top_recommendations(
                        state["available_players"], roster, pick_num, n=5
                    )
                    st.session_state.current_recs = recs

                st.markdown("#### \U0001f3af Top Recommendations \u2014 Pick #" + str(pick_num))
                for idx, rec in enumerate(recs):
                    pos_color    = POS_COLORS.get(rec["position"], "#9a9aaa")
                    grade_col    = GRADE_COLORS.get(rec["grade"], "#9a9aaa")
                    verdict_color = ACCENT_GRN if rec["verdict"] == "Great Value" else (
                        ACCENT_RED if rec["verdict"] == "Overpriced" else "#ffd400"
                    )
                    _rank = str(idx + 1)
                    _player  = rec["player"]
                    _pos     = rec["position"]
                    _team    = rec["team"]
                    _grade   = rec["grade"]
                    _adp_str = str(int(rec["adp"]))
                    _ppg_str = str(round(rec["proj_ppg"], 1))
                    _vor_str = str(round(rec["vor"], 1))
                    _verdict = rec["verdict"]
                    _ctx     = rec["ctx"]
                    st.markdown(
                        "<div style=\"background:" + CARD_BG + ";border-radius:8px;padding:14px 16px;"
                        "border-left:3px solid " + pos_color + ";margin-bottom:8px;"
                        "border-top:1px solid " + BORDER + ";border-right:1px solid " + BORDER + ";border-bottom:1px solid " + BORDER + ";\">"
                        "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;\">"
                        "<div>"
                        "<span style=\"color:" + TEXT_PRI + ";font-weight:700;font-size:1rem;font-family:\'Barlow Condensed\',sans-serif;\">#" + _rank + " " + _player + "</span>"
                        "<span style=\"color:" + pos_color + ";font-size:0.8rem;font-weight:600;margin-left:8px;"
                        "background:rgba(128,128,128,0.12);padding:2px 7px;border-radius:4px;\">" + _pos + "</span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.8rem;margin-left:6px;\">" + _team + "</span>"
                        "</div>"
                        "<div style=\"text-align:right;\">"
                        "<span style=\"color:" + grade_col + ";font-weight:800;font-size:1.1rem;font-family:\'Barlow Condensed\',sans-serif;\">Grade: " + _grade + "</span>"
                        "</div></div>"
                        "<div style=\"margin-top:8px;display:flex;gap:16px;flex-wrap:wrap;\">"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.82rem;\">ADP: <b style=\"color:" + TEXT_PRI + ";\">" + _adp_str + "</b></span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.82rem;\">Proj PPG: <b style=\"color:" + TEXT_PRI + ";\">" + _ppg_str + "</b></span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.82rem;\">VOR: <b style=\"color:" + TEXT_PRI + ";\">" + _vor_str + "</b></span>"
                        "<span style=\"color:" + verdict_color + ";font-size:0.82rem;font-weight:600;\">" + _verdict + "</span>"
                        "</div>"
                        "<div style=\"margin-top:6px;color:" + TEXT_SEC + ";font-size:0.78rem;\">" + _ctx + "</div>"
                        "</div>",
                        unsafe_allow_html=True
                    )

                st.markdown("---")
                st.markdown("#### \u270d\ufe0f Make Your Pick")
                avail_names = [p["name"] for p in state["available_players"]]

                if recs:
                    st.markdown("**Quick Pick:**")
                    btn_cols = st.columns(min(5, len(recs)))
                    for bi, rec in enumerate(recs[:5]):
                        with btn_cols[bi]:
                            _btn_label = rec["player"] + "\n" + rec["position"] + " \u00b7 " + rec["grade"]
                            if st.button(_btn_label, key="qpick_" + str(bi) + "_" + str(pick_num), use_container_width=True):
                                result = make_user_pick(state, rec["player"])
                                if "error" not in result:
                                    st.session_state.draft_history.append({
                                        "round":    result["round"],
                                        "pick":     pick_num,
                                        "player":   rec["player"],
                                        "position": rec["position"],
                                        "team":     rec["team"],
                                        "adp":      rec["adp"],
                                        "ppg":      rec["ppg"],
                                        "grade":    rec["grade"],
                                    })
                                    if not state.get("draft_complete"):
                                        st.session_state.current_recs = get_top_recommendations(
                                            state["available_players"],
                                            state["rosters"][DRAFT_USER_TEAM],
                                            state["picks_made"] + 1,
                                            n=5,
                                        )
                                    st.rerun()

                selected_player = st.selectbox(
                    "Or search all available players:",
                    options=["\u2014 Select a player \u2014"] + sorted(avail_names),
                    key="pick_select_" + str(pick_num),
                )
                if st.button("\u2705 Confirm Pick", use_container_width=True,
                             disabled=(selected_player == "\u2014 Select a player \u2014")):
                    if selected_player != "\u2014 Select a player \u2014":
                        p_data = next((p for p in state["available_players"]
                                       if p["name"] == selected_player), None)
                        result = make_user_pick(state, selected_player)
                        if "error" in result:
                            st.error(result["error"])
                        else:
                            grade_v, _, proj_ppg_v, _ = grade_player_adp(
                                selected_player,
                                p_data["position"] if p_data else "?",
                                p_data["ppg"] if p_data else 0,
                                p_data["adp"] if p_data else 999,
                                result["round"],
                            )
                            st.session_state.draft_history.append({
                                "round":    result["round"],
                                "pick":     pick_num,
                                "player":   selected_player,
                                "position": p_data["position"] if p_data else "?",
                                "team":     p_data["team"] if p_data else "?",
                                "adp":      p_data["adp"] if p_data else 999,
                                "ppg":      p_data["ppg"] if p_data else 0,
                                "grade":    grade_v,
                            })
                            if not state.get("draft_complete"):
                                st.session_state.current_recs = get_top_recommendations(
                                    state["available_players"],
                                    state["rosters"][DRAFT_USER_TEAM],
                                    state["picks_made"] + 1,
                                    n=5,
                                )
                            st.rerun()

                st.markdown("---")
                if st.button("\U0001f504 Reset Draft", use_container_width=True):
                    st.session_state.draft_started    = False
                    st.session_state.draft_state      = None
                    st.session_state.draft_history    = []
                    st.session_state.current_recs     = []
                    st.rerun()

    with col_right:
        st.markdown("### \U0001f4cb Your Roster")
        if st.session_state.draft_started and st.session_state.draft_state:
            roster = st.session_state.draft_state["rosters"][DRAFT_USER_TEAM]
            needs  = get_positional_needs(roster)

            if roster:
                for p in roster:
                    pos_col = POS_COLORS.get(p["position"], "#9a9aaa")
                    _pname = p["name"]
                    _ppos  = p["position"]
                    _pteam = p["team"]
                    _padp  = str(int(p["adp"]))
                    _pppg  = str(round(p["ppg"], 1))
                    st.markdown(
                        "<div style=\"display:flex;justify-content:space-between;align-items:center;"
                        "background:" + CARD_BG + ";border-radius:6px;padding:9px 14px;margin-bottom:5px;"
                        "border-left:3px solid " + pos_col + ";border-right:1px solid " + BORDER + ";"
                        "border-top:1px solid " + BORDER + ";border-bottom:1px solid " + BORDER + ";\">"
                        "<div>"
                        "<span style=\"color:" + TEXT_PRI + ";font-weight:600;font-size:0.9rem;\">" + _pname + "</span>"
                        "<span style=\"color:" + pos_col + ";font-size:0.75rem;margin-left:6px;"
                        "background:rgba(128,128,128,0.12);padding:1px 6px;border-radius:3px;\">" + _ppos + "</span>"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.75rem;margin-left:5px;\">" + _pteam + "</span>"
                        "</div>"
                        "<div style=\"text-align:right;\">"
                        "<span style=\"color:" + TEXT_SEC + ";font-size:0.78rem;\">ADP " + _padp + "</span>"
                        "<span style=\"color:" + TEXT_PRI + ";font-size:0.78rem;margin-left:8px;\">" + _pppg + " PPG</span>"
                        "</div></div>",
                        unsafe_allow_html=True
                    )
            else:
                st.markdown(
                    "<p style=\"color:" + TEXT_SEC + ";font-size:0.9rem;text-align:center;padding:20px;\">Your roster is empty \u2014 make your first pick!</p>",
                    unsafe_allow_html=True
                )

            if needs:
                st.markdown("#### \U0001f4ca Needs")
                need_items = [("**" + k + "**: " + str(v) + " slot" + ("s" if v > 1 else "")) for k, v in sorted(needs.items())]
                st.markdown("  |  ".join(need_items[:4]))
                if len(need_items) > 4:
                    st.markdown("  |  ".join(need_items[4:]))

        elif not st.session_state.draft_started:
            st.markdown(
                "<div style=\"background:" + CARD_BG + ";border-radius:10px;padding:30px;text-align:center;"
                "border:1px dashed " + BORDER + ";\">"
                "<p style=\"color:" + TEXT_SEC + ";font-size:1.1rem;margin:0;\">Start a mock draft to see your roster here</p>"
                "</div>",
                unsafe_allow_html=True
            )

        if st.session_state.draft_history:
            st.markdown("#### \U0001f4dd Pick History")
            for ph in reversed(st.session_state.draft_history[-10:]):
                pos_col   = POS_COLORS.get(ph["position"], "#9a9aaa")
                grade_col = GRADE_COLORS.get(ph.get("grade", "F"), "#9a9aaa")
                _ph_player   = ph["player"]
                _ph_position = ph["position"]
                _ph_grade    = ph.get("grade", "?")
                _ph_round    = str(ph["round"])
                _ph_pick     = str(ph["pick"])
                st.markdown(
                    "<div style=\"display:flex;justify-content:space-between;align-items:center;"
                    "padding:6px 10px;border-bottom:1px solid " + BORDER + ";\">"
                    "<div>"
                    "<span style=\"color:" + TEXT_SEC + ";font-size:0.72rem;\">Rd " + _ph_round + " \u00b7 #" + _ph_pick + "</span>"
                    "<span style=\"color:" + TEXT_PRI + ";font-size:0.85rem;font-weight:600;margin-left:8px;\">" + _ph_player + "</span>"
                    "<span style=\"color:" + pos_col + ";font-size:0.72rem;margin-left:5px;\">" + _ph_position + "</span>"
                    "</div>"
                    "<span style=\"color:" + grade_col + ";font-size:0.8rem;font-weight:700;\">" + _ph_grade + "</span>"
                    "</div>",
                    unsafe_allow_html=True
                )


# ═══════════════════════════════════════════════════════════════════════════════
# SCREEN 2: PLAYER POOL BROWSER
# ═══════════════════════════════════════════════════════════════════════════════
with tab_pool:
    _render_theme_toggle()
    st.markdown("### \U0001f4cb 2025 Sleeper Player Pool")
    st.markdown(
        "<p style=\"color:" + TEXT_SEC + ";font-size:0.9rem;\">" + str(len(DRAFT_PLAYER_POOL)) +
        " players ranked by 2025 ADP \u00b7 PPR scoring \u00b7 Updated weekly projections</p>",
        unsafe_allow_html=True
    )

    import pandas as pd

    pool_df = pd.DataFrame(DRAFT_PLAYER_POOL)
    pool_df["rank"] = range(1, len(pool_df) + 1)
    pool_df = pool_df[["rank", "name", "position", "team", "adp", "ppg"]]
    pool_df.columns = ["Rank", "Player", "Pos", "Team", "ADP", "PPG (PPR)"]

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        pos_filter = st.multiselect(
            "Filter by Position",
            options=["QB", "RB", "WR", "TE", "K", "DEF"],
            default=[],
            key="pool_pos_filter"
        )
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
    mc1, mc2, mc3, mc4, mc5, mc6 = st.columns(6)
    cols_map = [mc1, mc2, mc3, mc4, mc5, mc6]
    for idx2, pos2 in enumerate(["QB", "RB", "WR", "TE", "K", "DEF"]):
        cols_map[idx2].metric(pos2, int(pos_counts.get(pos2, 0)))

    st.markdown("---")
    st.markdown("**Showing " + str(len(filtered_df)) + " of " + str(len(pool_df)) + " players**")

    def style_pos(val):
        color = POS_COLORS.get(val, "#9a9aaa")
        return "color: " + color + "; font-weight: bold;"

    styled = filtered_df.style.applymap(style_pos, subset=["Pos"]).format({
        "ADP": "{:.1f}", "PPG (PPR)": "{:.2f}"
    })
    st.dataframe(styled, use_container_width=True, height=600)


# ═══════════════════════════════════════════════════════════════════════════════
# SCREEN 3: PLAYER LOOKUP / GRADE TOOL
# ═══════════════════════════════════════════════════════════════════════════════
with tab_lookup:
    _render_theme_toggle()
    st.markdown("### \U0001f50d Player Lookup & Draft Grade")
    st.markdown(
        "<p style=\"color:" + TEXT_SEC + ";\">Enter any player from the pool to get their projected PPG, ADP, and AI-powered draft grade.</p>",
        unsafe_allow_html=True
    )

    all_names = sorted([p["name"] for p in DRAFT_PLAYER_POOL])
    lookup_name = st.selectbox(
        "Select a player",
        options=["\u2014 Select a player \u2014"] + all_names,
        key="lookup_player_select",
    )
    lookup_round = st.slider(
        "Draft Round (for value verdict)",
        min_value=1, max_value=15, value=5, step=1,
        key="lookup_round_slider",
    )

    if lookup_name != "\u2014 Select a player \u2014":
        player_data = next((p for p in DRAFT_PLAYER_POOL if p["name"] == lookup_name), None)
        if player_data:
            grade, verdict, proj_ppg, conf = grade_player_adp(
                player_data["name"],
                player_data["position"],
                player_data["ppg"],
                player_data["adp"],
                lookup_round,
            )

            pos_col     = POS_COLORS.get(player_data["position"], "#9a9aaa")
            grade_col   = GRADE_COLORS.get(grade, "#9a9aaa")
            verdict_col = (ACCENT_GRN if verdict == "Great Value" else
                           ACCENT_RED if verdict == "Overpriced" else "#ffd400")

            _pd_name     = player_data["name"]
            _pd_pos      = player_data["position"]
            _pd_team     = player_data["team"]
            _pd_adp      = str(int(player_data["adp"]))
            _pd_ppg      = str(round(proj_ppg, 1))
            _pd_rd       = str(math.ceil(player_data["adp"] / 12.0))
            _vor_base    = str(round(VOR_BASELINE.get(player_data["position"], 5.0), 1))
            _vor_val     = str(round(player_data["ppg"] - VOR_BASELINE.get(player_data["position"], 5.0), 2))
            _adp_rd_lbl  = str(math.ceil(player_data["adp"] / 12.0))
            _conf_str    = str(round(conf, 2))
            _ppr_adj     = str(_PPR_BUMP.get(player_data["position"], 0.5))

            st.markdown(
                "<div style=\"background:" + CARD_BG + ";border-radius:12px;padding:24px 28px;margin-top:12px;"
                "border-left:4px solid " + pos_col + ";"
                "border-top:1px solid " + BORDER + ";border-right:1px solid " + BORDER + ";border-bottom:1px solid " + BORDER + ";\">"
                "<div style=\"display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:16px;\">"
                "<div>"
                "<h2 style=\"color:" + TEXT_PRI + ";margin:0;font-size:1.6rem;font-weight:800;font-family:\'Barlow Condensed\',sans-serif;\">" + _pd_name + "</h2>"
                "<div style=\"margin-top:8px;\">"
                "<span style=\"color:" + pos_col + ";font-size:0.9rem;font-weight:700;"
                "background:rgba(128,128,128,0.12);padding:3px 10px;border-radius:5px;\">" + _pd_pos + "</span>"
                "<span style=\"color:" + TEXT_SEC + ";font-size:0.9rem;margin-left:10px;\">" + _pd_team + "</span>"
                "</div></div>"
                "<div style=\"text-align:center;background:" + STAT_BG + ";border-radius:10px;padding:12px 20px;\">"
                "<div style=\"color:" + grade_col + ";font-size:2.5rem;font-weight:900;line-height:1;font-family:\'Barlow Condensed\',sans-serif;\">" + grade + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.72rem;margin-top:4px;\">Draft Grade</div>"
                "</div></div>"
                "<div style=\"display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px;\">"
                "<div style=\"background:" + STAT_BG + ";border-radius:8px;padding:12px;text-align:center;\">"
                "<div style=\"color:" + TEXT_PRI + ";font-size:1.3rem;font-weight:700;font-family:\'Barlow Condensed\',sans-serif;\">" + _pd_adp + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.75rem;margin-top:2px;\">ADP Rank</div>"
                "</div>"
                "<div style=\"background:" + STAT_BG + ";border-radius:8px;padding:12px;text-align:center;\">"
                "<div style=\"color:" + TEXT_PRI + ";font-size:1.3rem;font-weight:700;font-family:\'Barlow Condensed\',sans-serif;\">" + _pd_ppg + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.75rem;margin-top:2px;\">Proj PPG (PPR)</div>"
                "</div>"
                "<div style=\"background:" + STAT_BG + ";border-radius:8px;padding:12px;text-align:center;\">"
                "<div style=\"color:" + TEXT_PRI + ";font-size:1.3rem;font-weight:700;font-family:\'Barlow Condensed\',sans-serif;\">Rd " + _pd_rd + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.75rem;margin-top:2px;\">ADP Round</div>"
                "</div>"
                "<div style=\"background:" + STAT_BG + ";border-radius:8px;padding:12px;text-align:center;\">"
                "<div style=\"color:" + verdict_col + ";font-size:0.95rem;font-weight:700;\">" + verdict + "</div>"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.75rem;margin-top:2px;\">Round " + str(lookup_round) + " Value</div>"
                "</div></div>"
                "<div style=\"background:" + STAT_BG + ";border-radius:8px;padding:14px;margin-top:4px;\">"
                "<div style=\"color:" + TEXT_SEC + ";font-size:0.75rem;font-weight:600;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;\">Analysis</div>"
                "<div style=\"color:" + TEXT_PRI + ";font-size:0.88rem;line-height:1.6;font-family:\'DM Mono\',monospace;\">"
                "<b>VOR Baseline:</b> " + _vor_base + " PPG (position replacement level)<br>"
                "<b>Value over replacement:</b> " + _vor_val + " PPG above baseline<br>"
                "<b>ADP-implied round:</b> " + _adp_rd_lbl + " vs your selected round " + str(lookup_round) + "<br>"
                "<b>Grade confidence:</b> " + _conf_str + " (ADP-decay heuristic)<br>"
                "<b>PPR adjustment:</b> +" + _ppr_adj + " PPG over standard scoring"
                "</div></div></div>",
                unsafe_allow_html=True
            )

            st.markdown("#### Similar Players by Position & ADP")
            pos_pool = [p for p in DRAFT_PLAYER_POOL
                        if p["position"] == player_data["position"] and p["name"] != player_data["name"]]
            pos_pool.sort(key=lambda p: abs(p["adp"] - player_data["adp"]))
            similar = pos_pool[:8]
            if similar:
                import pandas as pd
                sim_df = pd.DataFrame(similar)[["name","team","adp","ppg"]]
                sim_df.columns = ["Player","Team","ADP","PPG"]
                sim_df["ADP"] = sim_df["ADP"].round(1)
                sim_df["PPG"] = sim_df["PPG"].round(2)
                st.dataframe(sim_df, use_container_width=True, hide_index=True)
        else:
            st.warning("Player \'" + lookup_name + "\' not found in the pool.")

    st.markdown("---")
    st.markdown("#### \U0001f4ca Pool Statistics")

    import pandas as pd
    stats_df_pool = pd.DataFrame(DRAFT_PLAYER_POOL)

    sc1, sc2 = st.columns(2)
    with sc1:
        st.markdown("**Top 10 by Projected PPG**")
        top10 = stats_df_pool[stats_df_pool["ppg"] > 0].nlargest(10, "ppg")[["name","position","team","adp","ppg"]]
        top10.columns = ["Player","Pos","Team","ADP","PPG"]
        st.dataframe(top10, use_container_width=True, hide_index=True)

    with sc2:
        st.markdown("**Best ADP Value (Top PPG Relative to ADP)**")
        stats_df2 = stats_df_pool[stats_df_pool["ppg"] > 0].copy()
        stats_df2["adp_round"] = (stats_df2["adp"] / 12.0).apply(math.ceil)
        stats_df2["vor"] = stats_df2.apply(
            lambda r: r["ppg"] - VOR_BASELINE.get(r["position"], 5.0), axis=1
        )
        top_vor = stats_df2.nlargest(10, "vor")[["name","position","team","adp","ppg","vor"]]
        top_vor.columns = ["Player","Pos","Team","ADP","PPG","VOR"]
        st.dataframe(top_vor, use_container_width=True, hide_index=True)
