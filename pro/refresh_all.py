"""DRAFTi Pro — Master data refresh orchestrator.

Runs all data pipelines in the correct order, checking staleness before
each step so it only re-fetches what actually needs updating.

Staleness thresholds (configurable below):
  - Consensus board (current year)  : 7 days during draft season, 30 days off-season
  - Consensus board (historical)    : 90 days (boards rarely change after the draft)
  - Combine data                    : 14 days (combine only runs once ~Feb, then stable)
  - Historical draft outcomes        : 30 days (nflverse updates seasonally)
  - Cap context                     : 7 days (free agency moves fast in March-April)

Usage:
    python pro/refresh_all.py                   # smart refresh (staleness-gated)
    python pro/refresh_all.py --force           # refresh everything regardless of age
    python pro/refresh_all.py --board           # board + velocity only
    python pro/refresh_all.py --combine         # combine measurables only
    python pro/refresh_all.py --historical      # historical outcomes only
    python pro/refresh_all.py --status          # show staleness report, no fetching
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

DATA_DIR = os.environ.get("DRAFTI_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# STALENESS CONFIG  (days)
# ---------------------------------------------------------------------------
CURRENT_YEAR = 2026
DRAFT_SEASON_MONTHS = {1, 2, 3, 4}   # Jan–Apr: refresh more aggressively

def _is_draft_season():
    return datetime.now().month in DRAFT_SEASON_MONTHS

THRESHOLDS = {
    "board_current":    7  if _is_draft_season() else 30,
    "board_historical": 90,
    "combine":          14,
    "historical":       30,
    "cap_context":      7  if _is_draft_season() else 30,
}

# ---------------------------------------------------------------------------
# STALENESS HELPERS
# ---------------------------------------------------------------------------
def _file_age_days(path):
    """Return age of file in days, or 9999 if it doesn't exist."""
    if not os.path.exists(path):
        return 9999
    mtime = os.path.getmtime(path)
    age = (time.time() - mtime) / 86400
    return round(age, 1)


def _board_age(year):
    return _file_age_days(os.path.join(DATA_DIR, f"consensus_board_{year}.json"))


def _board_has_velocity(year):
    """Check if the current board has velocity data populated."""
    path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            board = json.load(f)
        prospects = board.get("prospects", [])
        return any(p.get("board_velocity", {}).get("rank_history") for p in prospects[:5])
    except Exception:
        return False


def _board_has_combine(year):
    """Check if the current board has combine measurables populated."""
    path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    if not os.path.exists(path):
        return False
    try:
        with open(path) as f:
            board = json.load(f)
        prospects = board.get("prospects", [])
        return any(
            any(v is not None for v in p.get("measurables", {}).values())
            for p in prospects[:20]
        )
    except Exception:
        return False


def available_board_years():
    years = []
    for fname in os.listdir(DATA_DIR):
        m = re.fullmatch(r"consensus_board_(\d{4})\.json", fname)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


# ---------------------------------------------------------------------------
# RUNNER
# ---------------------------------------------------------------------------
def _run(script, args=None, label=""):
    """Run a pro/ script as a subprocess. Returns True on success."""
    cmd = [sys.executable, os.path.join(SCRIPT_DIR, script)] + (args or [])
    label = label or script
    print(f"\n{'─' * 60}")
    print(f"▶  {label}")
    print(f"   {' '.join(cmd)}")
    print(f"{'─' * 60}")
    start = time.time()
    result = subprocess.run(cmd, cwd=os.path.dirname(SCRIPT_DIR))
    elapsed = round(time.time() - start, 1)
    if result.returncode == 0:
        print(f"   ✓ Done in {elapsed}s")
        return True
    else:
        print(f"   ✗ Failed (exit {result.returncode}) after {elapsed}s")
        return False


# ---------------------------------------------------------------------------
# REFRESH TASKS
# ---------------------------------------------------------------------------
def refresh_board(force=False):
    """Re-scrape the current year's consensus board (velocity is computed inside)."""
    age = _board_age(CURRENT_YEAR)
    threshold = THRESHOLDS["board_current"]
    if not force and age < threshold:
        print(f"  Board {CURRENT_YEAR}: {age}d old (threshold {threshold}d) — skipping")
        return False
    print(f"  Board {CURRENT_YEAR}: {age}d old — refreshing")
    return _run("scrape_consensus_board.py", [str(CURRENT_YEAR)],
                label=f"Scrape {CURRENT_YEAR} consensus board (multi-source + velocity)")


def refresh_historical_boards(force=False):
    """Re-scrape any historical boards that are stale."""
    years = [y for y in available_board_years() if y < CURRENT_YEAR]
    refreshed = 0
    for year in years:
        age = _board_age(year)
        threshold = THRESHOLDS["board_historical"]
        if not force and age < threshold:
            print(f"  Board {year}: {age}d old — skipping")
            continue
        print(f"  Board {year}: {age}d old — refreshing")
        ok = _run("scrape_consensus_board.py", [str(year)],
                  label=f"Scrape {year} consensus board")
        if ok:
            refreshed += 1
        time.sleep(4)
    return refreshed > 0


def refresh_combine(force=False):
    """Fetch combine measurables from nflverse + PFR and enrich boards."""
    # Run for current year always, plus recent years if stale
    years_to_enrich = [CURRENT_YEAR]
    for year in available_board_years():
        if year >= CURRENT_YEAR - 2 and not _board_has_combine(year):
            years_to_enrich.append(year)
    years_to_enrich = sorted(set(years_to_enrich))

    if not force and _board_has_combine(CURRENT_YEAR):
        age = _board_age(CURRENT_YEAR)
        if age < THRESHOLDS["combine"]:
            print(f"  Combine data for {CURRENT_YEAR}: already present, board {age}d old — skipping")
            return False

    return _run("fetch_combine_data.py", [str(y) for y in years_to_enrich],
                label=f"Fetch combine measurables for {years_to_enrich}")


def refresh_historical_outcomes(force=False):
    """Re-download nflverse draft outcomes (career AV, status, etc.)."""
    hist_path = os.path.join(DATA_DIR, "historical_drafts.json")
    age = _file_age_days(hist_path)
    threshold = THRESHOLDS["historical"]
    if not force and age < threshold:
        print(f"  Historical drafts: {age}d old (threshold {threshold}d) — skipping")
        return False
    print(f"  Historical drafts: {age}d old — refreshing")
    ok = _run("build_historical_data.py", label="Rebuild historical draft outcomes (nflverse)")
    if ok:
        # After rebuilding, update consensus ranks from scraped boards
        _run("scrape_consensus_board.py", ["--update-ranks"],
             label="Sync historical consensus ranks")
    return ok


def refresh_cap_context(force=False):
    """Remind operator that cap context needs manual verification.

    Cap data changes weekly during free agency (March–April). OTC scraping
    is brittle and may produce stale numbers for specific teams. This step
    prints a staleness warning rather than auto-fetching, since bad cap data
    directly affects pick grades.
    """
    cap_path = os.path.join(DATA_DIR, "team_cap_context.json")
    age = _file_age_days(cap_path)
    threshold = THRESHOLDS["cap_context"]
    if age > threshold:
        print(f"\n  ⚠  team_cap_context.json is {age}d old (threshold {threshold}d).")
        print(f"     Update from: https://overthecap.com/salary-cap-space")
        print(f"     Edit: pro/data/team_cap_context.json")
        return False
    print(f"  Cap context: {age}d old — OK")
    return True


# ---------------------------------------------------------------------------
# STATUS REPORT
# ---------------------------------------------------------------------------
def print_status():
    """Print a staleness summary for all data files."""
    print("\n" + "=" * 60)
    print("DRAFTi Pro — Data Freshness Report")
    print("=" * 60)

    board_years = available_board_years()
    print(f"\n{'Source':<45} {'Age':>8}  {'Status'}")
    print("-" * 70)

    def _status(age, threshold):
        if age > threshold * 2:
            return "⛔ Very stale"
        if age > threshold:
            return "⚠  Stale"
        return "✓  Fresh"

    for year in board_years:
        age = _board_age(year)
        threshold = THRESHOLDS["board_current"] if year == CURRENT_YEAR else THRESHOLDS["board_historical"]
        has_vel = _board_has_velocity(year)
        has_comb = _board_has_combine(year)
        extras = []
        if not has_vel:
            extras.append("no velocity")
        if not has_comb:
            extras.append("no combine")
        extra_str = f"  [{', '.join(extras)}]" if extras else ""
        label = f"consensus_board_{year}.json{extra_str}"
        print(f"  {label:<43} {age:>6}d  {_status(age, threshold)}")

    hist_age = _file_age_days(os.path.join(DATA_DIR, "historical_drafts.json"))
    cap_age = _file_age_days(os.path.join(DATA_DIR, "team_cap_context.json"))
    print(f"  {'historical_drafts.json':<43} {hist_age:>6}d  {_status(hist_age, THRESHOLDS['historical'])}")
    print(f"  {'team_cap_context.json':<43} {cap_age:>6}d  {_status(cap_age, THRESHOLDS['cap_context'])}")

    print(f"\n  Draft season mode: {'ON' if _is_draft_season() else 'off'}")
    print(f"  Staleness thresholds: board={THRESHOLDS['board_current']}d, "
          f"combine={THRESHOLDS['combine']}d, "
          f"historical={THRESHOLDS['historical']}d, "
          f"cap={THRESHOLDS['cap_context']}d\n")


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    args = set(sys.argv[1:])
    force = "--force" in args

    if "--status" in args:
        print_status()
        return

    print_status()

    if "--board" in args:
        refresh_board(force=True)
        return

    if "--combine" in args:
        refresh_combine(force=True)
        return

    if "--historical" in args:
        refresh_historical_outcomes(force=True)
        return

    # Default: smart refresh all
    print("\n" + "=" * 60)
    print("Running smart refresh (force=" + str(force) + ")")
    print("=" * 60)

    refresh_board(force=force)
    refresh_combine(force=force)
    refresh_historical_outcomes(force=force)
    refresh_historical_boards(force=False)  # historical boards rarely need re-scraping
    refresh_cap_context(force=force)

    print("\n" + "=" * 60)
    print("Refresh complete.")
    print_status()


if __name__ == "__main__":
    main()
