"""Merge ESPN 7-round mock draft picks into a consensus board JSON.

Usage:
    python pro/ingest/merge_espn_mock.py --year 2026 \
      --url "https://www.espn.com/nfl/draft2026/story/_/id/48299038/..."
    python pro/ingest/merge_espn_mock.py --year 2026 --url "..." --dry-run
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Dict

import requests
from bs4 import BeautifulSoup


DEFAULT_URL = (
    "https://www.espn.com/nfl/draft2026/story/_/id/48299038/"
    "2026-nfl-mock-draft-seven-rounds-257-picks-projections-matt-miller"
)

POS_MAP = {
    "DE": "EDGE",
    "OLB": "EDGE",
    "DT": "IDL",
    "NT": "IDL",
    "DL": "IDL",
    "ILB": "LB",
    "MLB": "LB",
    "G": "IOL",
    "OG": "IOL",
    "C": "IOL",
    "T": "OT",
    "FS": "S",
    "SS": "S",
    "DB": "S",
    "HB": "RB",
    "FB": "RB",
    "PK": "K",
}

SUFFIX_RE = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b", re.I)


def _normalize_name(name: str) -> str:
    text = str(name or "").lower().replace(".", " ").replace("'", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = SUFFIX_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_pos(pos: str) -> str:
    p = str(pos or "").upper().strip()
    return POS_MAP.get(p, p)


def _clean_school(school: str) -> str:
    return re.sub(r"\s+", " ", str(school or "").strip().rstrip("."))


def _fetch_article_text(url: str) -> str:
    resp = requests.get(
        url,
        timeout=25,
        headers={
            "User-Agent": "DraftiPro-ESPN-Merge/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    resp.raise_for_status()
    # Convert HTML to line-oriented plain text so parsing is stable from CLI requests.
    return BeautifulSoup(resp.text, "html.parser").get_text("\n")


def _parse_espn_picks(article_text: str) -> Dict[int, dict]:
    rows: Dict[int, dict] = {}

    # Strategy A: markdown-like blocks (used by converted text fetchers)
    # Picks 1-100 appear as section headers and a first player line.
    heading_pat = re.compile(r"##\s*(\d{1,3})\.\s+[^\n]+")
    headings = list(heading_pat.finditer(article_text))
    for i, m in enumerate(headings):
        pick = int(m.group(1))
        if pick > 100:
            continue
        end = headings[i + 1].start() if i + 1 < len(headings) else len(article_text)
        chunk = article_text[m.end():end]
        pm = re.search(r"\[([^\]]+)\]\([^\)]*\)\.?\s*,\s*([^,\n]+),\s*([^\n]+)", chunk)
        if not pm:
            continue
        rows[pick] = {
            "rank": pick,
            "name": pm.group(1).strip().rstrip("."),
            "position": _normalize_pos(pm.group(2)),
            "school": _clean_school(pm.group(3)),
        }

    # Picks 101+ are in dense inline lists; parse each segment robustly.
    starts = [m.start() for m in re.finditer(r"(?<!\d)(\d{1,3})\.\s*\[", article_text)]
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(article_text)
        seg = article_text[start:end].strip()
        m = re.match(
            r"^(\d{1,3})\.\s*\[[^\]]+\]\([^\)]*\)(?:\([^\)]*\))*\*?\s*:\s*"
            r"\[([^\]]+)\]\([^\)]*\)\.?\s*,\s*([^,\n]+),\s*(.+?)\s*$",
            seg,
            re.S,
        )
        if not m:
            continue
        pick = int(m.group(1))
        if 101 <= pick <= 257:
            rows[pick] = {
                "rank": pick,
                "name": m.group(2).strip().rstrip("."),
                "position": _normalize_pos(m.group(3)),
                "school": _clean_school(m.group(4)),
            }

    if rows:
        return rows

    # Strategy B: raw ESPN page text from BeautifulSoup(html).get_text("\n")
    # Round 1-3 entries have this shape:
    #   1.
    #   Team Name
    #   Player Name
    #   , Pos, School
    pick_starts = list(re.finditer(r"(?m)^\s*(\d{1,3})\.\s*\n", article_text))
    for i, m in enumerate(pick_starts):
        pick = int(m.group(1))
        if not (1 <= pick <= 100):
            continue
        end = pick_starts[i + 1].start() if i + 1 < len(pick_starts) else len(article_text)
        chunk = article_text[m.end():end]
        # In each pick chunk, the first "name + , pos, school" tuple is the drafted player.
        pm = re.search(r"\n([^\n]+)\n\.?\s*,\s*([^,\n]+),\s*([^\n]+)", chunk)
        if not pm:
            continue
        rows[pick] = {
            "rank": pick,
            "name": pm.group(1).strip().rstrip("."),
            "position": _normalize_pos(pm.group(2)),
            "school": _clean_school(pm.group(3)),
        }

    # Round 4-7 entries in cleaned page text are multiline:
    #   101.
    #   Team Name
    #   (from ...)
    #   :
    #   Player Name
    #   , Pos, School
    rounds_4_7 = re.compile(
        r"(?ms)^\s*(\d{1,3})\.\s*\n[^\n]+\n"
        r"(?:\s*\([^\n]*\)\*?:\s*\n|\*?:\s*\n)\s*"
        r"([^\n]+)\n\.?\s*,\s*([^,\n]+),\s*([^\n]+)"
    )
    for m in rounds_4_7.finditer(article_text):
        pick = int(m.group(1))
        if 101 <= pick <= 257:
            rows[pick] = {
                "rank": pick,
                "name": m.group(2).strip().rstrip("."),
                "position": _normalize_pos(m.group(3)),
                "school": _clean_school(m.group(4)),
            }

    return rows


def _tier_for_rank(rank: int) -> int:
    if rank <= 5:
        return 1
    if rank <= 15:
        return 2
    if rank <= 32:
        return 3
    if rank <= 64:
        return 4
    return 5


def _merge_espn_into_board(board: dict, espn_rows: Dict[int, dict], add_missing: bool = True) -> dict:
    prospects = board.get("prospects", [])
    if not isinstance(prospects, list):
        raise ValueError("Board JSON has invalid prospects payload")

    # Best existing row per normalized name.
    best_index: dict[str, int] = {}
    for i, p in enumerate(prospects):
        key = _normalize_name(p.get("name", ""))
        if not key:
            continue
        rank = p.get("consensus_rank", 10**9)
        prev = best_index.get(key)
        if prev is None:
            best_index[key] = i
            continue
        prev_rank = prospects[prev].get("consensus_rank", 10**9)
        if isinstance(rank, int) and (not isinstance(prev_rank, int) or rank < prev_rank):
            best_index[key] = i

    matched = 0
    added = 0
    for rank in range(1, 258):
        row = espn_rows.get(rank)
        if row is None:
            continue
        key = _normalize_name(row["name"])
        idx = best_index.get(key)
        if idx is None:
            if not add_missing:
                continue
            prospects.append(
                {
                    "consensus_rank": rank,
                    "name": row["name"],
                    "position": row["position"],
                    "school": row["school"],
                    "grade": max(60.0, 100.0 - (rank - 1) * 0.5),
                    "tier": _tier_for_rank(rank),
                    "measurables": {"height": None, "weight": None, "forty": None, "arm": None},
                    "peak_rank": rank,
                    "source_ranks": {"espn_mock_miller_2026": rank},
                    "_merge_score": rank,
                }
            )
            added += 1
            continue

        p = prospects[idx]
        old_rank = p.get("consensus_rank")
        p.setdefault("source_ranks", {})
        if isinstance(old_rank, int):
            p["source_ranks"]["nflmockdraftdb"] = old_rank
        p["source_ranks"]["espn_mock_miller_2026"] = rank
        p["school"] = row["school"]
        p["position"] = row["position"]
        p["_merge_score"] = rank
        matched += 1

    # ESPN-derived rows lead ordering; untouched rows keep relative order below.
    for p in prospects:
        if "_merge_score" in p:
            continue
        old_rank = p.get("consensus_rank", 10**9)
        if not isinstance(old_rank, int):
            old_rank = 10**9
        p["_merge_score"] = 1000 + old_rank

    prospects.sort(key=lambda p: (p.get("_merge_score", 10**9), _normalize_name(p.get("name", ""))))
    for i, p in enumerate(prospects, start=1):
        p["consensus_rank"] = i
        p.pop("_merge_score", None)

    board["prospects"] = prospects
    board["last_updated"] = "2026-03-31"
    board["_description"] = "2026 NFL Draft consensus board (NFLMockDraftDB baseline + ESPN 7-round mock integration)."
    sources = board.get("sources", [])
    if isinstance(sources, list) and "ESPN Matt Miller 2026 7-round mock draft (id=48299038)" not in sources:
        sources.append("ESPN Matt Miller 2026 7-round mock draft (id=48299038)")
    board["sources"] = sources if isinstance(sources, list) else [str(sources)]
    board["_espn_mock_merge"] = {
        "article_id": "48299038",
        "num_picks_parsed": len(espn_rows),
        "num_matched_existing": matched,
        "num_added_new": added,
    }
    return board


def run_merge(year: int, url: str = DEFAULT_URL, dry_run: bool = False, add_missing: bool = True) -> dict:
    board_path = Path(__file__).resolve().parents[1] / "data" / f"consensus_board_{year}.json"
    if not board_path.exists():
        raise FileNotFoundError(f"Board file not found: {board_path}")

    article_text = _fetch_article_text(url)
    espn_rows = _parse_espn_picks(article_text)
    if not espn_rows:
        raise ValueError("No picks parsed from ESPN article.")

    with board_path.open("r", encoding="utf-8") as f:
        board = json.load(f)
    board = _merge_espn_into_board(board, espn_rows, add_missing=add_missing)

    if not dry_run:
        with board_path.open("w", encoding="utf-8") as f:
            json.dump(board, f, indent=2)

    return {
        "board_file": str(board_path),
        "year": year,
        "url": url,
        "num_picks_parsed": len(espn_rows),
        "num_prospects_total": len(board.get("prospects", [])),
        "merge": board.get("_espn_mock_merge", {}),
        "dry_run": bool(dry_run),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge ESPN mock draft picks into consensus board JSON.")
    parser.add_argument("--year", type=int, required=True, help="Draft year (e.g. 2026)")
    parser.add_argument("--url", default=DEFAULT_URL, help="ESPN mock draft article URL")
    parser.add_argument("--dry-run", action="store_true", help="Do not write board file")
    parser.add_argument("--no-add-missing", action="store_true", help="Do not append new names from ESPN")
    args = parser.parse_args()

    try:
        result = run_merge(
            year=args.year,
            url=args.url,
            dry_run=args.dry_run,
            add_missing=not args.no_add_missing,
        )
    except (FileNotFoundError, ValueError, requests.RequestException) as exc:
        raise SystemExit(str(exc)) from exc

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
