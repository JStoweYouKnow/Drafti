"""Ingest CFB production stats and enrich consensus board prospects.

Primary source: CollegeFootballData player season stats API.
This script is resilient to partial data and only fills missing fields when
existing board rows already have values.

Usage:
    python pro/cfb_production_ingest.py 2026
    python pro/cfb_production_ingest.py 2025 2026
    python pro/cfb_production_ingest.py --all
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict

import requests


DATA_DIR = os.environ.get("DRAFTI_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CFBD_BASE_URL = "https://api.collegefootballdata.com/stats/player/season"


def _norm(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name or "").strip().lower())
    n = re.sub(r"\s+(jr\.?|sr\.?|ii+|iv|v|vi)$", "", n)
    return n


def _safe_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _load_board(year: int) -> dict | None:
    path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_board(year: int, board: dict) -> None:
    path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2)


def _available_board_years() -> list[int]:
    years = []
    for fname in os.listdir(DATA_DIR):
        m = re.fullmatch(r"consensus_board_(\d{4})\.json", fname)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def _cfbd_headers() -> dict:
    token = (
        os.environ.get("CFBD_API_KEY")
        or os.environ.get("COLLEGEFOOTBALLDATA_API_KEY")
        or os.environ.get("CFB_API_KEY")
        or ""
    ).strip()
    headers = {
        "Accept": "application/json",
        "User-Agent": "DraftiPro-CFB-Ingest/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _fetch_cfbd_season_stats(season_year: int) -> list[dict]:
    headers = _cfbd_headers()
    if "Authorization" not in headers:
        return []
    try:
        resp = requests.get(CFBD_BASE_URL, params={"year": season_year}, headers=headers, timeout=35)
        if resp.status_code != 200:
            return []
        payload = resp.json()
        return payload if isinstance(payload, list) else []
    except requests.RequestException:
        return []


def _add_stat(bucket: dict, key: str, val) -> None:
    f = _safe_float(val)
    if f is None:
        return
    bucket[key] = bucket.get(key, 0.0) + f


def _build_player_stats(rows: list[dict], season_year: int) -> dict[str, dict]:
    """Normalize CFBD stat rows into board-friendly cfb_stats dicts."""
    players: dict[str, dict] = defaultdict(lambda: {"_season_year": season_year, "_source": "collegefootballdata"})
    for row in rows:
        if not isinstance(row, dict):
            continue
        player = str(row.get("player", "") or row.get("name", "")).strip()
        if not player:
            continue
        key = _norm(player)
        category = str(row.get("category", "")).strip().lower()
        stat_type = str(row.get("statType", "")).strip().lower()
        stat_val = row.get("stat")
        p = players[key]
        p["_name"] = player

        # Passing
        if category == "passing":
            if "comp" in stat_type:
                _add_stat(p, "_pass_comp", stat_val)
            elif stat_type in {"att", "attempts"}:
                _add_stat(p, "_pass_att", stat_val)
            elif stat_type in {"yds", "pass yds", "yards"}:
                _add_stat(p, "_pass_yds", stat_val)
            elif stat_type in {"td", "pass td", "touchdowns"}:
                _add_stat(p, "_pass_td", stat_val)
            elif stat_type in {"int", "ints", "interceptions"}:
                _add_stat(p, "_pass_int", stat_val)
        # Rushing
        elif category == "rushing":
            if stat_type in {"att", "attempts", "car"}:
                _add_stat(p, "_rush_att", stat_val)
            elif stat_type in {"yds", "yards", "rush yds"}:
                _add_stat(p, "_rush_yds", stat_val)
            elif stat_type in {"td", "touchdowns", "rush td"}:
                _add_stat(p, "_rush_td", stat_val)
        # Receiving
        elif category == "receiving":
            if stat_type in {"rec", "receptions"}:
                _add_stat(p, "_rec", stat_val)
            elif stat_type in {"targets", "tgt"}:
                _add_stat(p, "_targets", stat_val)
            elif stat_type in {"yds", "yards", "rec yds"}:
                _add_stat(p, "_rec_yds", stat_val)
            elif stat_type in {"td", "touchdowns", "rec td"}:
                _add_stat(p, "_rec_td", stat_val)
        # Defense
        elif category in {"defensive", "defense"}:
            if "tack" in stat_type:
                _add_stat(p, "_tackles", stat_val)
            elif "sack" in stat_type:
                _add_stat(p, "_sacks", stat_val)
            elif "pbu" in stat_type or "pass break" in stat_type:
                _add_stat(p, "_pbu", stat_val)
            elif "int" == stat_type or "interceptions" in stat_type:
                _add_stat(p, "_def_int", stat_val)
        # General
        if stat_type in {"gp", "games", "games played"}:
            _add_stat(p, "_games", stat_val)

    # Derive board-facing fields
    out = {}
    for key, p in players.items():
        cfb = {
            "_source": p.get("_source"),
            "_season_year": p.get("_season_year"),
        }
        pass_att = p.get("_pass_att", 0.0)
        pass_comp = p.get("_pass_comp", 0.0)
        pass_yds = p.get("_pass_yds", 0.0)
        pass_td = p.get("_pass_td", 0.0)
        pass_int = p.get("_pass_int", 0.0)
        rush_att = p.get("_rush_att", 0.0)
        rush_yds = p.get("_rush_yds", 0.0)
        games = p.get("_games", 0.0)
        tackles = p.get("_tackles", 0.0)
        sacks = p.get("_sacks", 0.0)
        pbu = p.get("_pbu", 0.0)
        rec = p.get("_rec", 0.0)
        targets = p.get("_targets", 0.0)
        rec_yds = p.get("_rec_yds", 0.0)

        if pass_att > 0:
            cfb["completion_pct"] = round(pass_comp / pass_att, 3)
            cfb["yards_per_attempt"] = round(pass_yds / pass_att, 2)
            cfb["td_int_ratio"] = round(pass_td / max(1.0, pass_int), 2)
        if rush_att > 0:
            cfb["yards_per_carry"] = round(rush_yds / rush_att, 2)
        if rec > 0:
            cfb["yards_per_route"] = round(rec_yds / rec, 2)
        if targets > 0:
            cfb["target_share"] = round(rec / targets, 3)
        if games > 0:
            cfb["games_played"] = int(round(games))
            if tackles > 0:
                cfb["tackles_per_game"] = round(tackles / games, 2)
            if sacks > 0:
                cfb["sack_rate"] = round(sacks / games, 3)
            if pbu > 0:
                cfb["pbu_rate"] = round(pbu / games, 3)

        # Skip rows with no model-facing metrics.
        metrics = [k for k in cfb.keys() if not k.startswith("_")]
        if metrics:
            out[key] = cfb
    return out


def enrich_board(year: int, overwrite: bool = False) -> dict:
    board = _load_board(year)
    if not board:
        return {"year": year, "ok": False, "reason": "board_missing"}

    season_year = year - 1
    rows = _fetch_cfbd_season_stats(season_year)
    if not rows:
        return {"year": year, "ok": False, "reason": "cfbd_fetch_failed_or_no_api_key", "season_year": season_year}

    lookup = _build_player_stats(rows, season_year)
    enriched = 0
    matched = 0
    for p in board.get("prospects", []):
        k = _norm(p.get("name", ""))
        cfb = lookup.get(k)
        if cfb is None:
            # partial match fallback
            for lk, lv in lookup.items():
                if k and (k in lk or lk in k):
                    cfb = lv
                    break
        if not cfb:
            continue
        matched += 1
        existing = p.setdefault("cfb_stats", {})
        changed = False
        for mk, mv in cfb.items():
            if mk.startswith("_"):
                continue
            if overwrite or existing.get(mk) is None:
                existing[mk] = mv
                changed = True
        # keep source metadata even if no metric changed
        existing["_source"] = "collegefootballdata"
        existing["_season_year"] = season_year
        if changed:
            enriched += 1

    sources = board.setdefault("sources", [])
    if "CollegeFootballData API (player season stats)" not in sources:
        sources.append("CollegeFootballData API (player season stats)")
    board["last_updated"] = time.strftime("%Y-%m-%d")
    _save_board(year, board)
    return {
        "year": year,
        "ok": True,
        "season_year": season_year,
        "cfbd_rows": len(rows),
        "players_with_cfb_stats": len(lookup),
        "prospects_matched": matched,
        "prospects_enriched": enriched,
    }


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python pro/cfb_production_ingest.py 2026")
        print("  python pro/cfb_production_ingest.py 2025 2026")
        print("  python pro/cfb_production_ingest.py --all")
        sys.exit(1)

    if "--all" in args:
        years = _available_board_years()
    else:
        years = []
        for a in args:
            try:
                years.append(int(a))
            except ValueError:
                pass
    years = sorted(set(years))
    if not years:
        print("No valid years specified.")
        sys.exit(1)

    results = [enrich_board(y) for y in years]
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
