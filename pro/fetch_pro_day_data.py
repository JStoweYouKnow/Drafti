"""Fetch and merge pro-day measurables from curated source URLs.

This is a low-confidence enrichment layer. It only fills missing measurable
fields and never overwrites existing combine/PFR data.

Usage:
    python pro/fetch_pro_day_data.py 2026
    python pro/fetch_pro_day_data.py --all
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from typing import Iterable

import requests
from bs4 import BeautifulSoup


DATA_DIR = os.environ.get("DRAFTI_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
SEED_TEMPLATE = "pro_day_seed_sources_{year}.json"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip().lower())


def _available_board_years() -> list[int]:
    years = []
    for fname in os.listdir(DATA_DIR):
        m = re.fullmatch(r"consensus_board_(\d{4})\.json", fname)
        if m:
            years.append(int(m.group(1)))
    return sorted(years)


def _load_board(year: int) -> dict | None:
    path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_board(year: int, board: dict):
    path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2)


def _load_seed_urls(year: int) -> list[str]:
    path = os.path.join(DATA_DIR, SEED_TEMPLATE.format(year=year))
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("sources", [])
    if not isinstance(rows, list):
        return []
    urls = []
    for row in rows:
        if isinstance(row, dict):
            url = str(row.get("url", "")).strip()
            if url:
                urls.append(url)
    return sorted(set(urls))


def _fetch_page_text(url: str) -> str:
    resp = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "DraftiPro-ProDay/1.0",
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        },
    )
    if resp.status_code != 200:
        return ""
    return BeautifulSoup(resp.text, "html.parser").get_text("\n")


def _extract_metric(chunk: str, patterns: Iterable[tuple[str, str]]) -> dict:
    out = {}
    for key, pat in patterns:
        m = re.search(pat, chunk, re.I)
        if not m:
            continue
        val = m.group(1).strip()
        try:
            out[key] = float(val) if "." in val else int(val)
        except ValueError:
            continue
    return out


PRO_DAY_PATTERNS = (
    ("forty", r"(?:40(?:-yard)?(?: dash)?|forty)[^0-9]{0,20}(4\.\d{2})"),
    ("ten_split", r"(?:10(?:-yard)? split|ten split)[^0-9]{0,20}(1\.\d{2})"),
    ("vertical", r"(?:vertical|vert)[^0-9]{0,20}(\d{2}(?:\.\d)?)"),
    ("broad_jump", r"(?:broad(?: jump)?)[^0-9]{0,20}(\d{2,3})"),
    ("three_cone", r"(?:three[- ]cone|3[- ]cone)[^0-9]{0,20}(6\.\d{2}|7\.\d{2})"),
    ("short_shuttle", r"(?:short shuttle|20[- ]yard shuttle|shuttle)[^0-9]{0,20}(3\.\d{2}|4\.\d{2})"),
    ("arm_length", r"(?:arm length)[^0-9]{0,20}(\d{2}(?:\.\d{1,2})?)"),
    ("hand_size", r"(?:hand size)[^0-9]{0,20}(\d(?:\.\d{1,2})?)"),
)


def _extract_player_pro_day_metrics(page_text: str, player_name: str) -> dict:
    # Capture a small window around each player mention.
    escaped = re.escape(player_name)
    windows = []
    for m in re.finditer(escaped, page_text, re.I):
        start = max(0, m.start() - 60)
        end = min(len(page_text), m.end() + 220)
        windows.append(page_text[start:end])
    if not windows:
        return {}
    merged = {}
    for chunk in windows[:4]:
        extracted = _extract_metric(chunk, PRO_DAY_PATTERNS)
        for k, v in extracted.items():
            if k not in merged:
                merged[k] = v
    return merged


def enrich_pro_day(year: int) -> dict:
    board = _load_board(year)
    if not board:
        return {"year": year, "ok": False, "reason": "board_missing"}
    urls = _load_seed_urls(year)
    if not urls:
        return {"year": year, "ok": False, "reason": "seed_urls_missing"}

    page_texts = {}
    for url in urls:
        txt = _fetch_page_text(url)
        if txt:
            page_texts[url] = re.sub(r"\s+", " ", txt)

    if not page_texts:
        return {"year": year, "ok": False, "reason": "all_seed_fetch_failed", "num_seed_urls": len(urls)}

    updated = 0
    matched = 0
    for p in board.get("prospects", []):
        name = str(p.get("name", "")).strip()
        if not name:
            continue
        meas = p.setdefault("measurables", {})
        merged_metrics = {}
        source_hits = []
        for url, text in page_texts.items():
            m = _extract_player_pro_day_metrics(text, name)
            if not m:
                continue
            source_hits.append(url)
            for k, v in m.items():
                if k not in merged_metrics:
                    merged_metrics[k] = v
        if not merged_metrics:
            continue
        matched += 1
        changed = False
        for k, v in merged_metrics.items():
            # Low-confidence source: fill only missing fields.
            if meas.get(k) is None:
                meas[k] = v
                changed = True
        if changed:
            meas["_pro_day_source_confidence"] = "low"
            meas["_pro_day_sources"] = source_hits[:3]
            updated += 1

    sources = board.setdefault("sources", [])
    tag = "Pro Day seed sources (low-confidence fill-only)"
    if tag not in sources:
        sources.append(tag)
    board["last_updated"] = time.strftime("%Y-%m-%d")
    _save_board(year, board)
    return {
        "year": year,
        "ok": True,
        "num_seed_urls": len(urls),
        "num_seed_urls_fetched": len(page_texts),
        "prospects_matched_in_text": matched,
        "prospects_enriched": updated,
    }


def main():
    args = sys.argv[1:]
    if not args:
        print("Usage:")
        print("  python pro/fetch_pro_day_data.py 2026")
        print("  python pro/fetch_pro_day_data.py --all")
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
    results = [enrich_pro_day(y) for y in years]
    print(json.dumps({"results": results}, indent=2))


if __name__ == "__main__":
    main()
