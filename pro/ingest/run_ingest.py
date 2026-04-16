"""Periodic ingestion for eligibility and status signals.

Usage:
    python pro/ingest/run_ingest.py --year 2026
    python pro/ingest/run_ingest.py --year 2026 --source nfl
    python pro/ingest/run_ingest.py --year 2026 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import requests
from bs4 import BeautifulSoup


DATA_DIR = os.environ.get("DRAFTI_DATA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
WIRE_FILE_TEMPLATE = "transaction_wire_{year}.json"
STATUS_CACHE_TEMPLATE = "player_status_cache_{year}.json"
HEALTH_HISTORY_TEMPLATE = "ingest_health_history_{year}.json"
_PLAYWRIGHT_STATUS_CACHE: dict | None = None
HEALTH_HISTORY_MAX_RUNS = 20
HEALTH_DEGRADED_CONSEC_FAILS = 3


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _norm_name(name: str) -> str:
    return _norm_space(name).lower()


def _host_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower().strip()
    except ValueError:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _is_allowed_host(url: str, allowed_hosts: Iterable[str]) -> bool:
    host = _host_from_url(url)
    if not host:
        return False
    for allowed in allowed_hosts:
        allowed = allowed.lower().strip()
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


@dataclass
class SourceConfig:
    source_id: str
    tier: str
    kind: str  # rss | html | html_rendered | nfl_draft_tracker | nfl_combine_tracker
    url: str
    allowed_item_hosts: tuple[str, ...]


# NFL team source matrix for broad, deterministic coverage.
TEAM_SOURCE_MATRIX: tuple[tuple[str, str, str], ...] = (
    ("ari", "arizona-cardinals", "ARI/arizona-cardinals"),
    ("atl", "atlanta-falcons", "ATL/atlanta-falcons"),
    ("bal", "baltimore-ravens", "BAL/baltimore-ravens"),
    ("buf", "buffalo-bills", "BUF/buffalo-bills"),
    ("car", "carolina-panthers", "CAR/carolina-panthers"),
    ("chi", "chicago-bears", "CHI/chicago-bears"),
    ("cin", "cincinnati-bengals", "CIN/cincinnati-bengals"),
    ("cle", "cleveland-browns", "CLE/cleveland-browns"),
    ("dal", "dallas-cowboys", "DAL/dallas-cowboys"),
    ("den", "denver-broncos", "DEN/denver-broncos"),
    ("det", "detroit-lions", "DET/detroit-lions"),
    ("gb", "green-bay-packers", "GB/green-bay-packers"),
    ("hou", "houston-texans", "HOU/houston-texans"),
    ("ind", "indianapolis-colts", "IND/indianapolis-colts"),
    ("jac", "jacksonville-jaguars", "JAC/jacksonville-jaguars"),
    ("kc", "kansas-city-chiefs", "KC/kansas-city-chiefs"),
    ("lac", "los-angeles-chargers", "LAC/los-angeles-chargers"),
    ("lar", "los-angeles-rams", "LAR/los-angeles-rams"),
    ("lv", "las-vegas-raiders", "LV/las-vegas-raiders"),
    ("mia", "miami-dolphins", "MIA/miami-dolphins"),
    ("min", "minnesota-vikings", "MIN/minnesota-vikings"),
    ("ne", "new-england-patriots", "NE/new-england-patriots"),
    ("no", "new-orleans-saints", "NO/new-orleans-saints"),
    ("nyg", "new-york-giants", "NYG/new-york-giants"),
    ("nyj", "new-york-jets", "NYJ/new-york-jets"),
    ("phi", "philadelphia-eagles", "PHI/philadelphia-eagles"),
    ("pit", "pittsburgh-steelers", "PIT/pittsburgh-steelers"),
    ("sea", "seattle-seahawks", "SEA/seattle-seahawks"),
    ("sf", "san-francisco-49ers", "SF/san-francisco-49ers"),
    ("tb", "tampa-bay-buccaneers", "TB/tampa-bay-buccaneers"),
    ("ten", "tennessee-titans", "TEN/tennessee-titans"),
    ("was", "washington-commanders", "WAS/washington-commanders"),
)


# Strict allowlist for source and article hosts.
ALLOWED_SOURCE_HOSTS = {
    "nfl.com",
    "chiefs.com",
    "philadelphiaeagles.com",
    "espn.com",
    "cbssports.com",
}

def _build_team_source_catalog() -> list[SourceConfig]:
    rows: list[SourceConfig] = []
    for code, espn_slug, cbs_path in TEAM_SOURCE_MATRIX:
        rows.append(
            SourceConfig(
                f"team-{code}-espn",
                "media",
                "html",
                f"https://www.espn.com/blog/{espn_slug}",
                ("espn.com",),
            )
        )
        rows.append(
            SourceConfig(
                f"team-{code}-cbs",
                "media",
                "html",
                f"https://www.cbssports.com/nfl/teams/{cbs_path}/",
                ("cbssports.com",),
            )
        )
    return rows


# Start from predictable, public pages/feeds, then expand with all-team pages.
SOURCE_CATALOG = [
    SourceConfig("nfl-news", "official", "rss", "https://www.nfl.com/rss/rsslanding?searchString=News", ("nfl.com",)),
    SourceConfig("nfl-combine-pro-days", "official", "html", "https://www.nfl.com/combine/", ("nfl.com",)),
    SourceConfig("chiefs-news", "team", "rss", "https://www.chiefs.com/rss/news", ("chiefs.com", "nfl.com")),
    SourceConfig("eagles-news", "team", "rss", "https://www.philadelphiaeagles.com/rss/article", ("philadelphiaeagles.com", "nfl.com")),
    SourceConfig("espn-nfl-draft", "media", "html", "https://www.espn.com/nfl/draft/", ("espn.com",)),
    SourceConfig(
        "espn-mel-kiper-mocks",
        "media",
        "html",
        "https://www.espn.com/search/_/q/mel%20kiper%20nfl%20mock%20draft",
        ("espn.com",),
    ),
    SourceConfig(
        "espn-bill-barnwell-draft",
        "media",
        "html",
        "https://www.espn.com/search/_/q/bill%20barnwell%20nfl%20draft",
        ("espn.com",),
    ),
    SourceConfig("cbs-nfl-draft", "media", "html", "https://www.cbssports.com/nfl/draft/", ("cbssports.com",)),
    # Official NFL trackers (JS-heavy pages; parsed via dedicated extractor)
    SourceConfig(
        "nfl-draft-tracker-prospects",
        "official",
        "nfl_draft_tracker",
        "https://www.nfl.com/draft/tracker/prospects/all-positions/all-colleges/all-statuses/2026",
        ("nfl.com",),
    ),
    SourceConfig(
        "nfl-combine-tracker-participants",
        "official",
        "nfl_combine_tracker",
        "https://www.nfl.com/combine/tracker/participants/",
        ("nfl.com",),
    ),
] + _build_team_source_catalog()

SEED_SOURCE_FILE_TEMPLATE = "source_seeds_{year}.json"
KEY_SOURCE_MIN_ROWS = {
    "seed-espn-mel-kiper-search": 10,
    "seed-espn-bill-barnwell-search": 10,
    "seed-espn-draft-home": 20,
    "seed-nfl-mock-drafts": 20,
    "seed-nfl-draft-news": 20,
    "seed-nfl-combine-hub": 20,
}


STATUS_PATTERNS = [
    ("medical_retirement", re.compile(r"\b(retire(?:s|d)?|medical retirement)\b", re.I)),
    (
        "withdrew",
        re.compile(
            r"\b(withdraw(?:s|n)?|return(?:s|ed|ing)? to (?:school|college)|"
            r"staying in school|not declaring|not entering|won't enter|will return for)\b",
            re.I,
        ),
    ),
    ("transferred", re.compile(r"\b(transfer(?:s|red)?|enters? (?:the )?transfer portal|hits (?:the )?portal)\b", re.I)),
    (
        "declared",
        re.compile(
            r"\b(declare(?:s|d|ing)? for (?:the )?(?:nfl )?draft|enters? (?:the )?nfl draft|"
            r"forego(?:es|ing|ne)? (?:his|their) remaining eligibility|"
            r"pro day|pro-day)\b",
            re.I,
        ),
    ),
]


PLAYER_NAME_RE = re.compile(r"\b([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,3})\b")


def _confidence_for_tier(tier: str) -> float:
    return {"official": 0.98, "team": 0.94, "media": 0.85}.get(tier, 0.75)


def _extract_status(text: str) -> str | None:
    for status, pattern in STATUS_PATTERNS:
        if pattern.search(text):
            return status
    return None


def _extract_name(text: str) -> str | None:
    # Heuristic: use first title-cased multiword phrase, excluding generic words.
    blacklist = {"Nfl Draft", "Draft Tracker", "Team News", "Breaking News"}
    for match in PLAYER_NAME_RE.findall(text):
        name = _norm_space(match)
        if name.title() in blacklist:
            continue
        return name
    return None


def _is_probable_article_url(url: str, source_id: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    if not path:
        return False
    # Keep precision high by ignoring nav/index links on broad landing pages.
    if source_id.endswith("-espn") or source_id.startswith("espn-"):
        return ("/story/" in path) or ("/blog/" in path and "/post/" in path)
    if source_id.endswith("-cbs") or source_id.startswith("cbs-"):
        return "/news/" in path
    if source_id.startswith("nfl-"):
        return ("/news/" in path) or ("/draft/" in path) or ("/combine/" in path)
    return True


def _safe_get(url: str, timeout: int = 20) -> str | None:
    if not _is_allowed_host(url, ALLOWED_SOURCE_HOSTS):
        return None
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "DraftiPro-Ingest/1.0 (+https://github.com/JStoweYouKnow/Drafti)",
                "Accept": "text/html,application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        if resp.status_code != 200:
            return None
        return resp.text
    except requests.RequestException:
        return None


def _safe_get_rendered(url: str, timeout_ms: int = 35000) -> str | None:
    """Fetch fully rendered HTML using Playwright (for JS-heavy pages)."""
    if not _is_allowed_host(url, ALLOWED_SOURCE_HOSTS):
        return None
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1440, "height": 2200},
                locale="en-US",
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            # Let client-side trackers/tables render.
            page.wait_for_timeout(3500)
            html_text = page.content()
            browser.close()
            return html_text
    except Exception:
        return None


def _playwright_status() -> dict:
    """Return Playwright/browser readiness once per process."""
    global _PLAYWRIGHT_STATUS_CACHE
    if _PLAYWRIGHT_STATUS_CACHE is not None:
        return _PLAYWRIGHT_STATUS_CACHE
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception:
        _PLAYWRIGHT_STATUS_CACHE = {"ok": False, "reason": "playwright_package_missing"}
        return _PLAYWRIGHT_STATUS_CACHE
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        _PLAYWRIGHT_STATUS_CACHE = {"ok": True, "reason": "ok"}
        return _PLAYWRIGHT_STATUS_CACHE
    except Exception as exc:
        msg = str(exc).lower()
        if "executable doesn't exist" in msg or "please run the following command" in msg:
            reason = "playwright_browser_missing"
        else:
            reason = "playwright_launch_failed"
        _PLAYWRIGHT_STATUS_CACHE = {"ok": False, "reason": reason, "error": str(exc)[:220]}
        return _PLAYWRIGHT_STATUS_CACHE


def _safe_get_rendered_with_reason(url: str, timeout_ms: int = 35000) -> tuple[str | None, str | None]:
    """Rendered fetch with structured failure reason."""
    if not _is_allowed_host(url, ALLOWED_SOURCE_HOSTS):
        return None, "host_not_allowed"
    pw = _playwright_status()
    if not pw.get("ok"):
        return None, str(pw.get("reason", "playwright_unavailable"))
    html_text = _safe_get_rendered(url, timeout_ms=timeout_ms)
    if not html_text:
        return None, "render_fetch_failed"
    return html_text, None


def _load_seed_sources(year: int) -> list[SourceConfig]:
    """Load curated high-priority source URLs from data/source_seeds_{year}.json."""
    path = os.path.join(DATA_DIR, SEED_SOURCE_FILE_TEMPLATE.format(year=year))
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

    out: list[SourceConfig] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_id = _norm_space(str(row.get("source_id", "")))
        url = _norm_space(str(row.get("url", "")))
        if not source_id or not url or not _is_allowed_host(url, ALLOWED_SOURCE_HOSTS):
            continue
        tier = _norm_space(str(row.get("tier", "media"))).lower() or "media"
        kind = _norm_space(str(row.get("kind", "html_rendered"))).lower() or "html_rendered"
        allowed_hosts = row.get("allowed_item_hosts")
        if isinstance(allowed_hosts, list) and allowed_hosts:
            hosts = tuple(str(h).strip().lower() for h in allowed_hosts if str(h).strip())
        else:
            host = _host_from_url(url)
            hosts = (host,) if host else tuple()
        if not hosts:
            continue
        out.append(
            SourceConfig(
                source_id=source_id,
                tier=tier,
                kind=kind,
                url=url,
                allowed_item_hosts=hosts,
            )
        )
    return out


def _iter_rss_entries(xml_text: str) -> Iterable[dict]:
    try:
        root = ET.fromstring(xml_text.encode("utf-8"))
    except ET.ParseError:
        return []

    entries: list[dict] = []
    # RSS items
    for item in root.findall(".//item"):
        entries.append(
            {
                "title": _norm_space("".join(item.findtext("title", default=""))),
                "summary": _norm_space("".join(item.findtext("description", default=""))),
                "url": _norm_space("".join(item.findtext("link", default=""))),
                "published": _norm_space("".join(item.findtext("pubDate", default=""))),
            }
        )
    # Atom entries
    atom_entries = root.findall(".//{*}entry")
    for entry in atom_entries:
        link_el = entry.find("{*}link")
        href = ""
        if link_el is not None:
            href = link_el.attrib.get("href", "")
        entries.append(
            {
                "title": _norm_space("".join(entry.findtext("{*}title", default=""))),
                "summary": _norm_space("".join(entry.findtext("{*}summary", default=""))),
                "url": _norm_space(href),
                "published": _norm_space("".join(entry.findtext("{*}updated", default=""))),
            }
        )
    return entries


def _iter_html_entries(html_text: str, source_url: str) -> Iterable[dict]:
    soup = BeautifulSoup(html_text, "html.parser")
    entries = []
    for a in soup.select("a[href]"):
        title = _norm_space(a.get_text(" ", strip=True))
        href = _norm_space(a.get("href", ""))
        if not title or len(title) < 18:
            continue
        if href.startswith("/"):
            base = re.match(r"^https?://[^/]+", source_url)
            if base:
                href = base.group(0) + href
        entries.append({"title": title, "summary": "", "url": href, "published": ""})
    return entries[:200]


def _iter_nfl_tracker_entries(html_text: str, page_kind: str) -> Iterable[dict]:
    """Best-effort parser for NFL tracker pages (draft prospects / combine participants)."""
    soup = BeautifulSoup(html_text, "html.parser")
    text = soup.get_text("\n")
    text = _norm_space(text.replace("\xa0", " "))
    out: list[dict] = []
    seen: set[str] = set()

    # Pattern 0: parse JSON-ish data blocks commonly embedded in rendered NFL pages.
    json_like_pat = re.compile(
        r'"(?:fullName|displayName|name|playerName)"\s*:\s*"([^"]{3,80})".{0,240}?'
        r'"(?:position|pos)"\s*:\s*"([A-Z]{1,5})".{0,240}?'
        r'"(?:college|school|collegeName)"\s*:\s*"([^"]{2,80})"',
        re.I | re.S,
    )
    for m in json_like_pat.finditer(html_text):
        name = _norm_space(m.group(1))
        pos = _norm_space(m.group(2).upper())
        school = _norm_space(m.group(3))
        if not PLAYER_NAME_RE.fullmatch(name):
            continue
        key = _norm_name(name)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": name,
                "summary": f"Listed on NFL {'Draft Tracker' if page_kind == 'draft' else 'Combine Participants'} ({pos}, {school})",
                "url": "",
                "published": "",
            }
        )

    # Pattern 0b: row-style DOM fragments rendered without clear separators.
    for node in soup.select("[data-testid*='row'], [class*='row'], article, li"):
        label = _norm_space(node.get_text(" ", strip=True))
        if len(label) < 16 or len(label) > 180:
            continue
        m = re.search(
            r"\b([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,3})\b"
            r"\s+([A-Z]{1,5})\s+([A-Za-z0-9&().'\- ]{2,60})",
            label,
        )
        if not m:
            continue
        name = _norm_space(m.group(1))
        pos = _norm_space(m.group(2))
        school = _norm_space(m.group(3))
        key = _norm_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": name,
                "summary": f"Listed on NFL {'Draft Tracker' if page_kind == 'draft' else 'Combine Participants'} ({pos}, {school})",
                "url": "",
                "published": "",
            }
        )

    # Pattern 1: "Player Name, POS, School" (works when rows are flattened)
    row_pat = re.compile(
        r"\b([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,3})\b"
        r"\s*,\s*([A-Z]{1,5})\s*,\s*([A-Za-z0-9&().'\- ]{2,60})"
    )
    for m in row_pat.finditer(text):
        name = _norm_space(m.group(1))
        pos = _norm_space(m.group(2))
        school = _norm_space(m.group(3))
        key = _norm_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": name,
                "summary": f"Listed on NFL {'Draft Tracker' if page_kind == 'draft' else 'Combine Participants'} ({pos}, {school})",
                "url": "",
                "published": "",
            }
        )

    # Pattern 2: pick-number rows often shown as "N. Team Player, POS, School"
    pick_pat = re.compile(
        r"\b\d{1,3}\.\s+[A-Za-z .()'&-]{2,40}\s+"
        r"([A-Z][a-z]+(?:[-'][A-Z][a-z]+)?(?:\s+[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?){1,3})\s*,\s*"
        r"([A-Z]{1,5})\s*,\s*([A-Za-z0-9&().'\- ]{2,60})"
    )
    for m in pick_pat.finditer(text):
        name = _norm_space(m.group(1))
        pos = _norm_space(m.group(2))
        school = _norm_space(m.group(3))
        key = _norm_name(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "title": name,
                "summary": f"Listed on NFL {'Draft Tracker' if page_kind == 'draft' else 'Combine Participants'} ({pos}, {school})",
                "url": "",
                "published": "",
            }
        )

    return out[:600]


def _load_wire(year: int) -> dict:
    path = os.path.join(DATA_DIR, WIRE_FILE_TEMPLATE.format(year=year))
    if not os.path.exists(path):
        return {
            "_description": f"{year} NFL Draft transaction wire.",
            "draft_year": year,
            "last_updated": _utc_now().split(" ")[0],
            "entries": [],
        }
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_wire(year: int, payload: dict):
    path = os.path.join(DATA_DIR, WIRE_FILE_TEMPLATE.format(year=year))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _save_status_cache(year: int, entries: list[dict]):
    status_by_player: dict[str, dict] = {}
    for e in entries:
        key = _norm_name(e.get("name", ""))
        if not key:
            continue
        prev = status_by_player.get(key)
        if prev is None or float(e.get("confidence", 0)) >= float(prev.get("confidence", 0)):
            status_by_player[key] = {
                "name": e.get("name", ""),
                "status": e.get("status", "undeclared"),
                "date": e.get("date", ""),
                "confidence": e.get("confidence", 0),
                "source": e.get("source", ""),
                "source_url": e.get("source_url", ""),
                "notes": e.get("notes", ""),
            }

    payload = {
        "draft_year": year,
        "generated_at": _utc_now(),
        "players": sorted(status_by_player.values(), key=lambda x: x["name"]),
    }
    path = os.path.join(DATA_DIR, STATUS_CACHE_TEMPLATE.format(year=year))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _load_health_history(year: int) -> dict:
    path = os.path.join(DATA_DIR, HEALTH_HISTORY_TEMPLATE.format(year=year))
    if not os.path.exists(path):
        return {"draft_year": year, "runs": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if not isinstance(payload, dict):
            return {"draft_year": year, "runs": []}
        runs = payload.get("runs")
        if not isinstance(runs, list):
            payload["runs"] = []
        return payload
    except (OSError, json.JSONDecodeError):
        return {"draft_year": year, "runs": []}


def _save_health_history(year: int, payload: dict) -> None:
    path = os.path.join(DATA_DIR, HEALTH_HISTORY_TEMPLATE.format(year=year))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _is_source_success(stat: dict) -> bool:
    if stat.get("note") or stat.get("render_error"):
        return False
    rows_found = int(stat.get("rows_found", 0) or 0)
    events_added = int(stat.get("events_added", 0) or 0)
    return rows_found > 0 or events_added > 0


def _compute_health_rollup(history_payload: dict, source_stats: list[dict]) -> dict:
    """Build per-source success rates and degraded flags from rolling history."""
    runs = history_payload.get("runs", [])
    if not isinstance(runs, list):
        runs = []
    run_success_maps: list[dict] = []
    for run in runs:
        if not isinstance(run, dict):
            continue
        success_map = run.get("success_by_source", {})
        if isinstance(success_map, dict):
            run_success_maps.append(success_map)

    rollup = {}
    for stat in source_stats:
        source = str(stat.get("source", "")).strip()
        if not source:
            continue
        hist_bits: list[bool] = []
        for m in run_success_maps:
            val = m.get(source)
            if isinstance(val, bool):
                hist_bits.append(val)
        current_ok = _is_source_success(stat)
        all_bits = hist_bits + [current_ok]
        total = len(all_bits)
        success_count = sum(1 for x in all_bits if x)
        success_rate = round((success_count / total) if total else 0.0, 3)

        consecutive_failures = 0
        for bit in reversed(all_bits):
            if bit:
                break
            consecutive_failures += 1
        degraded = consecutive_failures >= HEALTH_DEGRADED_CONSEC_FAILS
        rollup[source] = {
            "success_rate": success_rate,
            "sample_size": total,
            "consecutive_failures": consecutive_failures,
            "degraded": degraded,
        }
    return rollup


def run_ingestion(year: int, source_group: str = "all", dry_run: bool = False) -> dict:
    dynamic_catalog = SOURCE_CATALOG + _load_seed_sources(year)
    selected = []
    for src in dynamic_catalog:
        if source_group == "all":
            selected.append(src)
        elif source_group == "nfl" and src.source_id.startswith("nfl"):
            selected.append(src)
        elif source_group == "team" and src.tier == "team":
            selected.append(src)
        elif source_group == "media" and src.tier == "media":
            selected.append(src)

    discovered: list[dict] = []
    render_diag = {
        "render_fallback_attempted": 0,
        "render_fallback_succeeded": 0,
        "render_fallback_sources": [],
    }
    source_stats: list[dict] = []
    pw_status = _playwright_status()
    for src in selected:
        if not _is_allowed_host(src.url, ALLOWED_SOURCE_HOSTS):
            continue
        body = _safe_get(src.url)
        used_rendered = False
        render_error = None
        if src.kind == "html_rendered" and not body:
            render_diag["render_fallback_attempted"] += 1
            body, render_error = _safe_get_rendered_with_reason(src.url)
            used_rendered = bool(body)
            if body:
                render_diag["render_fallback_succeeded"] += 1
        if src.kind == "html_rendered" and body and not used_rendered:
            rendered_body, render_error = _safe_get_rendered_with_reason(src.url)
            if rendered_body:
                body = rendered_body
                used_rendered = True
                render_diag["render_fallback_attempted"] += 1
                render_diag["render_fallback_succeeded"] += 1
        if not body:
            source_stats.append(
                {
                    "source": src.source_id,
                    "kind": src.kind,
                    "rows_found": 0,
                    "events_added": 0,
                    "note": render_error or "fetch_failed",
                }
            )
            continue
        if src.kind == "rss":
            rows = _iter_rss_entries(body)
        elif src.kind == "nfl_draft_tracker":
            rows = _iter_nfl_tracker_entries(body, "draft")
        elif src.kind == "nfl_combine_tracker":
            rows = _iter_nfl_tracker_entries(body, "combine")
        else:
            rows = _iter_html_entries(body, src.url)
        rows = list(rows)

        # Media pages are often JS-heavy. Fall back to rendered HTML if plain fetch found nothing.
        if src.kind in {"html", "html_rendered"} and not rows and src.tier == "media":
            render_diag["render_fallback_attempted"] += 1
            rendered, render_error = _safe_get_rendered_with_reason(src.url)
            if rendered:
                rows = list(_iter_html_entries(rendered, src.url))
                if rows:
                    render_diag["render_fallback_succeeded"] += 1
                    used_rendered = True
                    render_diag["render_fallback_sources"].append({"source": src.source_id, "rows_found": len(rows)})

        # JS-heavy NFL tracker pages often render data client-side.
        # If static extraction yields no rows, try a rendered browser fetch.
        if src.kind in {"nfl_draft_tracker", "nfl_combine_tracker"} and not rows:
            render_diag["render_fallback_attempted"] += 1
            rendered, render_error = _safe_get_rendered_with_reason(src.url)
            if rendered:
                if src.kind == "nfl_draft_tracker":
                    rows = _iter_nfl_tracker_entries(rendered, "draft")
                else:
                    rows = _iter_nfl_tracker_entries(rendered, "combine")
                rows = list(rows)
                if rows:
                    render_diag["render_fallback_succeeded"] += 1
                    render_diag["render_fallback_sources"].append(
                        {
                            "source": src.source_id,
                            "rows_found": len(rows),
                        }
                    )
                else:
                    render_diag["render_fallback_sources"].append(
                        {
                            "source": src.source_id,
                            "rows_found": 0,
                            "note": "Rendered fetch returned no parseable rows.",
                        }
                    )
            else:
                render_diag["render_fallback_sources"].append(
                    {
                        "source": src.source_id,
                        "rows_found": 0,
                        "note": f"Rendered fetch unavailable ({render_error or 'unknown'}).",
                    }
                )
        events_before = len(discovered)
        for row in rows:
            source_url = row.get("url") or src.url
            if source_url and not _is_allowed_host(source_url, src.allowed_item_hosts):
                continue
            if source_url and not _is_probable_article_url(source_url, src.source_id):
                continue
            text = _norm_space((row.get("title", "") + " " + row.get("summary", "")))
            status = _extract_status(text)
            if not status and src.kind in {"nfl_draft_tracker", "nfl_combine_tracker"}:
                # Tracker listings are treated as declared/active unless explicit status says otherwise.
                status = "declared"
            if not status:
                continue
            name = _extract_name(row.get("title", "")) or _extract_name(text)
            if not name:
                continue
            discovered.append(
                {
                    "name": name,
                    "position": "",
                    "school": "",
                    "status": status,
                    "date": row.get("published") or _utc_now().split(" ")[0],
                    "notes": row.get("title", ""),
                    "source": src.source_id,
                    "source_url": source_url,
                    "confidence": _confidence_for_tier(src.tier),
                    "ingested_at": _utc_now(),
                }
            )
        source_stats.append(
            {
                "source": src.source_id,
                "kind": src.kind,
                "rows_found": len(rows),
                "events_added": len(discovered) - events_before,
                "rendered": bool(used_rendered),
                "render_error": render_error,
            }
        )

    health_history = _load_health_history(year)
    health_rollup = _compute_health_rollup(health_history, source_stats)
    for stat in source_stats:
        src = str(stat.get("source", "")).strip()
        extra = health_rollup.get(src)
        if isinstance(extra, dict):
            stat["health"] = extra

    # Merge with existing entries; preserve manual curation and dedupe on (name, status)
    wire = _load_wire(year)
    existing = wire.get("entries", [])
    merged: dict[tuple[str, str], dict] = {}
    for e in existing + discovered:
        key = (_norm_name(e.get("name", "")), str(e.get("status", "undeclared")))
        if not key[0]:
            continue
        current = merged.get(key)
        if current is None:
            merged[key] = e
            continue
        # Keep higher-confidence or richer note
        new_conf = float(e.get("confidence", 0) or 0)
        old_conf = float(current.get("confidence", 0) or 0)
        if new_conf > old_conf or (len(str(e.get("notes", ""))) > len(str(current.get("notes", "")))):
            merged[key] = e

    merged_entries = sorted(merged.values(), key=lambda x: (_norm_name(x.get("name", "")), x.get("status", "")))
    wire["draft_year"] = year
    wire["last_updated"] = _utc_now().split(" ")[0]
    wire["entries"] = merged_entries
    degraded_sources = sorted(
        [src for src, meta in health_rollup.items() if bool(meta.get("degraded"))]
    )
    success_map = {str(s.get("source", "")): _is_source_success(s) for s in source_stats if s.get("source")}
    wire["_ingest"] = {
        "generated_at": _utc_now(),
        "source_group": source_group,
        "num_sources_attempted": len(selected),
        "num_events_discovered": len(discovered),
        "num_events_total": len(merged_entries),
        "num_seed_sources_loaded": len(dynamic_catalog) - len(SOURCE_CATALOG),
        "num_degraded_sources": len(degraded_sources),
        "degraded_sources": degraded_sources,
        "playwright": pw_status,
        "source_stats": source_stats,
        **render_diag,
    }

    if not dry_run:
        hist_runs = health_history.get("runs", [])
        if not isinstance(hist_runs, list):
            hist_runs = []
        hist_runs.append(
            {
                "generated_at": wire["_ingest"]["generated_at"],
                "source_group": source_group,
                "success_by_source": success_map,
            }
        )
        hist_runs = hist_runs[-HEALTH_HISTORY_MAX_RUNS:]
        health_history["draft_year"] = year
        health_history["runs"] = hist_runs
        _save_health_history(year, health_history)
        _save_wire(year, wire)
        _save_status_cache(year, merged_entries)
    return wire["_ingest"]


def _print_health_report(result: dict) -> None:
    """Print quick scrape-health summary from ingestion diagnostics."""
    stats = list(result.get("source_stats", []))
    total = len(stats)
    zero_rows = [s for s in stats if int(s.get("rows_found", 0) or 0) == 0]
    zero_events = [s for s in stats if int(s.get("events_added", 0) or 0) == 0]
    failures = [s for s in stats if s.get("note") or s.get("render_error")]
    degraded = [
        s for s in stats
        if isinstance(s.get("health"), dict) and bool(s["health"].get("degraded"))
    ]
    threshold_misses = []
    for s in stats:
        src = str(s.get("source", ""))
        min_rows = KEY_SOURCE_MIN_ROWS.get(src)
        if min_rows is None:
            continue
        if int(s.get("rows_found", 0) or 0) < min_rows:
            threshold_misses.append(
                {"source": src, "rows_found": int(s.get("rows_found", 0) or 0), "min_rows": min_rows}
            )
    print("\nSCRAPE HEALTH")
    print(f"  Sources analyzed: {total}")
    print(f"  Zero-row sources: {len(zero_rows)}")
    print(f"  Zero-event sources: {len(zero_events)}")
    print(f"  Failures flagged: {len(failures)}")
    print(f"  Key source threshold misses: {len(threshold_misses)}")
    print(f"  Degraded sources: {len(degraded)}")
    pw = result.get("playwright", {})
    print(f"  Playwright: {pw.get('reason', 'unknown')}")
    if failures:
        print("\nTop failures:")
        for row in failures[:12]:
            reason = row.get("note") or row.get("render_error") or "unknown"
            print(f"  - {row.get('source')}: {reason}")
    if threshold_misses:
        print("\nKey source row-count alerts:")
        for row in threshold_misses:
            print(f"  - {row['source']}: rows={row['rows_found']} (min={row['min_rows']})")
    if degraded:
        print("\nDegraded source alerts:")
        for row in degraded[:12]:
            h = row.get("health", {})
            print(
                f"  - {row.get('source')}: consecutive_failures={h.get('consecutive_failures')} "
                f"success_rate={h.get('success_rate')}"
            )


def main():
    parser = argparse.ArgumentParser(description="Ingest eligibility events from NFL/team/media sources.")
    parser.add_argument("--year", type=int, required=True, help="Draft year (e.g. 2026)")
    parser.add_argument("--source", choices=["all", "nfl", "team", "media"], default="all")
    parser.add_argument("--dry-run", action="store_true", help="Do not write output files")
    parser.add_argument("--health", action="store_true", help="Print scrape health summary after ingestion")
    args = parser.parse_args()

    result = run_ingestion(year=args.year, source_group=args.source, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    if args.health:
        _print_health_report(result)


if __name__ == "__main__":
    main()

