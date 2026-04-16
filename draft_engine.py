"""DRAFTi - Core draft simulation engine.

All draft logic, scoring, grading, and analysis lives here.
No Streamlit dependency - pure Python.
"""
import copy
import json
import math
import os
import random
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
SFLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}

ROSTER_PRESETS = {
    "Standard": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 6},
    "Superflex": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "SFLEX": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 5},
    "3 WR": {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 5},
    "No Kicker": {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 2, "DEF": 1, "BN": 6},
    "2 QB": {"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DEF": 1, "BN": 5},
}

VOR_BASELINE = {"QB": 18.0, "RB": 8.0, "WR": 9.0, "TE": 5.0, "K": 6.0, "DEF": 6.0}

GRADE_THRESHOLDS = [
    (12.0, "A+"), (9.0, "A"), (7.0, "A-"), (5.5, "B+"), (4.0, "B"),
    (3.0, "B-"),  (2.2, "C+"), (1.5, "C"), (0.9, "C-"), (0.5, "D+"),
    (0.2, "D"),   (0.0, "F"),
]

GRADE_VALUES = {
    "A+": 12, "A": 11, "A-": 10, "B+": 9, "B": 8, "B-": 7,
    "C+": 6, "C": 5, "C-": 4, "D+": 3, "D": 2, "F": 1,
}

REC_PPR_PREMIUM_EST = {"QB": 0.35, "RB": 2.75, "WR": 4.25, "TE": 3.0, "K": 0.0, "DEF": 0.0}
_TARGET_TO_REC_RATE = {"WR": 0.62, "TE": 0.65, "RB": 0.72, "QB": 0.82, "K": 0.0, "DEF": 0.0}

# 2025 NFL bye weeks
BYE_WEEKS = {
    "ARI": 14, "ATL": 11, "BAL": 14, "BUF": 12,
    "CAR": 7,  "CHI": 7,  "CIN": 10, "CLE": 9,
    "DAL": 7,  "DEN": 14, "DET": 5,  "GB": 10,
    "HOU": 14, "IND": 14, "JAX": 12, "KC": 6,
    "LV": 10,  "LAC": 5,  "LAR": 6,  "MIA": 6,
    "MIN": 12, "NE": 14,  "NO": 12,  "NYG": 11,
    "NYJ": 12, "PHI": 5,  "PIT": 9,  "SF": 9,
    "SEA": 10, "TB": 11,  "TEN": 5,  "WAS": 14,
}

# Simplified 2025 strength-of-schedule tiers
SOS_TIERS = {
    "ARI": "Easy",   "ATL": "Medium", "BAL": "Hard",   "BUF": "Hard",
    "CAR": "Easy",   "CHI": "Medium", "CIN": "Medium", "CLE": "Easy",
    "DAL": "Medium", "DEN": "Medium", "DET": "Hard",   "GB": "Medium",
    "HOU": "Hard",   "IND": "Medium", "JAX": "Easy",   "KC": "Hard",
    "LV": "Easy",    "LAC": "Medium", "LAR": "Medium", "MIA": "Medium",
    "MIN": "Medium", "NE": "Easy",    "NO": "Easy",    "NYG": "Easy",
    "NYJ": "Medium", "PHI": "Hard",   "PIT": "Hard",   "SF": "Hard",
    "SEA": "Medium", "TB": "Medium",  "TEN": "Easy",   "WAS": "Medium",
}

SOS_COLORS = {"Easy": "#10b981", "Medium": "#facc15", "Hard": "#ef4444"}

_SUFFIX_RE = re.compile(r"\b(jr\.?|sr\.?|ii+|iv|v)\b", re.IGNORECASE)
_PUNCT_RE  = re.compile(r"[\'.\-]")

DRAFT_RESULTS_PATH = "draft_results.json"
DEFAULT_PLAYERS_PATH = "default_players.json"
PLAYER_POOL_FALLBACK_PATH = "players.json"


# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------
def roster_total_slots(preset_name):
    preset = ROSTER_PRESETS.get(preset_name, ROSTER_PRESETS["Standard"])
    return sum(preset.values())


def ordinal(n):
    n = int(n)
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return str(n) + suffix


def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def norm_name(name):
    n = str(name).lower().strip()
    n = _PUNCT_RE.sub(" ", n)
    n = _SUFFIX_RE.sub("", n)
    return re.sub(r"\s+", " ", n).strip()


# ---------------------------------------------------------------------------
# PLAYER POOL VALIDATION
# ---------------------------------------------------------------------------
def validate_player_pool(raw_pool):
    validated = []
    for raw_player in raw_pool or []:
        if not isinstance(raw_player, dict):
            continue
        name = str(raw_player.get("name", "")).strip()
        position = str(raw_player.get("position", "")).strip().upper()
        team = str(raw_player.get("team") or "FA").strip().upper() or "FA"
        if not name or position not in FANTASY_POSITIONS:
            continue
        try:
            adp = float(raw_player.get("adp", 999.0))
        except (TypeError, ValueError):
            adp = 999.0
        try:
            ppg = float(raw_player.get("ppg", 0.0))
        except (TypeError, ValueError):
            ppg = 0.0
        entry = {"name": name, "position": position, "team": team, "adp": adp, "ppg": ppg}
        sid = raw_player.get("sleeper_id")
        if isinstance(sid, str) and sid.strip():
            entry["sleeper_id"] = sid.strip()
        elif isinstance(sid, (int, float)) and not isinstance(sid, bool):
            entry["sleeper_id"] = str(int(sid))
        for stat_key in ("targets", "rec"):
            if stat_key not in raw_player or raw_player[stat_key] is None:
                continue
            try:
                stat_val = float(raw_player[stat_key])
            except (TypeError, ValueError):
                continue
            if stat_val < 0:
                continue
            entry[stat_key] = stat_val
        validated.append(entry)
    validated = [p for p in validated if not (p["ppg"] == 0.0 and p["team"] == "FA")]
    validated.sort(key=lambda player: (player["adp"], player["name"]))
    return validated


def load_player_pool_from_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return validate_player_pool(payload)


def save_player_pool_to_file(player_pool, path):
    validated_pool = validate_player_pool(player_pool)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(validated_pool, f, separators=(",", ":"))


# ---------------------------------------------------------------------------
# SCORING
# ---------------------------------------------------------------------------
def _rec_per_game(player):
    if not isinstance(player, dict):
        return None
    pos = str(player.get("position", "")).strip().upper()
    if pos in ("K", "DEF"):
        return 0.0
    if "rec" in player and player["rec"] is not None:
        try:
            return max(0.0, float(player["rec"]))
        except (TypeError, ValueError):
            pass
    if "targets" in player and player["targets"] is not None:
        try:
            tgt = max(0.0, float(player["targets"]))
        except (TypeError, ValueError):
            tgt = 0.0
        if tgt <= 0:
            return None
        rate = float(_TARGET_TO_REC_RATE.get(pos, 0.62))
        return max(0.0, tgt * rate) if rate > 0 else None
    return None


def _ppr_rec_premium(player, position):
    pos_u = str(position or (player.get("position") if isinstance(player, dict) else "") or "").strip().upper()
    rpg = _rec_per_game(player if isinstance(player, dict) else {})
    if rpg is not None:
        return float(rpg)
    return float(REC_PPR_PREMIUM_EST.get(pos_u, 1.5))


def effective_fantasy_ppg(raw_ppg, position, scoring_key="PPR", player=None):
    try:
        raw = float(raw_ppg)
    except (TypeError, ValueError):
        return 0.0
    pl = player if isinstance(player, dict) else {}
    if position and not pl.get("position"):
        pl = {**pl, "position": position}
    prem = _ppr_rec_premium(pl, position)
    if scoring_key == "PPR":
        return max(0.0, raw)
    if scoring_key == "Half PPR":
        return max(0.0, raw - 0.5 * prem)
    if scoring_key == "Standard":
        return max(0.0, raw - prem)
    return max(0.0, raw)


def effective_vor_baseline(position, scoring_key="PPR"):
    pos = str(position or "").strip().upper()
    base = float(VOR_BASELINE.get(pos, 5.0))
    prem = float(REC_PPR_PREMIUM_EST.get(pos, 1.5))
    if scoring_key == "PPR":
        return max(0.0, base)
    if scoring_key == "Half PPR":
        return max(0.0, base - 0.5 * prem)
    if scoring_key == "Standard":
        return max(0.0, base - prem)
    return max(0.0, base)


def ppg_title_for_scoring_key(scoring_key):
    return {"PPR": "PPG (PPR)", "Half PPR": "PPG (Half PPR)", "Standard": "PPG (Std)"}.get(scoring_key, "PPG")


# ---------------------------------------------------------------------------
# GRADING
# ---------------------------------------------------------------------------
def grade_player_adp(player_name, position, ppg, adp, draft_round,
                     num_teams=12, scoring_key="PPR", player=None):
    proj_ppg = effective_fantasy_ppg(ppg, position, scoring_key, player)
    confidence = max(0.15, 0.70 - (adp / 150.0) * 0.35)
    composite = confidence * proj_ppg
    grade = "F"
    for thresh, g in GRADE_THRESHOLDS:
        if composite >= thresh:
            grade = g
            break
    adp_rd = adp / float(max(6, num_teams))
    verdict = (
        "Great Value" if (adp_rd - draft_round) >= 1.5 else
        "Overpriced"  if (adp_rd - draft_round) <= -1.5 else
        "Fair Value"
    )
    return grade, verdict, round(proj_ppg, 2), round(confidence, 2)


# ---------------------------------------------------------------------------
# POSITIONAL NEEDS (configurable roster)
# ---------------------------------------------------------------------------
def get_positional_needs(roster, roster_preset="Standard"):
    slots = ROSTER_PRESETS.get(roster_preset, ROSTER_PRESETS["Standard"])
    counts = {}
    for p in roster:
        counts[p["position"]] = counts.get(p["position"], 0) + 1
    needs = {}

    # Direct position slots
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        if pos not in slots:
            continue
        rem = max(0, slots[pos] - counts.get(pos, 0))
        if rem > 0:
            needs[pos] = rem

    # FLEX (RB/WR/TE overflow)
    flex_total = slots.get("FLEX", 0)
    flex_overflow = sum(max(0, counts.get(pos, 0) - slots.get(pos, 0)) for pos in FLEX_ELIGIBLE)
    flex_filled = min(flex_total, flex_overflow)
    if flex_filled < flex_total:
        needs["FLEX"] = flex_total - flex_filled

    # SFLEX (QB/RB/WR/TE overflow after FLEX)
    sflex_total = slots.get("SFLEX", 0)
    if sflex_total > 0:
        qb_overflow = max(0, counts.get("QB", 0) - slots.get("QB", 0))
        remaining_flex_overflow = max(0, flex_overflow - flex_filled)
        sflex_avail = qb_overflow + remaining_flex_overflow
        sflex_filled = min(sflex_total, sflex_avail)
        if sflex_filled < sflex_total:
            needs["SFLEX"] = sflex_total - sflex_filled
    else:
        sflex_filled = 0

    # Bench
    total_starters = sum(v for k, v in slots.items() if k != "BN")
    starters_on_roster = min(len(roster), total_starters)
    bench_used = max(0, len(roster) - starters_on_roster)
    bench_rem = max(0, slots.get("BN", 0) - bench_used)
    if bench_rem > 0:
        needs["BN"] = bench_rem

    return needs


# ---------------------------------------------------------------------------
# BYE WEEK HELPERS
# ---------------------------------------------------------------------------
def get_bye_week_conflicts(roster, candidate_team):
    candidate_bye = BYE_WEEKS.get(candidate_team)
    if not candidate_bye:
        return 0
    return sum(1 for p in roster if BYE_WEEKS.get(p["team"]) == candidate_bye)


def get_roster_bye_analysis(roster):
    bye_counts = {}
    for p in roster:
        bye = BYE_WEEKS.get(p["team"])
        if bye:
            if bye not in bye_counts:
                bye_counts[bye] = []
            bye_counts[bye].append(p["name"])
    conflicts = {k: v for k, v in bye_counts.items() if len(v) >= 3}
    return bye_counts, conflicts


# ---------------------------------------------------------------------------
# POSITIONAL SCARCITY
# ---------------------------------------------------------------------------
def get_positional_scarcity(available, scoring_key="PPR"):
    scarcity = {}
    for pos in ("QB", "RB", "WR", "TE", "K", "DEF"):
        players = [p for p in available if p["position"] == pos]
        startable = sum(
            1 for p in players
            if effective_fantasy_ppg(p["ppg"], pos, scoring_key, p) - effective_vor_baseline(pos, scoring_key) > 0
        )
        scarcity[pos] = {"total": len(players), "startable": startable}
    return scarcity


# ---------------------------------------------------------------------------
# RECOMMENDATION ENGINE (bye-week + SOS aware)
# ---------------------------------------------------------------------------
def get_top_recommendations(available, roster, pick_number, n=3,
                            scoring_key="PPR", num_teams=12, roster_preset="Standard"):
    needs = get_positional_needs(roster, roster_preset)
    scored = []
    for p in available:
        pos = p["position"]
        vor = effective_fantasy_ppg(p["ppg"], pos, scoring_key, p) - effective_vor_baseline(pos, scoring_key)

        # Positional need multiplier
        if pos in needs and needs[pos] >= 2:
            mult = 2.0
        elif pos in needs or (pos in FLEX_ELIGIBLE and "FLEX" in needs):
            mult = 1.5
        elif pos in SFLEX_ELIGIBLE and "SFLEX" in needs:
            mult = 1.3
        else:
            mult = 1.0

        # Bye week penalty
        bye_conflicts = get_bye_week_conflicts(roster, p["team"])
        if bye_conflicts >= 3:
            mult *= 0.75
        elif bye_conflicts >= 2:
            mult *= 0.9

        scored.append((vor * mult, p))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:max(n * 2, 8)]
    recs = []
    seen = set()
    rnd = max(1, math.ceil(pick_number / max(6, num_teams)))
    for score, p in top:
        if p["name"] in seen:
            continue
        seen.add(p["name"])
        grade, verdict, proj_ppg, conf = grade_player_adp(
            p["name"], p["position"], p["ppg"], p["adp"], rnd, num_teams, scoring_key, p
        )
        _ppos = p["position"]
        pos_ctx = "Fills: " + _ppos
        if _ppos in needs:
            s = needs[_ppos]
            pos_ctx += " (" + str(s) + " slot" + ("s" if s > 1 else "") + " remaining)"
        elif _ppos in FLEX_ELIGIBLE and "FLEX" in needs:
            pos_ctx += " (FLEX eligible)"
        elif _ppos in SFLEX_ELIGIBLE and "SFLEX" in needs:
            pos_ctx += " (SFLEX eligible)"
        else:
            pos_ctx += " (bench depth)"

        bye = BYE_WEEKS.get(p["team"])
        bye_conflicts = get_bye_week_conflicts(roster, p["team"])
        bye_warning = ""
        if bye_conflicts >= 2:
            bye_warning = str(bye_conflicts) + " roster players share Week " + str(bye) + " bye"

        recs.append({
            "player":      p["name"],
            "position":    p["position"],
            "team":        p["team"],
            "adp":         p["adp"],
            "ppg":         p["ppg"],
            "proj_ppg":    proj_ppg,
            "vor":         round(score, 2),
            "grade":       grade,
            "verdict":     verdict,
            "ctx":         pos_ctx,
            "bye_week":    bye,
            "bye_warning": bye_warning,
            "sos":         SOS_TIERS.get(p["team"], "Medium"),
        })
        if len(recs) >= n:
            break
    return recs


# ---------------------------------------------------------------------------
# OPPONENT AI (ADP-weighted, realistic)
# ---------------------------------------------------------------------------
def simulate_opponent_pick(available):
    if not available:
        return None
    window = min(len(available), 5)
    weights = [math.exp(-0.5 * i) for i in range(window)]
    chosen = random.choices(available[:window], weights=weights, k=1)[0]
    available.remove(chosen)
    return chosen


# ---------------------------------------------------------------------------
# DRAFT STATE MANAGEMENT
# ---------------------------------------------------------------------------
def init_draft_state(pool, num_teams=12, user_team=1, snake=True,
                     scoring="PPR", roster_preset="Standard"):
    pool = copy.deepcopy(pool)
    pool.sort(key=lambda p: p["adp"])
    num_teams = max(6, min(16, num_teams))
    user_team = max(1, min(num_teams, user_team))
    total_rounds = roster_total_slots(roster_preset)
    state = {
        "current_round":     1,
        "pick_in_round":     1,
        "picks_made":        0,
        "draft_complete":    False,
        "available_players": pool,
        "rosters":           {t: [] for t in range(1, num_teams + 1)},
        "num_teams":         num_teams,
        "user_team":         user_team,
        "snake":             snake,
        "scoring":           scoring,
        "roster_preset":     roster_preset,
        "total_rounds":      total_rounds,
    }
    advance_to_user_pick(state)
    return state


def advance_to_user_pick(state):
    num_teams = int(state["num_teams"])
    user_team = int(state["user_team"])
    snake = bool(state.get("snake", True))
    total_rounds = state.get("total_rounds", 15)
    while True:
        rnd = state["current_round"]
        pick_in = state["pick_in_round"]
        if rnd > total_rounds:
            state["draft_complete"] = True
            break
        if snake:
            team_slot = pick_in if (rnd % 2 == 1) else (num_teams + 1 - pick_in)
        else:
            team_slot = pick_in
        if team_slot == user_team:
            break
        picked = simulate_opponent_pick(state["available_players"])
        if picked:
            state["rosters"][team_slot].append(picked)
            state["picks_made"] += 1
        pick_in += 1
        if pick_in > num_teams:
            pick_in = 1
            state["current_round"] += 1
        state["pick_in_round"] = pick_in
        if state["current_round"] > total_rounds:
            state["draft_complete"] = True
            break


def make_user_pick(state, player_name, roster_preset="Standard"):
    name_lower = player_name.lower().strip()
    found = next((p for p in state["available_players"]
                  if p["name"].lower().strip() == name_lower), None)
    if found is None:
        return {"error": "Player '" + player_name + "' not available or already drafted."}
    state["available_players"].remove(found)
    _ut = int(state["user_team"])
    state["rosters"][_ut].append(found)
    state["picks_made"] += 1
    round_now = state["current_round"]
    nxt = state["pick_in_round"] + 1
    if nxt > int(state["num_teams"]):
        nxt = 1
        state["current_round"] += 1
    state["pick_in_round"] = nxt
    advance_to_user_pick(state)
    user_roster = state["rosters"][_ut]
    next_pick = state["picks_made"] + 1
    scoring_key = state.get("scoring", "PPR")
    num_teams = int(state["num_teams"])
    if state.get("draft_complete"):
        return {"picked": found, "round": round_now, "draft_complete": True, "user_roster": user_roster}
    return {
        "picked":     found,
        "round":      round_now,
        "next_pick":  next_pick,
        "next_round": state["current_round"],
        "needs":      get_positional_needs(user_roster, roster_preset),
        "recs":       get_top_recommendations(
            state["available_players"], user_roster, next_pick,
            scoring_key=scoring_key, num_teams=num_teams, roster_preset=roster_preset
        ),
        "user_roster": user_roster,
    }


def make_auto_pick(state, roster_preset="Standard"):
    """Auto-draft the top recommendation (simulates trade-down / AI pick)."""
    if not state["available_players"]:
        return {"error": "No players available."}
    roster = state["rosters"][state["user_team"]]
    scoring_key = state.get("scoring", "PPR")
    num_teams = int(state["num_teams"])
    recs = get_top_recommendations(
        state["available_players"], roster, state["picks_made"] + 1,
        n=1, scoring_key=scoring_key, num_teams=num_teams, roster_preset=roster_preset,
    )
    if recs:
        return make_user_pick(state, recs[0]["player"], roster_preset)
    return make_user_pick(state, state["available_players"][0]["name"], roster_preset)


# ---------------------------------------------------------------------------
# UNDO
# ---------------------------------------------------------------------------
def save_undo_snapshot(state, history):
    return {"state": copy.deepcopy(state), "history": copy.deepcopy(history)}


def restore_undo_snapshot(snapshot):
    return copy.deepcopy(snapshot["state"]), copy.deepcopy(snapshot["history"])


# ---------------------------------------------------------------------------
# PLAYERS LIKELY GONE (trade awareness)
# ---------------------------------------------------------------------------
def picks_until_next_turn(state):
    num_teams = int(state["num_teams"])
    user_team = int(state["user_team"])
    snake = bool(state.get("snake", True))
    total_rounds = state.get("total_rounds", 15)
    rnd = state["current_round"]
    pick_in = state["pick_in_round"]
    count = 0
    sim_rnd = rnd
    sim_pick = pick_in
    while True:
        sim_pick += 1
        if sim_pick > num_teams:
            sim_pick = 1
            sim_rnd += 1
        if sim_rnd > total_rounds:
            break
        if snake:
            team_slot = sim_pick if (sim_rnd % 2 == 1) else (num_teams + 1 - sim_pick)
        else:
            team_slot = sim_pick
        if team_slot == user_team:
            break
        count += 1
    return count


def get_players_likely_gone(state, max_show=8):
    ahead = picks_until_next_turn(state)
    if ahead <= 0:
        return []
    count = min(len(state["available_players"]), ahead, max_show)
    return state["available_players"][:count]


# ---------------------------------------------------------------------------
# DRAFT RECAP
# ---------------------------------------------------------------------------
def compute_draft_recap(roster, history, scoring_key="PPR", num_teams=12):
    if not roster or not history:
        return None

    grades = [h.get("grade", "F") for h in history]
    avg_val = sum(GRADE_VALUES.get(g, 1) for g in grades) / max(len(grades), 1)

    # Map average back to letter grade
    overall_grade = "F"
    for val, letter in sorted([(v, k) for k, v in GRADE_VALUES.items()], reverse=True):
        if avg_val >= val - 0.5:
            overall_grade = letter
            break

    # Position breakdown
    pos_groups = {}
    for h in history:
        pos = h.get("position", "?")
        if pos not in pos_groups:
            pos_groups[pos] = []
        pos_groups[pos].append(h)

    # Total projected PPG
    total_ppg = sum(
        effective_fantasy_ppg(p["ppg"], p["position"], scoring_key, p)
        for p in roster
    )

    # Reach vs steal analysis
    pick_values = []
    for h in history:
        ppg_eff = effective_fantasy_ppg(h.get("ppg", 0), h["position"], scoring_key)
        vor = ppg_eff - effective_vor_baseline(h["position"], scoring_key)
        adp_rd = h.get("adp", 999) / float(max(6, num_teams))
        actual_rd = h.get("round", 1)
        value_diff = adp_rd - actual_rd
        pick_values.append({
            **h,
            "vor": round(vor, 2),
            "value_diff": round(value_diff, 1),
            "ppg_eff": round(ppg_eff, 2),
        })

    best_pick = max(pick_values, key=lambda x: x["value_diff"]) if pick_values else None
    worst_pick = min(pick_values, key=lambda x: x["value_diff"]) if pick_values else None
    steals = [p for p in pick_values if p["value_diff"] >= 1.5]
    reaches = [p for p in pick_values if p["value_diff"] <= -1.5]

    # Bye week conflicts
    _, bye_conflicts = get_roster_bye_analysis(roster)

    return {
        "overall_grade":  overall_grade,
        "avg_grade_val":  round(avg_val, 1),
        "total_ppg":      round(total_ppg, 1),
        "pos_groups":     pos_groups,
        "pick_values":    pick_values,
        "best_pick":      best_pick,
        "worst_pick":     worst_pick,
        "steals":         steals,
        "reaches":        reaches,
        "bye_conflicts":  bye_conflicts,
        "num_picks":      len(history),
    }


# ---------------------------------------------------------------------------
# MULTI-DRAFT HISTORY
# ---------------------------------------------------------------------------
def save_draft_result(history, roster, settings):
    results = load_draft_results()
    results.append({
        "timestamp": utc_timestamp(),
        "settings": settings,
        "history": history,
        "roster_names": [p["name"] for p in roster],
    })
    results = results[-50:]
    try:
        with open(DRAFT_RESULTS_PATH, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)
    except OSError:
        pass


def load_draft_results():
    try:
        with open(DRAFT_RESULTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []


def get_draft_trends(results):
    if not results:
        return None

    player_counts = {}
    for draft in results:
        for pick in draft.get("history", []):
            name = pick.get("player", "")
            if name:
                player_counts[name] = player_counts.get(name, 0) + 1

    most_drafted = sorted(player_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    pos_rounds = {}
    for draft in results:
        for pick in draft.get("history", []):
            pos = pick.get("position", "?")
            rd = pick.get("round", 0)
            if pos not in pos_rounds:
                pos_rounds[pos] = []
            pos_rounds[pos].append(rd)

    avg_pos_round = {
        pos: round(sum(rounds) / len(rounds), 1)
        for pos, rounds in pos_rounds.items()
        if rounds
    }

    grade_totals = []
    for draft in results:
        grades = [GRADE_VALUES.get(p.get("grade", "F"), 1) for p in draft.get("history", [])]
        if grades:
            grade_totals.append(sum(grades) / len(grades))

    avg_draft_grade = round(sum(grade_totals) / len(grade_totals), 1) if grade_totals else 0

    return {
        "total_drafts":   len(results),
        "most_drafted":   most_drafted,
        "avg_pos_round":  avg_pos_round,
        "avg_draft_grade": avg_draft_grade,
    }


# ---------------------------------------------------------------------------
# SLEEPER INTEGRATION
# ---------------------------------------------------------------------------
def build_sleeper_name(player_data):
    full_name = str(player_data.get("full_name") or "").strip()
    if full_name:
        return full_name
    first_name = str(player_data.get("first_name") or "").strip()
    last_name = str(player_data.get("last_name") or "").strip()
    return (first_name + " " + last_name).strip()


def merge_sleeper_metadata(base_pool, sleeper_payload):
    if not isinstance(sleeper_payload, dict):
        raise ValueError("Sleeper returned an unexpected payload.")

    base_by_name = {norm_name(player["name"]): player.copy() for player in base_pool}
    merged_pool = []
    seen_names = set()

    for sleeper_player in sleeper_payload.values():
        if not isinstance(sleeper_player, dict):
            continue
        fantasy_positions = sleeper_player.get("fantasy_positions") or []
        live_position = next(
            (str(pos).upper() for pos in fantasy_positions if str(pos).upper() in FANTASY_POSITIONS),
            None,
        )
        if live_position is None:
            raw_position = str(sleeper_player.get("position") or "").strip().upper()
            live_position = raw_position if raw_position in FANTASY_POSITIONS else None
        if live_position is None:
            continue

        live_name = build_sleeper_name(sleeper_player)
        if not live_name:
            continue

        nn = norm_name(live_name)
        base_player = base_by_name.get(nn)
        if base_player is None:
            continue

        updated_player = base_player.copy()
        updated_player["name"] = live_name
        updated_player["position"] = live_position
        updated_player["team"] = str(sleeper_player.get("team") or updated_player["team"] or "FA").strip().upper() or "FA"
        _spid = sleeper_player.get("player_id")
        if _spid is not None and str(_spid).strip():
            updated_player["sleeper_id"] = str(_spid).strip()
        merged_pool.append(updated_player)
        seen_names.add(nn)

    for base_player in base_pool:
        if norm_name(base_player["name"]) not in seen_names:
            merged_pool.append(base_player.copy())

    merged_pool = validate_player_pool(merged_pool)
    if not merged_pool:
        raise ValueError("Sleeper update returned no fantasy-eligible players.")
    return merged_pool
