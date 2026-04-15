"""Build historical_drafts.json from nflverse real NFL draft data.

Downloads the nflverse draft_picks dataset and converts it to the format
expected by draft_engine_pro.py. Run this script to refresh the data.

Usage:
    python pro/build_historical_data.py
"""
import csv
import io
import json
import math
import os
import ssl
import urllib.request

import certifi

DATA_DIR = os.environ.get("DRAFTI_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
OUTPUT_PATH = os.path.join(DATA_DIR, "historical_drafts.json")

NFLVERSE_DRAFT_CSV = (
    "https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.csv"
)

SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# NFL position mapping from nflverse categories to our positions
POSITION_MAP = {
    "QB": "QB",
    "RB": "RB", "FB": "RB", "HB": "RB",
    "WR": "WR",
    "TE": "TE",
    "T": "OT", "OT": "OT", "OL": "OT",
    "G": "IOL", "OG": "IOL", "C": "IOL",
    "DE": "EDGE", "OLB": "EDGE", "EDGE": "EDGE",
    "DT": "IDL", "NT": "IDL", "DL": "IDL",
    "ILB": "LB", "LB": "LB", "MLB": "LB",
    "CB": "CB",
    "S": "S", "FS": "S", "SS": "S", "DB": "S",
    "K": "K", "PK": "K",
    "P": "P", "LS": "P",
}

# Years to include
START_YEAR = 2015
END_YEAR = 2024


def download_csv():
    """Download the nflverse draft picks CSV."""
    print("Downloading nflverse draft_picks.csv...")
    req = urllib.request.Request(NFLVERSE_DRAFT_CSV, headers={"User-Agent": "Drafti/1.0"})
    with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
        raw = resp.read().decode("utf-8")
    print(f"  Downloaded {len(raw):,} bytes")
    return raw


def classify_status(row, seasons_since_draft):
    """Classify a player's career status based on real stats."""
    car_av = safe_int(row.get("w_av", 0))  # weighted approximate value
    pro_bowls = safe_int(row.get("probowls", 0))
    all_pros = safe_int(row.get("allpro", 0))
    seasons_started = safe_int(row.get("seasons_started", 0))
    games = safe_int(row.get("games", 0))
    pick = safe_int(row.get("pick", 999))

    if seasons_since_draft <= 1:
        if car_av >= 14 or pro_bowls >= 1:
            return "star"
        if car_av >= 6:
            return "starter"
        return "developing"

    # Expected AV benchmarks by years in league
    expected_av_per_year = max(2, 8 - (pick / 40))
    expected_total = expected_av_per_year * min(seasons_since_draft, 5)

    if all_pros >= 2 or (pro_bowls >= 3 and car_av >= expected_total * 1.3):
        return "star"
    if pro_bowls >= 1 or car_av >= expected_total * 1.0:
        return "star" if car_av >= expected_total * 1.5 else "starter"
    if games <= 16 and seasons_since_draft >= 3:
        return "bust"
    if car_av < expected_total * 0.4 and seasons_since_draft >= 3:
        return "bust"
    if car_av < expected_total * 0.6:
        return "developing"
    return "starter"


def safe_int(val):
    try:
        return int(float(val)) if val and str(val).strip() not in ("", "NA", "nan") else 0
    except (ValueError, TypeError):
        return 0


def safe_float(val):
    try:
        return float(val) if val and str(val).strip() not in ("", "NA", "nan") else 0.0
    except (ValueError, TypeError):
        return 0.0


def map_position(raw_pos):
    return POSITION_MAP.get(raw_pos.upper().strip(), raw_pos.upper().strip()) if raw_pos else "?"


def build_historical_data():
    raw_csv = download_csv()
    reader = csv.DictReader(io.StringIO(raw_csv))

    # Group by season
    by_year = {}
    for row in reader:
        season = safe_int(row.get("season", 0))
        if season < START_YEAR or season > END_YEAR:
            continue
        rnd = safe_int(row.get("round", 0))
        if rnd < 1 or rnd > 7:
            continue
        if season not in by_year:
            by_year[season] = []
        by_year[season].append(row)

    drafts = {}
    for year in sorted(by_year.keys()):
        rows = by_year[year]
        seasons_since = END_YEAR - year + 1  # rough count

        picks = []
        for row in rows:
            pick_num = safe_int(row.get("pick", 0))
            rnd = safe_int(row.get("round", 0))
            team = str(row.get("team", "")).strip().upper()
            player = str(row.get("pfr_player_name", "")).strip()
            raw_pos = str(row.get("position", "")).strip()
            position = map_position(raw_pos)
            school = str(row.get("college", "")).strip()
            car_av = safe_int(row.get("w_av", 0))  # weighted approximate value
            pro_bowls = safe_int(row.get("probowls", 0))
            all_pros = safe_int(row.get("allpro", 0))
            seasons_started = safe_int(row.get("seasons_started", 0))
            games = safe_int(row.get("games", 0))

            if not player or not pick_num:
                continue

            status = classify_status(row, seasons_since)

            pick_entry = {
                "overall": pick_num,
                "round": rnd,
                "team": team,
                "player": player,
                "position": position,
                "school": school,
                "consensus_rank": None,  # Will add separately
                "career_av": car_av,
                "pro_bowls": pro_bowls,
                "all_pros": all_pros,
                "status": status,
                "seasons_played": min(seasons_since, safe_int(row.get("to", year)) - year + 1) if safe_int(row.get("to", 0)) > 0 else seasons_since,
                "games": games,
            }
            picks.append(pick_entry)

        picks.sort(key=lambda p: p["overall"])
        drafts[str(year)] = {
            "picks": picks,
            "trades": [],
        }
        print(f"  {year}: {len(picks)} picks processed")

    # Add notable trades (manual — these are well-known)
    _add_notable_trades(drafts)

    # Add approximate consensus ranks for first-round picks
    _add_consensus_ranks(drafts)

    output = {
        "_description": "Historical NFL draft data from nflverse. career_av = Pro Football Reference Career Approximate Value. Auto-generated by build_historical_data.py.",
        "_source": "https://github.com/nflverse/nflverse-data/releases/tag/draft_picks",
        "_generated": True,
        "drafts": drafts,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nWrote {OUTPUT_PATH}")
    total_picks = sum(len(d["picks"]) for d in drafts.values())
    print(f"Total: {len(drafts)} years, {total_picks} picks")


def _add_notable_trades(drafts):
    """Add well-known draft day trades."""
    notable_trades = {
        "2015": [
            {"description": "TB stays at #1 for Jameis Winston", "from_pick": None, "to_pick": 1, "picks_sent": [], "picks_received": [1]},
        ],
        "2016": [
            {"description": "LAR trade up to #1 from #15 for Goff", "from_pick": 15, "to_pick": 1, "picks_sent": [15, 43, 45, 76, "2017 1st", "2017 3rd"], "picks_received": [1]},
            {"description": "PHI trade up to #2 from #8 for Wentz", "from_pick": 8, "to_pick": 2, "picks_sent": [8, 77, "2017 1st", "2018 2nd"], "picks_received": [2]},
        ],
        "2017": [
            {"description": "CHI trade up to #2 from #3 for Trubisky", "from_pick": 3, "to_pick": 2, "picks_sent": [3, 67, 111, "2018 3rd"], "picks_received": [2]},
        ],
        "2018": [
            {"description": "NYJ trade up to #3 from #6 for Darnold", "from_pick": 6, "to_pick": 3, "picks_sent": [6, 37, 49, "2019 2nd"], "picks_received": [3]},
            {"description": "BUF trade up to #7 from #12 for Josh Allen", "from_pick": 12, "to_pick": 7, "picks_sent": [12, 53, "2019 1st"], "picks_received": [7]},
        ],
        "2019": [],
        "2020": [],
        "2021": [
            {"description": "SF trade up to #3 from #12 for Lance", "from_pick": 12, "to_pick": 3, "picks_sent": [12, "2022 1st", "2022 3rd", "2023 1st"], "picks_received": [3]},
        ],
        "2022": [],
        "2023": [
            {"description": "CAR trade up to #1 from #9 for Bryce Young", "from_pick": 9, "to_pick": 1, "picks_sent": [9, 61, "2024 1st", "2024 2nd"], "picks_received": [1]},
        ],
        "2024": [],
    }
    for year, trades in notable_trades.items():
        if year in drafts:
            drafts[year]["trades"] = trades


def _add_consensus_ranks(drafts):
    """Add approximate consensus big board rankings for first-round picks.

    These are approximations based on major outlet consensus boards at the time.
    For a production system, you'd scrape NFL Mock Draft Database or similar.
    """
    # consensus_rank approximations for notable first-round picks
    # Format: {year: {player_name_lower: consensus_rank}}
    consensus = {
        "2015": {
            "jameis winston": 1, "marcus mariota": 2, "dante fowler": 3,
            "amari cooper": 4, "leonard williams": 5, "kevin white": 6,
            "vic beasley": 7, "brandon scherff": 8, "danny shelton": 9,
            "todd gurley": 10, "devante parker": 11, "andrus peat": 12,
            "melvin gordon": 13, "trae waynes": 14, "brandon trae waynes": 14,
        },
        "2016": {
            "jared goff": 1, "carson wentz": 2, "joey bosa": 3,
            "jalen ramsey": 4, "ezekiel elliott": 5, "deforest buckner": 6,
            "myles jack": 7, "ronnie stanley": 8, "laremy tunsil": 9,
            "vernon hargreaves": 10, "eli apple": 15, "corey coleman": 12,
            "sheldon rankins": 14, "karl joseph": 18, "ryan kelly": 16,
        },
        "2017": {
            "myles garrett": 1, "solomon thomas": 5, "mitchell trubisky": 3,
            "leonard fournette": 4, "corey davis": 6, "jamal adams": 2,
            "mike williams": 7, "christian mccaffrey": 8, "john ross": 10,
            "patrick mahomes": 9, "marshon lattimore": 11, "deshaun watson": 12,
        },
        "2018": {
            "baker mayfield": 1, "saquon barkley": 2, "sam darnold": 3,
            "denzel ward": 4, "bradley chubb": 5, "quenton nelson": 6,
            "josh allen": 7, "roquan smith": 8, "mike mcglinchey": 12,
            "josh rosen": 9, "minkah fitzpatrick": 10, "lamar jackson": 32,
            "vita vea": 11, "da'ron payne": 13,
        },
        "2019": {
            "kyler murray": 1, "nick bosa": 2, "quinnen williams": 3,
            "clelin ferrell": 6, "devin white": 4, "daniel jones": 17,
            "josh jacobs": 20, "tj hockenson": 7, "ed oliver": 5,
            "devin bush": 8, "dwayne haskins": 14, "brian burns": 9,
            "jonah williams": 10, "josh allen": 11, "deandre baker": 24,
        },
        "2020": {
            "joe burrow": 1, "chase young": 2, "jeff okudah": 3,
            "andrew thomas": 6, "tua tagovailoa": 5, "justin herbert": 7,
            "derrick brown": 4, "isaiah simmons": 8, "cj henderson": 9,
            "jedrick wills": 10, "mekhi becton": 11, "henry ruggs iii": 12,
            "jerry jeudy": 13, "ceedee lamb": 14, "ceedee lamb": 14,
            "tristan wirfs": 15, "jordan love": 26, "justin jefferson": 22,
            "patrick queen": 28,
        },
        "2021": {
            "trevor lawrence": 1, "zach wilson": 2, "trey lance": 3,
            "kyle pitts": 4, "ja'marr chase": 5, "jaylen waddle": 6,
            "penei sewell": 7, "devonta smith": 8, "patrick surtain ii": 9,
            "rashawn slater": 10, "micah parsons": 11, "jaycee horn": 12,
            "mac jones": 15, "alijah vera-tucker": 14, "najee harris": 24,
        },
        "2022": {
            "travon walker": 3, "aidan hutchinson": 1, "derek stingley jr.": 5,
            "sauce gardner": 2, "kayvon thibodeaux": 4, "ikem ekwonu": 6,
            "evan neal": 7, "kenyon green": 15, "charles cross": 9,
            "garrett wilson": 8, "chris olave": 10, "drake london": 11,
            "jameson williams": 12, "jordan davis": 13, "treylon burks": 18,
        },
        "2023": {
            "bryce young": 1, "c.j. stroud": 2, "will anderson jr.": 3,
            "anthony richardson": 9, "devon witherspoon": 7, "jahmyr gibbs": 15,
            "tyree wilson": 10, "bijan robinson": 4, "darnell wright": 6,
            "jalen carter": 5, "peter skoronski": 8, "quentin johnston": 14,
            "will mcdonald iv": 20, "christian gonzalez": 11, "lukas van ness": 13,
            "emmanuel forbes": 25, "broderick jones": 16, "jack campbell": 22,
            "calijah kancey": 18, "jaxon smith-njigba": 12,
            "zay flowers": 19, "jordan addison": 17, "anton harrison": 21,
            "deonte banks": 23, "mazi smith": 30, "dalton kincaid": 24,
            "rashee rice": 44,
        },
        "2024": {
            "caleb williams": 1, "jayden daniels": 2, "drake maye": 3,
            "marvin harrison jr.": 4, "joe alt": 5, "malik nabers": 6,
            "jc latham": 8, "michael penix jr.": 12, "rome odunze": 9,
            "olu fashanu": 10, "j.j. mccarthy": 11, "bo nix": 15,
            "brock bowers": 7, "taliese fuaga": 16, "laiatu latu": 13,
            "byron murphy ii": 14,
        },
    }

    for year_str, draft_data in drafts.items():
        year_consensus = consensus.get(year_str, {})
        if not year_consensus:
            continue
        for pick in draft_data["picks"]:
            player_lower = pick["player"].lower().strip()
            rank = year_consensus.get(player_lower)
            if rank is not None:
                pick["consensus_rank"] = rank


if __name__ == "__main__":
    build_historical_data()
