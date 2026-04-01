"""Scrape consensus big board rankings from NFL Mock Draft Database.

Fetches the consensus big board for a given year and outputs JSON compatible
with draft_engine_pro.py's consensus board format.

Strategies (tried in order):
  1. Direct fetch from nflmockdraftdatabase.com with browser-like headers
  2. Wayback Machine cached snapshot (reliable for 2016-2024)
  3. Playwright headless browser (renders JS, bypasses anti-bot)

Usage:
    python pro/scrape_consensus_board.py 2024
    python pro/scrape_consensus_board.py 2025
    python pro/scrape_consensus_board.py 2026
    python pro/scrape_consensus_board.py --all          # Scrape all available years
    python pro/scrape_consensus_board.py --update-ranks  # Update historical_drafts.json with scraped ranks

Playwright setup (one-time):
    pip install playwright
    playwright install chromium
"""
import json
import os
import re
import sys
import time

import certifi
import requests
from bs4 import BeautifulSoup

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Realistic browser headers to avoid basic bot detection
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}

LIVE_URL_TEMPLATE = "https://www.nflmockdraftdatabase.com/big-boards/{year}/consensus-big-board-{year}"
WAYBACK_URL_TEMPLATE = (
    "https://web.archive.org/web/2024/{url}"
)

# Respect robots.txt crawl-delay
CRAWL_DELAY = 10


def fetch_page(year):
    """Fetch the consensus big board HTML. Tries live site first, then Wayback."""
    live_url = LIVE_URL_TEMPLATE.format(year=year)

    # Strategy 1: Direct fetch
    print(f"  Trying live site: {live_url}")
    try:
        session = requests.Session()
        # Hit the homepage first to get cookies
        session.get("https://www.nflmockdraftdatabase.com/", headers=HEADERS, timeout=15)
        time.sleep(2)
        resp = session.get(live_url, headers=HEADERS, timeout=15, allow_redirects=True)
        if resp.status_code == 200 and "mock-list-item" in resp.text:
            print(f"  Live site returned {len(resp.text):,} bytes with player data")
            return resp.text
        print(f"  Live site returned {resp.status_code}, no player data in HTML (anti-bot likely)")
    except requests.RequestException as e:
        print(f"  Live site error: {e}")

    # Strategy 2: Wayback Machine
    wayback_url = WAYBACK_URL_TEMPLATE.format(url=live_url)
    print(f"  Trying Wayback Machine: {wayback_url}")
    try:
        resp = requests.get(wayback_url, headers=HEADERS, timeout=20, allow_redirects=True)
        if resp.status_code == 200 and "mock-list-item" in resp.text:
            print(f"  Wayback returned {len(resp.text):,} bytes with player data")
            return resp.text
        print(f"  Wayback returned {resp.status_code}, no player data")
    except requests.RequestException as e:
        print(f"  Wayback error: {e}")

    # Strategy 3: Try different Wayback timestamps
    for ts in ["20260401", "20260301", "20260201", "20250401", "20250301",
               "20240401", "20240301", "20240201", "20231201", "20231001"]:
        wb_url = f"https://web.archive.org/web/{ts}/{live_url}"
        print(f"  Trying Wayback timestamp {ts}...")
        try:
            resp = requests.get(wb_url, headers=HEADERS, timeout=20, allow_redirects=True)
            if resp.status_code == 200 and "mock-list-item" in resp.text:
                print(f"  Wayback {ts} returned data")
                return resp.text
        except requests.RequestException:
            pass
        time.sleep(2)

    # Strategy 4: Playwright headless browser (renders JS, bypasses anti-bot)
    html = _fetch_with_playwright(live_url)
    if html:
        return html

    return None


def _fetch_with_playwright(url):
    """Fetch page using Playwright headless Chromium to bypass JS-based anti-bot."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  Playwright not installed. Run: pip install playwright && playwright install chromium")
        return None

    print(f"  Trying Playwright headless browser: {url}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            page = context.new_page()

            # Navigate to homepage first for cookies/session
            page.goto("https://www.nflmockdraftdatabase.com/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(2000)

            # Now fetch the target page
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

            # Wait for the player list to render (JS-rendered content)
            try:
                page.wait_for_selector("li.mock-list-item", timeout=15000)
            except Exception:
                # Try scrolling to trigger lazy loading
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(3000)
                try:
                    page.wait_for_selector("li.mock-list-item", timeout=10000)
                except Exception:
                    pass

            html = page.content()
            browser.close()

            if "mock-list-item" in html:
                print(f"  Playwright returned {len(html):,} bytes with player data")
                return html
            print("  Playwright rendered page but no player data found")
            return None

    except Exception as e:
        print(f"  Playwright error: {e}")
        return None


def parse_board(html_content, year):
    """Parse the consensus big board HTML into structured data."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Find the mock list
    mock_list = soup.find("ul", class_="mock-list")
    if not mock_list:
        print("  WARNING: Could not find mock-list element")
        return []

    items = mock_list.find_all("li", class_="mock-list-item")
    print(f"  Found {len(items)} players on the board")

    prospects = []
    for item in items:
        try:
            prospect = _parse_item(item)
            if prospect:
                prospects.append(prospect)
        except Exception as e:
            # Skip malformed entries
            continue

    # Assign tiers based on ranking clusters
    _assign_tiers(prospects)

    return prospects


def _parse_item(item):
    """Parse a single mock-list-item into a prospect dict."""
    # Rank
    pick_num_el = item.find("div", class_="pick-number")
    if not pick_num_el:
        return None
    rank_text = pick_num_el.get_text(strip=True)
    try:
        rank = int(rank_text)
    except ValueError:
        return None

    # Player name
    name_el = item.find("div", class_="player-name")
    if not name_el:
        return None
    name = name_el.get_text(strip=True)
    if not name:
        return None

    # Position and school from player-details
    details_el = item.find("div", class_="player-details")
    position = ""
    school = ""
    if details_el:
        details_text = details_el.get_text(separator="|", strip=True)
        parts = details_text.split("|")
        if parts:
            position = parts[0].strip()
        if len(parts) > 1:
            # School is usually the second part, may have movement indicators mixed in
            school_part = parts[1].strip()
            # Clean out movement numbers and arrows
            school = re.sub(r'\d+$', '', school_part).strip()

        # Try getting school from the link
        school_link = details_el.find("a")
        if school_link:
            school = school_link.get_text(strip=True)

    # Peak rank
    peak_el = item.find("div", class_="peak")
    peak = None
    if peak_el:
        peak_span = peak_el.find("span")
        if peak_span:
            try:
                peak = int(peak_span.get_text(strip=True))
            except ValueError:
                pass

    # Movement (riser/faller)
    movement = 0
    riser_el = item.find("div", class_="riser")
    faller_el = item.find("div", class_="faller")
    if riser_el:
        try:
            movement = int(re.sub(r'[^\d]', '', riser_el.get_text(strip=True)) or 0)
        except ValueError:
            pass
    elif faller_el:
        try:
            movement = -int(re.sub(r'[^\d]', '', faller_el.get_text(strip=True)) or 0)
        except ValueError:
            pass

    # Projected pick/team
    projected_pick = None
    projected_team = None
    right_container = item.find_all("div", class_="left-container")
    if len(right_container) > 1:
        proj = right_container[-1]
        proj_pick_el = proj.find("div", class_="pick-number")
        if proj_pick_el:
            spans = proj_pick_el.find_all("span")
            for s in spans:
                try:
                    projected_pick = int(s.get_text(strip=True).replace("#", ""))
                    break
                except ValueError:
                    continue
        team_img = proj.find("img", class_="team-logo")
        if team_img:
            alt = team_img.get("alt", "")
            projected_team = alt.replace(" Logo", "").strip()

    return {
        "consensus_rank": rank,
        "name": name,
        "position": _normalize_position(position),
        "school": school,
        "peak_rank": peak,
        "movement": movement,
        "projected_pick": projected_pick,
        "projected_team": projected_team,
    }


def _normalize_position(raw):
    """Normalize position strings to our standard set."""
    pos = raw.upper().strip()
    mapping = {
        "DE": "EDGE", "OLB": "EDGE",
        "DT": "IDL", "NT": "IDL", "DL": "IDL",
        "ILB": "LB", "MLB": "LB",
        "G": "IOL", "C": "IOL", "OG": "IOL",
        "T": "OT",
        "FS": "S", "SS": "S", "DB": "S",
        "FB": "RB", "HB": "RB",
        "PK": "K",
    }
    return mapping.get(pos, pos)


def _assign_tiers(prospects):
    """Assign tier labels based on ranking gaps."""
    if not prospects:
        return

    # Simple tier assignment: top 5 = tier 1, 6-15 = tier 2, 16-32 = tier 3, 33+ = tier 4
    for p in prospects:
        rank = p["consensus_rank"]
        if rank <= 5:
            p["tier"] = 1
        elif rank <= 15:
            p["tier"] = 2
        elif rank <= 32:
            p["tier"] = 3
        elif rank <= 64:
            p["tier"] = 4
        else:
            p["tier"] = 5


def scrape_espn_rankings(year):
    """Scrape ESPN draft rankings for a given year.

    Returns dict mapping lowercase player name -> ESPN rank, or empty dict on failure.
    ESPN's public draft rankings page uses a predictable URL pattern.
    """
    url = f"https://www.espn.com/nfl/draft/tracker/_/year/{year}"
    print(f"  Trying ESPN rankings: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  ESPN returned {resp.status_code}")
            return {}
        soup = BeautifulSoup(resp.text, "html.parser")
        rankings = {}
        rows = soup.select("tr.Table__TR")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            try:
                rank = int(cells[0].get_text(strip=True))
                name_el = cells[1].find("a") or cells[1]
                name = name_el.get_text(strip=True).lower()
                if name and rank:
                    rankings[name] = rank
            except (ValueError, IndexError):
                continue
        if rankings:
            print(f"  ESPN: parsed {len(rankings)} rankings")
        return rankings
    except requests.RequestException as e:
        print(f"  ESPN error: {e}")
        return {}


def scrape_tankathon_rankings(year):
    """Scrape Tankathon big board rankings.

    Tankathon aggregates several sources and publishes a public board.
    Returns dict mapping lowercase player name -> rank, or empty dict.
    """
    url = f"https://www.tankathon.com/big-board"
    print(f"  Trying Tankathon rankings: {url}")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"  Tankathon returned {resp.status_code}")
            return {}
        soup = BeautifulSoup(resp.text, "html.parser")
        rankings = {}
        items = soup.select(".player-name, .big-board-player")
        for i, item in enumerate(items, start=1):
            name = item.get_text(strip=True).lower()
            if name:
                rankings[name] = i
        if rankings:
            print(f"  Tankathon: parsed {len(rankings)} rankings")
        return rankings
    except requests.RequestException as e:
        print(f"  Tankathon error: {e}")
        return {}


# Source weighting: higher = more authoritative
SOURCE_WEIGHTS = {
    "nflmockdraftdb": 1.0,   # Large aggregation of mocks
    "espn": 0.85,             # Major outlet, respected scouts
    "tankathon": 0.75,        # Good aggregator
}


def compute_weighted_consensus(nflmdb_prospects, alt_sources):
    """Blend NFLMockDraftDB rankings with other sources using weighted average.

    alt_sources: dict of {source_name: {player_name_lower: rank}}
    Returns updated prospects list with source_ranks and blended consensus_rank.
    """
    if not alt_sources:
        return nflmdb_prospects

    # Build lookup: name -> NFLMDB rank
    nflmdb_lookup = {p["name"].lower().strip(): p["consensus_rank"] for p in nflmdb_prospects}

    for p in nflmdb_prospects:
        name_lower = p["name"].lower().strip()
        source_ranks = {"nflmockdraftdb": p["consensus_rank"]}

        for source, rankings in alt_sources.items():
            rank = rankings.get(name_lower)
            if rank is None:
                # Try partial name match
                for ranked_name, ranked_pos in rankings.items():
                    if name_lower in ranked_name or ranked_name in name_lower:
                        rank = ranked_pos
                        break
            if rank is not None:
                source_ranks[source] = rank

        # Compute weighted average rank across available sources
        total_weight = 0.0
        weighted_rank = 0.0
        for src, rank in source_ranks.items():
            w = SOURCE_WEIGHTS.get(src, 0.7)
            weighted_rank += rank * w
            total_weight += w

        blended_rank = round(weighted_rank / total_weight) if total_weight > 0 else p["consensus_rank"]

        # Apply recency decay: if blended_rank differs significantly, dampen change
        orig = p["consensus_rank"]
        max_shift = max(3, int(orig * 0.15))  # Cap movement at 15% of rank
        clamped = max(1, min(orig + max_shift, max(1, blended_rank)))
        clamped = min(clamped, orig - max_shift) if blended_rank < orig else clamped

        p["source_ranks"] = source_ranks
        p["consensus_rank"] = clamped

    # Re-sort and re-rank after blending
    nflmdb_prospects.sort(key=lambda x: x["consensus_rank"])
    for i, p in enumerate(nflmdb_prospects, start=1):
        p["consensus_rank"] = i

    return nflmdb_prospects


def build_board_json(prospects, year, alt_sources=None):
    """Convert scraped prospects into consensus_board format.

    alt_sources: optional dict {source_name: {player_name_lower: rank}}
    for multi-source blending.
    """
    # Optionally blend with alternate sources
    if alt_sources:
        prospects = compute_weighted_consensus(prospects, alt_sources)

    formatted = []
    for p in prospects:
        entry = {
            "consensus_rank": p["consensus_rank"],
            "name": p["name"],
            "position": p["position"],
            "school": p["school"],
            "grade": max(60.0, 100.0 - (p["consensus_rank"] - 1) * 0.5),
            "tier": p.get("tier", 4),
            "measurables": {
                "height": None, "weight": None,
                "forty": None, "ten_split": None,
                "vertical": None, "broad_jump": None,
                "three_cone": None, "short_shuttle": None,
                "arm_length": None, "hand_size": None,
            },
            "cfb_stats": {},
            "eligibility": {"status": "declared", "notes": "", "verified_date": ""},
            "injury_history": {"flag": False, "risk_level": "low", "details": [], "availability_pct": None},
            "recruiting": {},
            "board_velocity": {
                "weekly_change": p.get("movement", 0),
                "peak_rank": p.get("peak_rank"),
                "stability": (
                    "high" if abs(p.get("movement", 0)) <= 2
                    else ("unstable" if abs(p.get("movement", 0)) >= 8 else "moderate")
                ),
            },
            "source_ranks": p.get("source_ranks", {"nflmockdraftdb": p["consensus_rank"]}),
        }
        if p.get("peak_rank"):
            entry["peak_rank"] = p["peak_rank"]
        if p.get("movement") and p["movement"] != 0:
            entry["movement"] = p["movement"]
        if p.get("projected_pick"):
            entry["projected_pick"] = p["projected_pick"]
        if p.get("projected_team"):
            entry["projected_team"] = p["projected_team"]
        formatted.append(entry)

    source_list = ["NFL Mock Draft Database (consensus aggregation)"]
    if alt_sources:
        source_list += [s.replace("_", " ").title() for s in alt_sources.keys()]

    board = {
        "_description": f"{year} NFL Draft consensus big board. Multi-source weighted consensus.",
        "_source": "https://www.nflmockdraftdatabase.com/big-boards/{}/consensus-big-board-{}".format(year, year),
        "draft_year": year,
        "last_updated": time.strftime("%Y-%m-%d"),
        "sources": source_list,
        "prospects": formatted,
        "team_needs": {},
    }
    return board


def scrape_year(year, multi_source=True):
    """Scrape consensus board for a given year and save to JSON.

    When multi_source=True (default), also attempts to scrape ESPN and
    Tankathon rankings and blends them with NFLMockDraftDB using source weights.
    """
    print(f"\n{'='*60}")
    print(f"Scraping {year} Consensus Big Board")
    print(f"{'='*60}")

    html = fetch_page(year)
    if not html:
        print(f"  FAILED: Could not fetch page for {year}")
        return None

    prospects = parse_board(html, year)
    if not prospects:
        print(f"  FAILED: No prospects parsed for {year}")
        return None

    # Gather alternate source rankings for blending
    alt_sources = {}
    if multi_source:
        print("  Gathering alternate source rankings...")
        time.sleep(2)
        espn_ranks = scrape_espn_rankings(year)
        if espn_ranks:
            alt_sources["espn"] = espn_ranks
        time.sleep(2)
        tankathon_ranks = scrape_tankathon_rankings(year)
        if tankathon_ranks:
            alt_sources["tankathon"] = tankathon_ranks
        if alt_sources:
            print(f"  Blending with {len(alt_sources)} additional source(s): {list(alt_sources.keys())}")
        else:
            print("  No alternate sources available — using NFLMockDraftDB only")

    board = build_board_json(prospects, year, alt_sources=alt_sources or None)

    # Save
    output_path = os.path.join(DATA_DIR, f"consensus_board_{year}.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(board, f, indent=2)
    print(f"  Saved {len(prospects)} prospects to {output_path}")
    return board


def update_historical_ranks():
    """Update historical_drafts.json with consensus ranks from scraped boards."""
    hist_path = os.path.join(DATA_DIR, "historical_drafts.json")
    with open(hist_path, "r", encoding="utf-8") as f:
        hist_data = json.load(f)

    updated_years = 0
    for year_str, draft in hist_data.get("drafts", {}).items():
        board_path = os.path.join(DATA_DIR, f"consensus_board_{year_str}.json")
        if not os.path.exists(board_path):
            continue

        with open(board_path, "r", encoding="utf-8") as f:
            board = json.load(f)

        # Build name lookup from board
        board_lookup = {}
        for p in board.get("prospects", []):
            name_lower = p["name"].lower().strip()
            board_lookup[name_lower] = p["consensus_rank"]
            # Also try without suffix (Jr., III, etc.)
            clean = re.sub(r'\s+(jr\.?|sr\.?|ii+|iv|v)$', '', name_lower, flags=re.IGNORECASE)
            if clean != name_lower:
                board_lookup[clean] = p["consensus_rank"]

        # Match picks to board ranks
        matched = 0
        for pick in draft.get("picks", []):
            player_lower = pick["player"].lower().strip()
            rank = board_lookup.get(player_lower)
            if rank is None:
                # Try partial match
                clean = re.sub(r'\s+(jr\.?|sr\.?|ii+|iv|v)$', '', player_lower, flags=re.IGNORECASE)
                rank = board_lookup.get(clean)
            if rank is None:
                # Try fuzzy: first-last match
                for board_name, board_rank in board_lookup.items():
                    if player_lower in board_name or board_name in player_lower:
                        rank = board_rank
                        break
            if rank is not None:
                pick["consensus_rank"] = rank
                matched += 1

        total_picks = len(draft.get("picks", []))
        print(f"  {year_str}: matched {matched}/{total_picks} picks to board ranks")
        if matched > 0:
            updated_years += 1

    with open(hist_path, "w", encoding="utf-8") as f:
        json.dump(hist_data, f, indent=2)
    print(f"\nUpdated {updated_years} years in {hist_path}")


def main():
    args = sys.argv[1:]

    if not args:
        print("Usage:")
        print("  python pro/scrape_consensus_board.py 2024       # Scrape one year")
        print("  python pro/scrape_consensus_board.py --all       # Scrape 2016-2026")
        print("  python pro/scrape_consensus_board.py --update-ranks  # Update historical_drafts.json")
        sys.exit(1)

    if "--all" in args:
        for year in range(2016, 2027):
            scrape_year(year)
            print(f"  Waiting {CRAWL_DELAY}s (respecting crawl-delay)...")
            time.sleep(CRAWL_DELAY)

    elif "--update-ranks" in args:
        update_historical_ranks()

    else:
        for arg in args:
            try:
                year = int(arg)
                scrape_year(year)
                time.sleep(CRAWL_DELAY)
            except ValueError:
                print(f"Unknown argument: {arg}")


if __name__ == "__main__":
    main()
