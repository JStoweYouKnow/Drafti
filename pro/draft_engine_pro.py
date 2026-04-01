"""DRAFTi Pro - NFL Draft Value Evaluation Engine.

Evaluates real NFL draft picks against consensus big boards, trade value charts,
positional value models, and historical outcome data. No fantasy football logic.
"""
import copy
import json
import math
import os
import re
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# CONSTANTS
# ---------------------------------------------------------------------------
NFL_POSITIONS = [
    "QB", "EDGE", "OT", "CB", "WR", "IDL", "S", "LB", "IOL", "TE", "RB", "K", "P",
]

GRADE_THRESHOLDS = [
    (2.5, "A+"), (2.0, "A"), (1.5, "A-"),
    (1.0, "B+"), (0.5, "B"), (0.0, "B-"),
    (-0.5, "C+"), (-1.0, "C"), (-1.5, "C-"),
    (-2.0, "D+"), (-2.5, "D"), (-999, "F"),
]

GRADE_VALUES = {
    "A+": 12, "A": 11, "A-": 10, "B+": 9, "B": 8, "B-": 7,
    "C+": 6, "C": 5, "C-": 4, "D+": 3, "D": 2, "F": 1,
}

STATUS_LABELS = {
    "star": "Star", "starter": "Quality Starter", "developing": "Developing",
    "bust": "Bust", "out": "Out of League", "unknown": "Too Early",
}

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Known prospects not draft-eligible for the given class year.
# Source boards can include underclassmen hype names, so we filter them out.
KNOWN_INELIGIBLE_PROSPECTS = {
    2026: {
        # Confirmed returning to school / not yet eligible (verified pre-cutoff)
        "arch manning",
        "lanorris sellers",
        "malachi nelson",
        "nico iamaleava",
        # Common misspelling variant seen in user-reported boards.
        "nico iamaleva",
        "dante moore",
        "sam leavitt",
    },
}

# Known year-specific board corrections when source aggregators lag or leak prior-season context.
KNOWN_BOARD_OVERRIDES = {
    2026: {
        "fernando mendoza": {
            "consensus_rank": 1,
            "school": "Indiana",
            "position": "QB",
        },
    },
}

# ---------------------------------------------------------------------------
# UTILITIES
# ---------------------------------------------------------------------------
def ordinal(n):
    n = int(n)
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return str(n) + suffix


def utc_timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def pick_to_round(overall):
    return max(1, math.ceil(int(overall) / 32))


# ---------------------------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------------------------
def _load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_trade_value_chart():
    data = _load_json("trade_value_chart.json")
    return {int(k): int(v) for k, v in data["pick_values"].items()}


def load_position_values():
    return _load_json("position_values.json")


def load_historical_drafts():
    return _load_json("historical_drafts.json")


def available_consensus_board_years():
    """Return sorted list of years that have consensus board files."""
    years = []
    try:
        for filename in os.listdir(DATA_DIR):
            m = re.fullmatch(r"consensus_board_(\d{4})\.json", filename)
            if m:
                years.append(int(m.group(1)))
    except OSError:
        return []
    return sorted(years)


def _normalize_name(name):
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _collect_ineligible_from_wire(year):
    """Collect ineligible player names from transaction wire/status cache."""
    statuses_ineligible = {"withdrew", "transferred", "medical_retirement"}
    rows = []

    wire = load_transaction_wire(year)
    if wire and isinstance(wire.get("entries"), list):
        rows.extend(wire["entries"])

    cache = load_player_status_cache(year)
    if cache and isinstance(cache.get("players"), list):
        rows.extend(cache["players"])

    names = set()
    for row in rows:
        status = str(row.get("status", "")).strip().lower()
        if status not in statuses_ineligible:
            continue
        nm = _normalize_name(row.get("name", ""))
        if nm:
            names.add(nm)
    return names


def _apply_board_overrides(board_data, requested_year):
    """Apply known board corrections and re-rank after forced placements."""
    if not isinstance(board_data, dict):
        return board_data
    prospects = board_data.get("prospects", [])
    if not isinstance(prospects, list) or not prospects:
        return board_data

    overrides = KNOWN_BOARD_OVERRIDES.get(int(requested_year), {})
    if not overrides:
        return board_data

    # Start with current board order.
    ordered = sorted(
        prospects,
        key=lambda p: (
            int(p.get("consensus_rank", 10**9)) if str(p.get("consensus_rank", "")).isdigit() else 10**9,
            _normalize_name(p.get("name", "")),
        ),
    )

    applied = []
    for name_key, patch in overrides.items():
        idx = None
        for i, p in enumerate(ordered):
            if _normalize_name(p.get("name", "")) == name_key:
                idx = i
                break
        if idx is None:
            continue

        row = ordered.pop(idx)
        if "school" in patch:
            row["school"] = patch["school"]
        if "position" in patch:
            row["position"] = patch["position"]

        target_rank = patch.get("consensus_rank")
        if isinstance(target_rank, int) and target_rank > 0:
            insert_at = max(0, min(len(ordered), target_rank - 1))
        else:
            insert_at = len(ordered)
        ordered.insert(insert_at, row)
        applied.append(row.get("name", name_key))

    # Re-rank board to contiguous values.
    for i, p in enumerate(ordered, start=1):
        p["consensus_rank"] = i

    if applied:
        board_data["prospects"] = ordered
        board_data["_overrides_applied"] = applied
    return board_data


def _auto_remediate_board(board_data):
    """Auto-remediate common board data issues (currently duplicate names)."""
    if not isinstance(board_data, dict):
        return board_data
    prospects = board_data.get("prospects", [])
    if not isinstance(prospects, list) or not prospects:
        return board_data

    ordered = sorted(
        prospects,
        key=lambda p: (
            int(p.get("consensus_rank", 10**9)) if isinstance(p.get("consensus_rank"), int) else 10**9,
            _normalize_name(p.get("name", "")),
        ),
    )

    deduped = []
    seen_names = set()
    removed = []
    for p in ordered:
        key = _normalize_name(p.get("name", ""))
        if not key:
            deduped.append(p)
            continue
        if key in seen_names:
            removed.append(
                {
                    "name": p.get("name", key),
                    "dropped_rank": p.get("consensus_rank"),
                }
            )
            continue
        seen_names.add(key)
        deduped.append(p)

    for idx, p in enumerate(deduped, start=1):
        p["consensus_rank"] = idx

    board_data["prospects"] = deduped
    board_data["_remediation"] = {
        "dedupe_names_removed": removed,
        "removed_count": len(removed),
    }
    return board_data


def _validate_consensus_board(board_data, requested_year):
    """Run data quality checks and attach validation metadata."""
    year = int(requested_year)
    out = {"status": "ok", "errors": [], "warnings": [], "stats": {}}
    if not isinstance(board_data, dict):
        out["status"] = "error"
        out["errors"].append("Board payload is not a dictionary.")
        return out

    prospects = board_data.get("prospects", [])
    if not isinstance(prospects, list):
        out["status"] = "error"
        out["errors"].append("Board prospects field is not a list.")
        return out

    out["stats"]["num_prospects"] = len(prospects)

    # Rank continuity and collisions.
    ranks = []
    rank_counts = {}
    for p in prospects:
        r = p.get("consensus_rank")
        if isinstance(r, int):
            ranks.append(r)
            rank_counts[r] = rank_counts.get(r, 0) + 1
    if ranks:
        expected = list(range(1, len(ranks) + 1))
        sorted_ranks = sorted(ranks)
        if sorted_ranks != expected:
            out["warnings"].append("Consensus ranks are not contiguous starting at 1.")
        dup_ranks = [r for r, c in rank_counts.items() if c > 1]
        if dup_ranks:
            out["warnings"].append("Duplicate consensus ranks detected: " + ", ".join(str(x) for x in dup_ranks[:10]))
    else:
        out["errors"].append("No valid integer consensus ranks found.")

    # Duplicate names.
    name_counts = {}
    for p in prospects:
        nm = _normalize_name(p.get("name", ""))
        if not nm:
            continue
        name_counts[nm] = name_counts.get(nm, 0) + 1
    dup_names = [n for n, c in name_counts.items() if c > 1]
    if dup_names:
        out["warnings"].append("Duplicate prospect names detected: " + ", ".join(dup_names[:8]))

    # Known ineligible names should not be present after filtering.
    ineligible = set(KNOWN_INELIGIBLE_PROSPECTS.get(year, set()))
    ineligible.update(_collect_ineligible_from_wire(year))
    present_ineligible = []
    for p in prospects:
        nm = _normalize_name(p.get("name", ""))
        if nm in ineligible:
            present_ineligible.append(p.get("name", nm))
    if present_ineligible:
        out["warnings"].append(
            "Ineligible prospects still present on board: " + ", ".join(present_ineligible[:8])
        )

    # Known override constraints should be satisfied in final board.
    overrides = KNOWN_BOARD_OVERRIDES.get(year, {})
    for nm, patch in overrides.items():
        row = next((p for p in prospects if _normalize_name(p.get("name", "")) == nm), None)
        if row is None:
            out["warnings"].append("Expected override prospect missing: " + nm)
            continue
        exp_rank = patch.get("consensus_rank")
        exp_school = patch.get("school")
        if isinstance(exp_rank, int) and row.get("consensus_rank") != exp_rank:
            out["warnings"].append(
                f"Override rank mismatch for {row.get('name', nm)}: expected #{exp_rank}, got #{row.get('consensus_rank')}."
            )
        if exp_school and str(row.get("school", "")).strip() != exp_school:
            out["warnings"].append(
                f"Override school mismatch for {row.get('name', nm)}: expected {exp_school}, got {row.get('school', '')}."
            )

    top_50_transfers = []
    top_50 = [p for p in prospects if isinstance(p.get("consensus_rank"), int) and p["consensus_rank"] <= 50]
    for p in top_50:
        status = str(p.get("eligibility", {}).get("status", "declared")).lower().strip()
        if status in {"withdrew", "transferred", "medical_retirement"}:
            top_50_transfers.append(p.get("name", ""))
    if top_50_transfers:
        out["warnings"].append("Top-50 includes ineligible statuses: " + ", ".join(top_50_transfers[:8]))

    if out["errors"]:
        out["status"] = "error"
    elif out["warnings"]:
        out["status"] = "warn"
    return out


def _filter_ineligible_prospects(board_data, requested_year):
    """Remove known non-eligible players for a draft year and re-rank board."""
    year = int(requested_year)
    excluded_names = set(KNOWN_INELIGIBLE_PROSPECTS.get(year, set()))
    excluded_names.update(_collect_ineligible_from_wire(year))
    if not excluded_names or not isinstance(board_data, dict):
        return board_data
    prospects = board_data.get("prospects", [])
    if not isinstance(prospects, list):
        return board_data

    filtered = []
    removed = []
    for p in prospects:
        name = str(p.get("name", "")).strip()
        if _normalize_name(name) in excluded_names:
            if name:
                removed.append(name)
            continue
        filtered.append(p)

    if not removed:
        return board_data

    # Re-rank board after exclusions to keep contiguous consensus ranks.
    for idx, p in enumerate(filtered, start=1):
        p["consensus_rank"] = idx

    board_data["prospects"] = filtered
    board_data["_excluded_prospects"] = removed
    return board_data


def load_consensus_board(year=2025, allow_fallback=True):
    """Load consensus board for a year, optionally falling back to nearest available year."""
    try:
        requested_year = int(year)
    except (TypeError, ValueError):
        requested_year = 2025

    filename = "consensus_board_" + str(requested_year) + ".json"
    try:
        board = _load_json(filename)
        if isinstance(board, dict):
            board = copy.deepcopy(board)
            board["_requested_year"] = requested_year
            board["_source_year"] = requested_year
            board = _filter_ineligible_prospects(board, requested_year)
            board = _auto_remediate_board(board)
            board = _apply_board_overrides(board, requested_year)
            board["_validation"] = _validate_consensus_board(board, requested_year)
        return board
    except (OSError, json.JSONDecodeError):
        pass

    if not allow_fallback:
        return None

    years = available_consensus_board_years()
    if not years:
        return None

    fallback_year = min(years, key=lambda y: abs(y - requested_year))
    fallback_file = "consensus_board_" + str(fallback_year) + ".json"
    try:
        board = _load_json(fallback_file)
    except (OSError, json.JSONDecodeError):
        return None

    if isinstance(board, dict):
        board = copy.deepcopy(board)
        board["_requested_year"] = requested_year
        board["_source_year"] = fallback_year
        board = _filter_ineligible_prospects(board, requested_year)
        board = _auto_remediate_board(board)
        board = _apply_board_overrides(board, requested_year)
        board["_validation"] = _validate_consensus_board(board, requested_year)
    return board


# ---------------------------------------------------------------------------
# TRADE VALUE CHART HELPERS
# ---------------------------------------------------------------------------
def get_pick_value(pick_number, chart=None):
    if chart is None:
        chart = load_trade_value_chart()
    pick = int(pick_number)
    if pick in chart:
        return chart[pick]
    keys = sorted(chart.keys())
    if pick < keys[0]:
        return chart[keys[0]]
    if pick > keys[-1]:
        return chart[keys[-1]]
    lower = max(k for k in keys if k <= pick)
    upper = min(k for k in keys if k >= pick)
    if lower == upper:
        return chart[lower]
    frac = (pick - lower) / (upper - lower)
    return round(chart[lower] + frac * (chart[upper] - chart[lower]))


def calculate_trade_surplus(picks_sent, picks_received, chart=None):
    """Calculate net trade value. Positive = team gained value."""
    if chart is None:
        chart = load_trade_value_chart()
    sent_value = sum(get_pick_value(p, chart) for p in picks_sent if isinstance(p, int))
    recv_value = sum(get_pick_value(p, chart) for p in picks_received if isinstance(p, int))
    return recv_value - sent_value


# ---------------------------------------------------------------------------
# CONSENSUS BOARD HELPERS
# ---------------------------------------------------------------------------
def find_prospect_on_board(board_data, player_name):
    if not board_data or "prospects" not in board_data:
        return None
    name_lower = player_name.lower().strip()
    for p in board_data["prospects"]:
        if p["name"].lower().strip() == name_lower:
            return p
    for p in board_data["prospects"]:
        pn = p["name"].lower().strip()
        if name_lower in pn or pn in name_lower:
            return p
    return None


def get_team_needs(board_data, team):
    if not board_data or "team_needs" not in board_data:
        return []
    return board_data["team_needs"].get(team.upper(), [])


# ---------------------------------------------------------------------------
# PICK GRADING ENGINE
# ---------------------------------------------------------------------------
def grade_pick(pick_overall, player_name, position, board_data=None,
               pos_values=None, trade_chart=None, team=None,
               team_schemes=None, cap_context=None):
    """Grade a single NFL draft pick.

    Returns a dict with grade, verdict, value_score, and detailed breakdown.
    Core formula:
        value_score = board_delta * source_confidence
                    + positional_adj + need_bonus + tier_bonus
                    + athletic_bonus + production_bonus + injury_penalty
                    + velocity_bonus + recruiting_bonus
                    + scheme_bonus + cap_bonus
    """
    if board_data is None:
        board_data = load_consensus_board()
    if pos_values is None:
        pos_values = load_position_values()
    if trade_chart is None:
        trade_chart = load_trade_value_chart()

    pick = int(pick_overall)
    rnd = pick_to_round(pick)
    pos = position.upper().strip()

    prospect = find_prospect_on_board(board_data, player_name) if board_data else None
    consensus_rank = prospect["consensus_rank"] if prospect else None
    prospect_grade = prospect["grade"] if prospect else None
    prospect_tier = prospect["tier"] if prospect else None

    # --- Board delta (biggest factor) ---
    if consensus_rank is not None:
        raw_delta = pick - consensus_rank
        position_weight = max(0.5, 1.0 - (pick - 1) / 256)
        board_delta = (raw_delta / max(5, pick * 0.3)) * position_weight
    else:
        board_delta = -0.5 if pick <= 64 else -0.2

    # --- Multi-source confidence (dampens board_delta when sources disagree) ---
    source_confidence = compute_source_confidence(
        prospect.get("source_ranks", {}) if prospect else {}
    )
    board_delta = board_delta * source_confidence

    # --- Positional value adjustment ---
    multipliers = pos_values.get("positional_value_multiplier", {})
    pos_mult = multipliers.get(pos, 1.0)
    positional_adj = (pos_mult - 1.0) * 1.5

    # --- Team need bonus ---
    need_bonus = 0.0
    needs = get_team_needs(board_data, team) if team else []
    if pos in needs:
        need_idx = needs.index(pos)
        if need_idx == 0:
            need_bonus = 0.5
        elif need_idx == 1:
            need_bonus = 0.3
        elif need_idx == 2:
            need_bonus = 0.15

    # --- Tier bonus (elite talent falling) ---
    tier_bonus = 0.0
    if prospect_tier is not None and consensus_rank is not None:
        if prospect_tier == 1 and pick > 10:
            tier_bonus = 0.5
        elif prospect_tier == 1 and pick > 5:
            tier_bonus = 0.25
        elif prospect_tier == 2 and pick > 20:
            tier_bonus = 0.25

    # --- NEW: Athletic / combine bonus ---
    measurables = prospect.get("measurables", {}) if prospect else {}
    athletic_bonus = compute_combine_score(measurables, pos) * 0.40

    # --- NEW: CFB production signal ---
    cfb_stats = prospect.get("cfb_stats", {}) if prospect else {}
    production_bonus = compute_cfb_production_score(cfb_stats, pos)

    # --- NEW: Injury risk penalty ---
    injury_history = prospect.get("injury_history", {}) if prospect else {}
    injury_penalty = compute_injury_risk_penalty(injury_history)

    # --- NEW: Board velocity signal ---
    board_velocity = prospect.get("board_velocity", {}) if prospect else {}
    velocity_bonus = compute_board_velocity_signal(board_velocity)

    # --- NEW: Recruiting / upside signal ---
    recruiting = prospect.get("recruiting", {}) if prospect else {}
    recruiting_bonus = compute_recruiting_signal(recruiting)

    # --- NEW: Scheme fit bonus ---
    scheme_bonus = compute_scheme_bonus(pos, team, team_schemes) if team else 0.0

    # --- NEW: Cap/roster urgency bonus ---
    cap_bonus = compute_cap_bonus(pos, team, cap_context) if team else 0.0

    # --- Composite score ---
    value_score = (
        board_delta + positional_adj + need_bonus + tier_bonus
        + athletic_bonus + production_bonus + injury_penalty
        + velocity_bonus + recruiting_bonus + scheme_bonus + cap_bonus
    )

    # --- Map to letter grade ---
    grade = "F"
    for threshold, g in GRADE_THRESHOLDS:
        if value_score >= threshold:
            grade = g
            break

    # --- Verdict (based on raw board delta before signal adjustments) ---
    if consensus_rank is not None:
        raw_delta_val = pick - consensus_rank
        if raw_delta_val >= 8:
            verdict = "Steal"
        elif raw_delta_val >= 3:
            verdict = "Great Value"
        elif raw_delta_val >= -2:
            verdict = "Fair Value"
        elif raw_delta_val >= -8:
            verdict = "Slight Reach"
        else:
            verdict = "Major Reach"
    else:
        verdict = "Off-Board Pick" if pick <= 64 else "Dart Throw"

    # --- Expected pick value and surplus ---
    expected_av = _interpolate_expected_av(pick, pos_values)
    pick_trade_value = get_pick_value(pick, trade_chart)

    # --- Historical hit rate ---
    hit_rates = pos_values.get("historical_hit_rate_by_round", {})
    pos_hit_rates = hit_rates.get(pos, {})
    hit_rate = pos_hit_rates.get(str(rnd), None)

    # --- Eligibility / injury flags from prospect data ---
    eligibility_status = (prospect.get("eligibility", {}).get("status", "declared")
                          if prospect else "declared")
    injury_flag = (prospect.get("injury_history", {}).get("flag", False)
                   if prospect else False)

    return {
        "pick_overall": pick,
        "round": rnd,
        "player": player_name,
        "position": pos,
        "team": team,
        "grade": grade,
        "grade_value": GRADE_VALUES.get(grade, 1),
        "value_score": round(value_score, 2),
        "verdict": verdict,
        "consensus_rank": consensus_rank,
        "prospect_grade": prospect_grade,
        "prospect_tier": prospect_tier,
        # Core formula components
        "board_delta": round(board_delta, 2),
        "positional_adj": round(positional_adj, 2),
        "need_bonus": round(need_bonus, 2),
        "tier_bonus": round(tier_bonus, 2),
        # New signal components
        "athletic_bonus": round(athletic_bonus, 3),
        "production_bonus": round(production_bonus, 3),
        "injury_penalty": round(injury_penalty, 3),
        "velocity_bonus": round(velocity_bonus, 3),
        "recruiting_bonus": round(recruiting_bonus, 3),
        "scheme_bonus": round(scheme_bonus, 3),
        "cap_bonus": round(cap_bonus, 3),
        "source_confidence": round(source_confidence, 3),
        # Flags
        "injury_flag": injury_flag,
        "eligibility_status": eligibility_status,
        "needs_filled": pos in needs,
        "team_needs": needs,
        "pick_trade_value": pick_trade_value,
        "expected_career_av": expected_av,
        "hit_rate": hit_rate,
    }


def _interpolate_expected_av(pick, pos_values):
    av_data = pos_values.get("expected_career_av_by_pick", {})
    av_map = {int(k): int(v) for k, v in av_data.items() if not k.startswith("_")}
    if not av_map:
        return None
    if pick in av_map:
        return av_map[pick]
    keys = sorted(av_map.keys())
    if pick < keys[0]:
        return av_map[keys[0]]
    if pick > keys[-1]:
        return av_map[keys[-1]]
    lower = max(k for k in keys if k <= pick)
    upper = min(k for k in keys if k >= pick)
    if lower == upper:
        return av_map[lower]
    frac = (pick - lower) / (upper - lower)
    return round(av_map[lower] + frac * (av_map[upper] - av_map[lower]))


# ---------------------------------------------------------------------------
# TEAM DRAFT GRADE (aggregate all picks)
# ---------------------------------------------------------------------------
def grade_team_draft(team, picks_graded, trade_details=None, trade_chart=None):
    """Aggregate individual pick grades into an overall team draft grade."""
    if not picks_graded:
        return None
    if trade_chart is None:
        trade_chart = load_trade_value_chart()

    grade_vals = [p["grade_value"] for p in picks_graded]
    # Weight earlier picks more heavily
    weights = [max(0.3, 1.0 - (i * 0.12)) for i in range(len(grade_vals))]
    weighted_avg = sum(g * w for g, w in zip(grade_vals, weights)) / sum(weights)

    # Trade adjustment
    trade_adj = 0.0
    if trade_details:
        for trade in trade_details:
            surplus = calculate_trade_surplus(
                trade.get("picks_sent", []),
                trade.get("picks_received", []),
                trade_chart,
            )
            # Normalize trade surplus to grade points
            trade_adj += surplus / 500.0
    weighted_avg += trade_adj

    # Map back to letter
    overall_grade = "F"
    for val, letter in sorted([(v, k) for k, v in GRADE_VALUES.items()], reverse=True):
        if weighted_avg >= val - 0.5:
            overall_grade = letter
            break

    # Position coverage analysis
    positions_drafted = [p["position"] for p in picks_graded]
    needs_addressed = sum(1 for p in picks_graded if p.get("needs_filled", False))

    best_pick = max(picks_graded, key=lambda x: x["value_score"])
    worst_pick = min(picks_graded, key=lambda x: x["value_score"])
    steals = [p for p in picks_graded if p["verdict"] in ("Steal", "Great Value")]
    reaches = [p for p in picks_graded if p["verdict"] in ("Slight Reach", "Major Reach")]

    return {
        "team": team,
        "overall_grade": overall_grade,
        "weighted_avg": round(weighted_avg, 1),
        "num_picks": len(picks_graded),
        "picks": picks_graded,
        "best_pick": best_pick,
        "worst_pick": worst_pick,
        "steals": steals,
        "reaches": reaches,
        "needs_addressed": needs_addressed,
        "positions_drafted": positions_drafted,
        "trade_adjustment": round(trade_adj, 2),
    }


# ---------------------------------------------------------------------------
# HISTORICAL OUTCOME EVALUATION
# ---------------------------------------------------------------------------
def evaluate_historical_pick(pick_data, pos_values=None):
    """Evaluate a historical pick using actual career outcomes.

    Compares actual career AV against expected AV for that draft slot,
    adjusted for position and accolades.
    """
    if pos_values is None:
        pos_values = load_position_values()

    pick = int(pick_data["overall"])
    pos = pick_data["position"]
    career_av = pick_data.get("career_av", 0)
    pro_bowls = pick_data.get("pro_bowls", 0)
    all_pros = pick_data.get("all_pros", 0)
    seasons = pick_data.get("seasons_played", 0)
    status = pick_data.get("status", "unknown")
    consensus_rank = pick_data.get("consensus_rank")

    expected_av = _interpolate_expected_av(pick, pos_values)
    if expected_av is None:
        expected_av = 10

    # Scale expected AV by seasons played (most data assumes 5-year window)
    if seasons > 0 and seasons < 5:
        expected_av_scaled = expected_av * (seasons / 5.0)
    else:
        expected_av_scaled = expected_av

    # --- AV surplus ---
    av_surplus = career_av - expected_av_scaled

    # --- Accolade bonus ---
    accolade_bonus = pro_bowls * 3.0 + all_pros * 6.0

    # --- Board accuracy (hindsight: was the consensus right?) ---
    board_accuracy = None
    if consensus_rank is not None:
        # If ranked high and produced, board was right
        # If ranked low and produced, board missed
        board_accuracy = "Accurate" if abs(consensus_rank - pick) <= 5 else (
            "Overrated" if career_av < expected_av_scaled * 0.6 else
            "Underrated" if career_av > expected_av_scaled * 1.4 else "Accurate"
        )

    # --- Outcome score ---
    outcome_score = av_surplus + accolade_bonus
    if seasons > 0:
        outcome_score = outcome_score / max(1, seasons) * 2  # Per-season normalization

    # --- Outcome grade ---
    outcome_grade = "F"
    for threshold, g in GRADE_THRESHOLDS:
        if outcome_score >= threshold:
            outcome_grade = g
            break

    # --- Contract value analysis ---
    rnd = pick_to_round(pick)
    contract_costs = pos_values.get("rookie_contract_value_by_round", {})
    contract_cost = contract_costs.get(str(rnd), 3)
    surplus_value = career_av - contract_cost

    return {
        "player": pick_data["player"],
        "team": pick_data["team"],
        "position": pos,
        "overall": pick,
        "round": rnd,
        "consensus_rank": consensus_rank,
        "school": pick_data.get("school", ""),
        "career_av": career_av,
        "expected_av": round(expected_av_scaled, 1),
        "av_surplus": round(av_surplus, 1),
        "pro_bowls": pro_bowls,
        "all_pros": all_pros,
        "seasons_played": seasons,
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "outcome_score": round(outcome_score, 2),
        "outcome_grade": outcome_grade,
        "board_accuracy": board_accuracy,
        "contract_cost_av": contract_cost,
        "surplus_value": round(surplus_value, 1),
        "accolade_bonus": round(accolade_bonus, 1),
    }


def evaluate_historical_draft_class(year, pos_values=None, historical_data=None):
    """Evaluate an entire draft class with outcome data."""
    if pos_values is None:
        pos_values = load_position_values()
    if historical_data is None:
        historical_data = load_historical_drafts()

    drafts = historical_data.get("drafts", {})
    draft = drafts.get(str(year))
    if not draft:
        return None

    picks = draft.get("picks", [])
    evaluated = [evaluate_historical_pick(p, pos_values) for p in picks]

    # Aggregate stats
    total_av = sum(e["career_av"] for e in evaluated)
    total_surplus = sum(e["av_surplus"] for e in evaluated)
    stars = [e for e in evaluated if e["status"] == "star"]
    busts = [e for e in evaluated if e["status"] == "bust"]

    grade_vals = [GRADE_VALUES.get(e["outcome_grade"], 1) for e in evaluated]
    avg_grade_val = sum(grade_vals) / max(len(grade_vals), 1)

    overall_grade = "F"
    for val, letter in sorted([(v, k) for k, v in GRADE_VALUES.items()], reverse=True):
        if avg_grade_val >= val - 0.5:
            overall_grade = letter
            break

    # Best/worst by surplus
    best = max(evaluated, key=lambda x: x["av_surplus"]) if evaluated else None
    worst = min(evaluated, key=lambda x: x["av_surplus"]) if evaluated else None

    # Position breakdown
    pos_groups = {}
    for e in evaluated:
        pos = e["position"]
        if pos not in pos_groups:
            pos_groups[pos] = []
        pos_groups[pos].append(e)

    return {
        "year": year,
        "overall_grade": overall_grade,
        "avg_grade_val": round(avg_grade_val, 1),
        "num_picks": len(evaluated),
        "evaluated_picks": evaluated,
        "total_career_av": total_av,
        "total_av_surplus": round(total_surplus, 1),
        "stars": stars,
        "busts": busts,
        "best_pick": best,
        "worst_pick": worst,
        "pos_groups": pos_groups,
        "trades": draft.get("trades", []),
    }


# ---------------------------------------------------------------------------
# HISTORICAL COMPARISONS
# ---------------------------------------------------------------------------
def find_historical_comps(position, pick_overall, historical_data=None):
    """Find historical players drafted at a similar position and pick range."""
    if historical_data is None:
        historical_data = load_historical_drafts()

    pick = int(pick_overall)
    pos = position.upper().strip()
    window = 8  # +/- 8 picks

    comps = []
    for year, draft in historical_data.get("drafts", {}).items():
        for p in draft.get("picks", []):
            if p["position"] == pos and abs(p["overall"] - pick) <= window:
                comps.append({**p, "draft_year": int(year)})

    comps.sort(key=lambda x: x.get("career_av", 0), reverse=True)
    return comps


def get_position_hit_rate_summary(pos_values=None):
    """Summarize hit rates by position across all rounds."""
    if pos_values is None:
        pos_values = load_position_values()
    hit_rates = pos_values.get("historical_hit_rate_by_round", {})
    summary = {}
    for pos, rounds in hit_rates.items():
        if not isinstance(rounds, dict):
            continue
        rates = []
        for v in rounds.values():
            try:
                rates.append(float(v))
            except (TypeError, ValueError):
                continue
        if not rates:
            continue
        def _round_rate(r_key):
            try:
                return float(rounds.get(r_key, 0))
            except (TypeError, ValueError):
                return 0.0
        summary[pos] = {
            "avg_hit_rate": round(sum(rates) / max(len(rates), 1), 3),
            "round_1_rate": _round_rate("1"),
            "late_round_rate": round(
                sum(_round_rate(str(r)) for r in range(5, 8)) / 3, 3
            ),
        }
    return summary


# ---------------------------------------------------------------------------
# LIVE DRAFT TRACKER STATE
# ---------------------------------------------------------------------------
def init_live_draft(year, board_data=None, pos_values=None, trade_chart=None):
    """Initialize state for tracking a live NFL draft."""
    if board_data is None:
        board_data = load_consensus_board(year)
    if pos_values is None:
        pos_values = load_position_values()
    if trade_chart is None:
        trade_chart = load_trade_value_chart()

    # Apply transaction wire eligibility flags to the board
    if board_data:
        board_data = apply_transaction_wire_to_board(board_data, year)

    team_schemes = load_team_schemes()
    cap_context = load_cap_context()

    return {
        "year": year,
        "picks": [],
        "graded_picks": [],
        "current_pick": 1,
        "trades": [],
        "board_data": board_data,
        "pos_values": pos_values,
        "trade_chart": trade_chart,
        "team_schemes": team_schemes,
        "cap_context": cap_context,
        "started_at": utc_timestamp(),
    }


def record_live_pick(state, team, player_name, position):
    """Record and grade a pick during live draft tracking."""
    pick_number = state["current_pick"]
    graded = grade_pick(
        pick_number, player_name, position,
        board_data=state["board_data"],
        pos_values=state["pos_values"],
        trade_chart=state["trade_chart"],
        team=team,
        team_schemes=state.get("team_schemes"),
        cap_context=state.get("cap_context"),
    )
    state["picks"].append({
        "overall": pick_number,
        "round": pick_to_round(pick_number),
        "team": team,
        "player": player_name,
        "position": position,
    })
    state["graded_picks"].append(graded)
    state["current_pick"] += 1
    return graded


def record_live_trade(state, description, picks_sent, picks_received):
    """Record a trade during live draft tracking."""
    trade_chart = state["trade_chart"]
    surplus = calculate_trade_surplus(picks_sent, picks_received, trade_chart)
    trade = {
        "description": description,
        "picks_sent": picks_sent,
        "picks_received": picks_received,
        "value_sent": sum(get_pick_value(p, trade_chart) for p in picks_sent if isinstance(p, int)),
        "value_received": sum(get_pick_value(p, trade_chart) for p in picks_received if isinstance(p, int)),
        "surplus": surplus,
    }
    state["trades"].append(trade)
    return trade


def get_live_draft_team_summary(state, team):
    """Get graded summary for one team during live draft."""
    team_picks = [p for p in state["graded_picks"] if p["team"] == team]
    team_trades = [t for t in state["trades"] if team in t.get("description", "")]
    return grade_team_draft(team, team_picks, team_trades, state["trade_chart"])


def get_live_draft_leaderboard(state):
    """Rank all teams by draft grade so far."""
    teams = set(p["team"] for p in state["graded_picks"])
    summaries = []
    for team in sorted(teams):
        summary = get_live_draft_team_summary(state, team)
        if summary:
            summaries.append(summary)
    summaries.sort(key=lambda x: x["weighted_avg"], reverse=True)
    return summaries


def get_remaining_top_prospects(state, n=10):
    """Show best available prospects not yet drafted."""
    if not state["board_data"] or "prospects" not in state["board_data"]:
        return []
    drafted_names = {p["player"].lower().strip() for p in state["picks"]}
    available = [
        p for p in state["board_data"]["prospects"]
        if p["name"].lower().strip() not in drafted_names
    ]
    available.sort(key=lambda x: x["consensus_rank"])
    return available[:n]


# ---------------------------------------------------------------------------
# TRANSACTION WIRE
# ---------------------------------------------------------------------------
def load_transaction_wire(year=2026):
    """Load eligibility transaction wire for a draft year."""
    filename = f"transaction_wire_{year}.json"
    try:
        return _load_json(filename)
    except (OSError, json.JSONDecodeError):
        return None


def load_player_status_cache(year=2026):
    """Load normalized player status cache generated by ingestion."""
    filename = f"player_status_cache_{year}.json"
    try:
        return _load_json(filename)
    except (OSError, json.JSONDecodeError):
        return None


def get_transaction_wire_summary(year=2026):
    """Return categorized lists of declared, withdrew, medical, transferred players."""
    wire = load_transaction_wire(year)
    if not wire:
        cache = load_player_status_cache(year)
        if cache and isinstance(cache.get("players"), list):
            wire = {"entries": cache["players"]}
    if not wire:
        return {
            "declared": [],
            "withdrew": [],
            "medical_retirement": [],
            "transferred": [],
            "undeclared": [],
        }
    out = {"declared": [], "withdrew": [], "medical_retirement": [], "transferred": [], "undeclared": []}
    for entry in wire.get("entries", []):
        status = entry.get("status", "undeclared")
        out.setdefault(status, []).append(entry)
    return out


def apply_transaction_wire_to_board(board_data, year=None):
    """Mark prospects on board with their transaction wire eligibility status."""
    if not board_data or "prospects" not in board_data:
        return board_data
    req_year = year or board_data.get("_requested_year", board_data.get("draft_year", 2026))
    wire = load_transaction_wire(req_year)
    if not wire:
        cache = load_player_status_cache(req_year)
        if cache and isinstance(cache.get("players"), list):
            wire = {"entries": cache["players"]}
    if not wire:
        return board_data
    wire_lookup = {}
    for entry in wire.get("entries", []):
        key = _normalize_name(entry.get("name", ""))
        wire_lookup[key] = entry
    for p in board_data["prospects"]:
        key = _normalize_name(p.get("name", ""))
        if key in wire_lookup:
            p.setdefault("eligibility", {})
            p["eligibility"]["status"] = wire_lookup[key].get("status", "declared")
            p["eligibility"]["notes"] = wire_lookup[key].get("notes", "")
            p["eligibility"]["verified_date"] = wire_lookup[key].get("date", "")
    return board_data


# ---------------------------------------------------------------------------
# COMBINE / ATHLETIC SCORING
# ---------------------------------------------------------------------------
# (ideal_value, scale, direction)  direction: +1 = higher is better, -1 = lower is better
_COMBINE_BENCHMARKS = {
    "forty":         {"QB": (4.72, 0.12, -1), "EDGE": (4.55, 0.10, -1), "OT": (4.98, 0.12, -1),
                      "IOL": (5.15, 0.15, -1), "CB": (4.40, 0.07, -1), "WR": (4.42, 0.07, -1),
                      "S": (4.45, 0.08, -1), "LB": (4.60, 0.10, -1), "TE": (4.68, 0.10, -1),
                      "RB": (4.46, 0.10, -1), "IDL": (4.88, 0.12, -1)},
    "ten_split":     {"QB": (1.60, 0.06, -1), "EDGE": (1.52, 0.05, -1), "OT": (1.70, 0.07, -1),
                      "IOL": (1.78, 0.08, -1), "CB": (1.47, 0.04, -1), "WR": (1.48, 0.04, -1),
                      "S": (1.49, 0.05, -1), "LB": (1.55, 0.05, -1), "TE": (1.57, 0.06, -1),
                      "RB": (1.50, 0.05, -1), "IDL": (1.66, 0.06, -1)},
    "vertical":      {"QB": (30, 4, 1), "EDGE": (35, 4, 1), "OT": (27, 4, 1),
                      "IOL": (26, 4, 1), "CB": (37, 4, 1), "WR": (38, 4, 1),
                      "S": (37, 4, 1), "LB": (34, 4, 1), "TE": (33, 4, 1),
                      "RB": (35, 4, 1), "IDL": (30, 4, 1)},
    "broad_jump":    {"QB": (108, 8, 1), "EDGE": (122, 8, 1), "OT": (104, 8, 1),
                      "IOL": (102, 8, 1), "CB": (127, 8, 1), "WR": (128, 8, 1),
                      "S": (125, 8, 1), "LB": (118, 8, 1), "TE": (116, 8, 1),
                      "RB": (120, 8, 1), "IDL": (112, 8, 1)},
    "three_cone":    {"QB": (6.90, 0.20, -1), "EDGE": (6.95, 0.20, -1), "OT": (7.30, 0.25, -1),
                      "IOL": (7.35, 0.25, -1), "CB": (6.65, 0.15, -1), "WR": (6.75, 0.15, -1),
                      "S": (6.75, 0.15, -1), "LB": (6.95, 0.20, -1), "TE": (6.95, 0.20, -1),
                      "RB": (6.80, 0.15, -1), "IDL": (7.08, 0.20, -1)},
    "short_shuttle": {"QB": (4.25, 0.15, -1), "EDGE": (4.30, 0.15, -1), "OT": (4.70, 0.20, -1),
                      "IOL": (4.65, 0.20, -1), "CB": (4.06, 0.10, -1), "WR": (4.10, 0.10, -1),
                      "S": (4.10, 0.10, -1), "LB": (4.25, 0.15, -1), "TE": (4.30, 0.15, -1),
                      "RB": (4.16, 0.12, -1), "IDL": (4.52, 0.15, -1)},
    "arm_length":    {"QB": (32.5, 1.5, 1), "EDGE": (33.5, 1.5, 1), "OT": (34.0, 1.5, 1),
                      "IOL": (33.0, 1.5, 1), "CB": (31.0, 1.5, 1), "WR": (31.5, 1.5, 1),
                      "S": (31.0, 1.5, 1), "LB": (32.0, 1.5, 1), "TE": (33.5, 1.5, 1),
                      "RB": (31.5, 1.5, 1), "IDL": (33.0, 1.5, 1)},
    "hand_size":     {"QB": (9.75, 0.75, 1), "EDGE": (10.0, 0.75, 1), "OT": (10.25, 0.75, 1),
                      "IOL": (10.0, 0.75, 1), "CB": (9.0, 0.50, 1), "WR": (9.25, 0.50, 1),
                      "S": (9.0, 0.50, 1), "LB": (9.5, 0.50, 1), "TE": (9.75, 0.50, 1),
                      "RB": (9.0, 0.50, 1), "IDL": (10.0, 0.75, 1)},
}

# Per-position weight for each metric (weights should sum to ~1.0)
_POSITION_COMBINE_WEIGHTS = {
    "QB":   {"forty": 0.12, "ten_split": 0.10, "arm_length": 0.15, "hand_size": 0.25, "three_cone": 0.15, "short_shuttle": 0.10, "vertical": 0.08, "broad_jump": 0.05},
    "EDGE": {"forty": 0.20, "ten_split": 0.20, "arm_length": 0.18, "hand_size": 0.12, "vertical": 0.12, "broad_jump": 0.12, "three_cone": 0.06},
    "OT":   {"arm_length": 0.30, "hand_size": 0.20, "forty": 0.15, "ten_split": 0.10, "vertical": 0.10, "short_shuttle": 0.08, "three_cone": 0.07},
    "IOL":  {"arm_length": 0.20, "hand_size": 0.15, "forty": 0.15, "ten_split": 0.10, "vertical": 0.12, "short_shuttle": 0.14, "three_cone": 0.14},
    "CB":   {"forty": 0.28, "ten_split": 0.22, "arm_length": 0.15, "vertical": 0.12, "broad_jump": 0.10, "short_shuttle": 0.08, "three_cone": 0.05},
    "WR":   {"forty": 0.25, "ten_split": 0.20, "vertical": 0.20, "broad_jump": 0.15, "three_cone": 0.10, "short_shuttle": 0.10},
    "S":    {"forty": 0.22, "ten_split": 0.18, "arm_length": 0.12, "vertical": 0.14, "broad_jump": 0.12, "three_cone": 0.12, "short_shuttle": 0.10},
    "LB":   {"forty": 0.20, "ten_split": 0.15, "arm_length": 0.10, "vertical": 0.15, "broad_jump": 0.15, "three_cone": 0.15, "short_shuttle": 0.10},
    "TE":   {"forty": 0.18, "ten_split": 0.12, "arm_length": 0.18, "vertical": 0.15, "broad_jump": 0.15, "three_cone": 0.12, "short_shuttle": 0.10},
    "RB":   {"forty": 0.25, "ten_split": 0.18, "vertical": 0.18, "broad_jump": 0.18, "three_cone": 0.12, "short_shuttle": 0.09},
    "IDL":  {"forty": 0.18, "ten_split": 0.15, "arm_length": 0.22, "hand_size": 0.15, "vertical": 0.12, "broad_jump": 0.10, "three_cone": 0.08},
}


def _parse_height_to_inches(h):
    """Convert '6-3', '6\'3"', or integer inches to float."""
    if h is None:
        return None
    try:
        return float(h)
    except (TypeError, ValueError):
        pass
    s = str(h).strip()
    m = re.match(r"(\d+)['\-](\d+)", s)
    if m:
        return int(m.group(1)) * 12 + int(m.group(2))
    return None


def compute_combine_score(measurables, position):
    """Return position-adjusted athletic score in [-1.0, +1.0].

    Uses z-score deviation from position-specific benchmarks, weighted
    by position-relevant metric importance.  Returns 0.0 when < 2 metrics
    are available (insufficient data).
    """
    if not measurables or not position:
        return 0.0
    pos = position.upper().strip()
    if pos not in _POSITION_COMBINE_WEIGHTS:
        pos = "LB"  # fallback

    benchmarks = _COMBINE_BENCHMARKS
    weights = _POSITION_COMBINE_WEIGHTS[pos]

    scored_weight = 0.0
    weighted_score = 0.0
    for metric, weight in weights.items():
        raw = measurables.get(metric)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        if metric not in benchmarks or pos not in benchmarks[metric]:
            continue
        ideal, scale, direction = benchmarks[metric][pos]
        z = direction * (val - ideal) / scale
        z = max(-2.5, min(2.5, z))
        weighted_score += z * weight
        scored_weight += weight

    if scored_weight < 0.15:
        return 0.0
    raw_score = weighted_score / scored_weight
    return round(max(-1.0, min(1.0, raw_score / 2.0)), 3)


# ---------------------------------------------------------------------------
# CFB PRODUCTION SCORING
# ---------------------------------------------------------------------------
# Format: {stat: (ideal, scale, direction, weight)}
# direction: +1 = higher is better, -1 = lower is better
_CFB_BENCHMARKS = {
    "QB": {
        "completion_pct":     (0.66, 0.08, 1, 0.25),
        "td_int_ratio":       (3.0,  1.5,  1, 0.25),
        "yards_per_attempt":  (8.5,  1.5,  1, 0.20),
        "snap_share":         (0.90, 0.10, 1, 0.15),
        "games_played":       (12,   3,    1, 0.15),
    },
    "EDGE": {
        "pressure_rate":          (0.12, 0.05, 1, 0.35),
        "sack_rate":              (0.08, 0.04, 1, 0.25),
        "missed_tackles_forced":  (12,   6,    1, 0.20),
        "snap_share":             (0.75, 0.15, 1, 0.20),
    },
    "IDL": {
        "pressure_rate":          (0.08, 0.04, 1, 0.35),
        "run_stop_rate":          (0.09, 0.04, 1, 0.30),
        "missed_tackles_forced":  (6,    3,    1, 0.15),
        "snap_share":             (0.70, 0.15, 1, 0.20),
    },
    "OT": {
        "pressure_rate_allowed":  (0.04, 0.03, -1, 0.45),
        "sacks_allowed":          (2,    2,    -1, 0.30),
        "snap_share":             (0.90, 0.10, 1, 0.25),
    },
    "IOL": {
        "pressure_rate_allowed":  (0.05, 0.03, -1, 0.40),
        "sacks_allowed":          (2,    2,    -1, 0.30),
        "snap_share":             (0.88, 0.10, 1, 0.30),
    },
    "CB": {
        "coverage_grade":         (78,   10,   1, 0.35),
        "pbu_rate":               (0.14, 0.08, 1, 0.25),
        "snap_share":             (0.82, 0.12, 1, 0.20),
        "contested_catch_rate":   (0.45, 0.12, 1, 0.20),
    },
    "WR": {
        "target_share":           (0.22, 0.08, 1, 0.30),
        "yards_per_route":        (2.1,  0.7,  1, 0.25),
        "snap_share":             (0.85, 0.10, 1, 0.20),
        "drops_per_route":        (0.02, 0.02, -1, 0.25),
    },
    "S": {
        "coverage_grade":         (74,   10,   1, 0.30),
        "tackles_per_game":       (5.5,  2.0,  1, 0.25),
        "missed_tackle_rate":     (0.08, 0.05, -1, 0.25),
        "snap_share":             (0.85, 0.10, 1, 0.20),
    },
    "LB": {
        "tackles_per_game":       (7.5,  2.5,  1, 0.30),
        "pass_rush_grade":        (68,   12,   1, 0.25),
        "missed_tackle_rate":     (0.10, 0.06, -1, 0.25),
        "snap_share":             (0.85, 0.10, 1, 0.20),
    },
    "TE": {
        "target_share":           (0.15, 0.06, 1, 0.25),
        "yards_per_route":        (1.8,  0.6,  1, 0.25),
        "blocking_grade":         (68,   12,   1, 0.25),
        "snap_share":             (0.70, 0.15, 1, 0.25),
    },
    "RB": {
        "yards_per_carry":        (5.5,  1.2,  1, 0.30),
        "missed_tackles_forced":  (25,   10,   1, 0.25),
        "yards_after_contact":    (3.2,  0.8,  1, 0.25),
        "snap_share":             (0.55, 0.20, 1, 0.20),
    },
}


def compute_cfb_production_score(cfb_stats, position):
    """Return production signal in [-0.5, +0.5].  Returns 0 if no CFB data."""
    if not cfb_stats or not position:
        return 0.0
    pos = position.upper().strip()
    benchmarks = _CFB_BENCHMARKS.get(pos)
    if not benchmarks:
        return 0.0

    scored_weight = 0.0
    weighted_score = 0.0
    for stat, (ideal, scale, direction, weight) in benchmarks.items():
        raw = cfb_stats.get(stat)
        if raw is None:
            continue
        try:
            val = float(raw)
        except (TypeError, ValueError):
            continue
        z = direction * (val - ideal) / scale
        z = max(-2.5, min(2.5, z))
        weighted_score += z * weight
        scored_weight += weight

    if scored_weight < 0.10:
        return 0.0
    raw_score = weighted_score / scored_weight
    return round(max(-0.5, min(0.5, raw_score * 0.25)), 3)


# ---------------------------------------------------------------------------
# INJURY RISK
# ---------------------------------------------------------------------------
def compute_injury_risk_penalty(injury_history):
    """Return penalty in [-0.5, 0].  Scales with availability and known injuries."""
    if not injury_history:
        return 0.0
    if injury_history.get("flag") is True:
        risk = injury_history.get("risk_level", "moderate")
        avail = injury_history.get("availability_pct")
        base = {"high": -0.50, "moderate": -0.25, "low": -0.10}.get(risk, -0.20)
        if avail is not None:
            try:
                avail = float(avail)
                if avail < 0.70:
                    base = min(base - 0.15, -0.50)
                elif avail < 0.85:
                    base = base - 0.05
            except (TypeError, ValueError):
                pass
        return round(max(-0.50, base), 3)
    return 0.0


# ---------------------------------------------------------------------------
# BOARD VELOCITY
# ---------------------------------------------------------------------------
def compute_board_velocity_signal(board_velocity):
    """Return velocity signal in [-0.2, +0.2].  Positive = rising = good signal."""
    if not board_velocity:
        return 0.0
    weekly = board_velocity.get("weekly_change")
    if weekly is not None:
        try:
            wc = float(weekly)
            return round(max(-0.20, min(0.20, wc / 20.0)), 3)
        except (TypeError, ValueError):
            pass
    stability = board_velocity.get("stability")
    if stability == "unstable":
        return -0.10
    return 0.0


# ---------------------------------------------------------------------------
# RECRUITING SIGNAL
# ---------------------------------------------------------------------------
def compute_recruiting_signal(recruiting):
    """Return recruiting/upside signal in [-0.1, +0.2].

    Higher stars + lower breakout age = upside.  Lower stars + late breakout = risk.
    """
    if not recruiting:
        return 0.0
    stars = recruiting.get("stars_247") or recruiting.get("stars_on3")
    breakout_age = recruiting.get("breakout_age")
    composite = recruiting.get("composite_rating")

    score = 0.0
    if composite is not None:
        try:
            c = float(composite)
            score += (c - 0.90) * 1.5
        except (TypeError, ValueError):
            pass
    elif stars is not None:
        try:
            s = float(stars)
            score += (s - 3.5) * 0.10
        except (TypeError, ValueError):
            pass

    if breakout_age is not None:
        try:
            ba = float(breakout_age)
            if ba <= 19.5:
                score += 0.08
            elif ba <= 20.5:
                score += 0.04
            elif ba >= 22.0:
                score -= 0.05
        except (TypeError, ValueError):
            pass

    return round(max(-0.10, min(0.20, score)), 3)


# ---------------------------------------------------------------------------
# MULTI-SOURCE CONSENSUS CONFIDENCE
# ---------------------------------------------------------------------------
def compute_source_confidence(source_ranks):
    """Return a confidence multiplier in [0.7, 1.0].

    When multiple sources agree on a player's rank, the board signal is reliable.
    High spread = apply a dampening factor to board_delta.
    """
    if not source_ranks:
        return 1.0
    values = []
    for k, v in source_ranks.items():
        if k.startswith("_"):
            continue
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            pass
    if len(values) < 2:
        return 1.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    std = math.sqrt(variance)
    # std > 12 → low confidence; std < 3 → high confidence
    confidence = max(0.70, min(1.0, 1.0 - (std / 12.0) * 0.30))
    return round(confidence, 3)


# ---------------------------------------------------------------------------
# TEAM SCHEMES + CAP CONTEXT LOADERS
# ---------------------------------------------------------------------------
def load_team_schemes():
    """Load coordinator scheme tendencies for all 32 teams."""
    try:
        return _load_json("team_schemes.json")
    except (OSError, json.JSONDecodeError):
        return {}


def load_cap_context():
    """Load team cap space and positional urgency data."""
    try:
        return _load_json("team_cap_context.json")
    except (OSError, json.JSONDecodeError):
        return {}


def compute_scheme_bonus(position, team, team_schemes=None):
    """Return scheme-fit bonus in [0, +0.4].

    A premium scheme fit gives an extra boost beyond the raw need bonus.
    """
    if not team or not position or not team_schemes:
        return 0.0
    pos = position.upper().strip()
    team_key = team.upper().strip()
    teams_data = team_schemes.get("teams", {})
    team_data = teams_data.get(team_key)
    if not team_data:
        return 0.0
    fit_scores = team_data.get("scheme_fit_scores", {})
    fit = fit_scores.get(pos, 1.0)
    try:
        fit = float(fit)
    except (TypeError, ValueError):
        return 0.0
    bonus = max(0.0, (fit - 1.0) * 1.5)
    return round(min(0.40, bonus), 3)


def compute_cap_bonus(position, team, cap_context=None):
    """Return cap/roster urgency bonus in [0, +0.2].

    Teams with cap space and high positional urgency get an extra reward
    for addressing that position.
    """
    if not team or not position or not cap_context:
        return 0.0
    pos = position.upper().strip()
    team_key = team.upper().strip()
    teams_data = cap_context.get("teams", {})
    team_data = teams_data.get(team_key)
    if not team_data:
        return 0.0
    urgency = team_data.get("position_urgency", {}).get(pos, 0.0)
    cap_tier = team_data.get("cap_tier", "medium")
    cap_mult = {"high": 1.20, "medium": 1.0, "low": 0.80, "over": 0.60}.get(cap_tier, 1.0)
    try:
        urgency = float(urgency)
    except (TypeError, ValueError):
        return 0.0
    bonus = urgency * 0.20 * cap_mult
    return round(min(0.20, max(0.0, bonus)), 3)


# ---------------------------------------------------------------------------
# SAVE / LOAD EVALUATED DRAFTS
# ---------------------------------------------------------------------------
EVALUATED_DRAFTS_PATH = os.path.join(DATA_DIR, "evaluated_drafts.json")


def save_evaluated_draft(state):
    """Persist a completed live draft evaluation."""
    results = _load_evaluated_drafts()
    entry = {
        "year": state["year"],
        "evaluated_at": utc_timestamp(),
        "num_picks": len(state["picks"]),
        "picks": state["picks"],
        "graded_picks": state["graded_picks"],
        "trades": state["trades"],
    }
    results.append(entry)
    results = results[-20:]
    with open(EVALUATED_DRAFTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def _load_evaluated_drafts():
    try:
        with open(EVALUATED_DRAFTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
