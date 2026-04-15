"""Fetch NFL combine measurements and enrich consensus board prospect data.

Two sources, tried in order:
  1. nflverse combine CSV — height, weight, 40yd, vertical, broad jump, 3-cone, shuttle
  2. Pro Football Reference combine page — arm length, hand size (supplements nflverse)

Matches players by name to prospects on the saved consensus board JSON and
writes the measurables in-place, preserving all other existing fields.

Usage:
    python pro/fetch_combine_data.py 2026        # enrich 2026 board
    python pro/fetch_combine_data.py 2025 2024   # enrich multiple years
    python pro/fetch_combine_data.py --all        # enrich all saved boards
"""
import csv
import io
import json
import os
import re
import ssl
import sys
import time
import urllib.request

import certifi
import requests
from bs4 import BeautifulSoup

DATA_DIR = os.environ.get("DRAFTI_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

NFLVERSE_COMBINE_CSV = (
    "https://github.com/nflverse/nflverse-data/releases/download/combine/combine.csv"
)

PFR_COMBINE_URL = "https://www.pro-football-reference.com/draft/{year}-combine.htm"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

CRAWL_DELAY = 4


# ---------------------------------------------------------------------------
# NAME NORMALIZATION
# ---------------------------------------------------------------------------
def _norm(name):
    """Lowercase, strip, collapse whitespace, remove suffixes."""
    n = re.sub(r"\s+", " ", str(name or "").strip().lower())
    n = re.sub(r"\s+(jr\.?|sr\.?|ii+|iv|v|vi)$", "", n)
    return n


def _ht_to_str(raw):
    """Convert nflverse height '6-3' or '75' (inches) to display string."""
    if raw is None:
        return None
    s = str(raw).strip()
    if re.match(r"^\d+-\d+$", s):
        return s
    try:
        total = int(float(s))
        return f"{total // 12}-{total % 12}"
    except (ValueError, TypeError):
        return s or None


def _safe_float(val):
    try:
        f = float(val)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _safe_int(val):
    try:
        i = int(float(val))
        return i if i > 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# SOURCE 1: nflverse combine CSV
# ---------------------------------------------------------------------------
def fetch_nflverse_combine():
    """Download and parse nflverse combine CSV. Returns list of dicts."""
    print("  Downloading nflverse combine CSV...")
    req = urllib.request.Request(
        NFLVERSE_COMBINE_CSV, headers={"User-Agent": "Drafti/1.0"}
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        print(f"  nflverse combine error: {e}")
        return []

    print(f"  Downloaded {len(raw):,} bytes")
    reader = csv.DictReader(io.StringIO(raw))
    rows = []
    for row in reader:
        rows.append(row)
    print(f"  Parsed {len(rows):,} combine entries")
    return rows


def build_nflverse_lookup(rows, year):
    """Build {norm_name: measurables_dict} for a specific draft year."""
    lookup = {}
    for row in rows:
        try:
            season = int(float(row.get("season") or row.get("draft_year") or 0))
        except (TypeError, ValueError):
            continue
        if season != year:
            continue
        name = row.get("player_name") or row.get("pfr_player_name") or ""
        if not name:
            continue
        meas = {
            "height":       _ht_to_str(row.get("ht")),
            "weight":       _safe_int(row.get("wt")),
            "forty":        _safe_float(row.get("forty")),
            "vertical":     _safe_float(row.get("vertical")),
            "broad_jump":   _safe_int(row.get("broad_jump")),
            "three_cone":   _safe_float(row.get("cone")),
            "short_shuttle":_safe_float(row.get("shuttle")),
        }
        # Skip rows with no useful data
        if not any(v is not None for v in meas.values()):
            continue
        lookup[_norm(name)] = meas
    return lookup


# ---------------------------------------------------------------------------
# SOURCE 2: Pro Football Reference combine page (arm length, hand size)
# ---------------------------------------------------------------------------
def fetch_pfr_combine(year):
    """Scrape PFR combine page for arm length and hand size.

    Returns {norm_name: {arm_length: float, hand_size: float, ten_split: float}}.
    Returns empty dict on failure.
    """
    url = PFR_COMBINE_URL.format(year=year)
    print(f"  Trying PFR combine page: {url}")
    time.sleep(CRAWL_DELAY)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"  PFR returned {resp.status_code}")
            return {}
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", id="combine")
        if not table:
            # Try any table with combine-like columns
            table = soup.find("table")
        if not table:
            print("  PFR: no combine table found")
            return {}

        # Parse header to find column positions
        headers = []
        header_row = table.find("thead")
        if header_row:
            ths = header_row.find_all("th")
            headers = [th.get("data-stat", th.get_text(strip=True).lower()) for th in ths]

        def _col(row, col_name):
            """Get cell text by data-stat attribute."""
            td = row.find("td", {"data-stat": col_name})
            if td:
                return td.get_text(strip=True) or None
            return None

        lookup = {}
        for tr in table.select("tbody tr"):
            name_td = tr.find("td", {"data-stat": "player"})
            if not name_td:
                continue
            name_link = name_td.find("a")
            name = (name_link or name_td).get_text(strip=True)
            if not name:
                continue

            arm = _safe_float(_col(tr, "arm_length"))
            hand = _safe_float(_col(tr, "hand_size"))
            ten = _safe_float(_col(tr, "ten_yd_split"))

            extras = {}
            if arm:
                extras["arm_length"] = arm
            if hand:
                extras["hand_size"] = hand
            if ten:
                extras["ten_split"] = ten

            if extras:
                lookup[_norm(name)] = extras

        print(f"  PFR: {len(lookup)} entries with arm/hand/10-split data")
        return lookup

    except requests.RequestException as e:
        print(f"  PFR error: {e}")
        return {}


# ---------------------------------------------------------------------------
# BOARD ENRICHMENT
# ---------------------------------------------------------------------------
def enrich_board(year, nflverse_rows, pfr_lookup=None):
    """Load board for year, overlay combine measurables, save."""
    board_path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    if not os.path.exists(board_path):
        print(f"  No board file for {year}, skipping")
        return 0

    with open(board_path, "r", encoding="utf-8") as f:
        board = json.load(f)

    nflverse_lookup = build_nflverse_lookup(nflverse_rows, year)
    print(f"  {year}: nflverse has {len(nflverse_lookup)} combine entries")

    updated = 0
    no_match = []
    for prospect in board.get("prospects", []):
        name_key = _norm(prospect.get("name", ""))
        meas = prospect.setdefault("measurables", {})

        # Try exact match, then partial
        nflverse_data = nflverse_lookup.get(name_key)
        if nflverse_data is None:
            for k, v in nflverse_lookup.items():
                if name_key in k or k in name_key:
                    nflverse_data = v
                    break

        if nflverse_data:
            changed = False
            for field, val in nflverse_data.items():
                if val is not None and meas.get(field) is None:
                    meas[field] = val
                    changed = True
            if changed:
                updated += 1
        else:
            no_match.append(prospect.get("name", ""))

        # Overlay PFR arm/hand/10-split
        if pfr_lookup:
            pfr_data = pfr_lookup.get(name_key)
            if pfr_data is None:
                for k, v in pfr_lookup.items():
                    if name_key in k or k in name_key:
                        pfr_data = v
                        break
            if pfr_data:
                for field, val in pfr_data.items():
                    if val is not None and meas.get(field) is None:
                        meas[field] = val

    # Update source metadata
    sources = board.setdefault("sources", [])
    if "nflverse combine" not in " ".join(sources).lower():
        sources.append("nflverse combine CSV")
    if pfr_lookup and "pro football reference" not in " ".join(sources).lower():
        sources.append("Pro Football Reference (arm/hand)")

    import time as _time
    board["last_updated"] = _time.strftime("%Y-%m-%d")

    with open(board_path, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2)

    print(f"  {year}: updated measurables for {updated} prospects")
    if no_match and year >= 2024:
        print(f"  {year}: {len(no_match)} unmatched (combine not yet run or not invited)")
    return updated


# ---------------------------------------------------------------------------
# AVAILABLE BOARD YEARS
# ---------------------------------------------------------------------------
def available_board_years():
    years = []
    for fname in os.listdir(DATA_DIR):
        m = re.fullmatch(r"consensus_board_(\d{4})\.json", fname)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python pro/fetch_combine_data.py 2026")
        print("  python pro/fetch_combine_data.py 2024 2025 2026")
        print("  python pro/fetch_combine_data.py --all")
        sys.exit(1)

    if "--all" in args:
        years = available_board_years()
    else:
        years = []
        for a in args:
            try:
                years.append(int(a))
            except ValueError:
                print(f"Unknown argument: {a}")

    if not years:
        print("No valid years specified.")
        sys.exit(1)

    print(f"Fetching combine data for years: {years}")

    # Download nflverse CSV once (contains all years)
    nflverse_rows = fetch_nflverse_combine()

    total_updated = 0
    for year in years:
        print(f"\n--- {year} ---")
        pfr_lookup = fetch_pfr_combine(year)
        n = enrich_board(year, nflverse_rows, pfr_lookup)
        total_updated += n
        time.sleep(CRAWL_DELAY)

    print(f"\nDone. Total prospects enriched: {total_updated}")


if __name__ == "__main__":
    main()
