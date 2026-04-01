# Drafti Pro Ingestion

This folder contains the periodic ingestion pipeline for eligibility/status events used by Drafti Pro.

## What it does

- Pulls public data from source adapters (`nfl`, `team`, `media`)
- Includes official NFL tracker pages:
  - combine participants
  - draft prospects tracker
- Uses a strict domain allowlist for both source URLs and article URLs
- Uses a generated 32-team source matrix (ESPN team blogs + CBS team pages)
- Extracts draft-relevant events:
  - `declared`
  - `withdrew` / return-to-school
  - `medical_retirement`
  - `transferred`
- Merges/deduplicates events into:
  - `pro/data/transaction_wire_<year>.json`
  - `pro/data/player_status_cache_<year>.json`

## Run manually

```bash
python pro/ingest/run_ingest.py --year 2026
python pro/ingest/run_ingest.py --year 2026 --source nfl
python pro/ingest/run_ingest.py --year 2026 --source team
python pro/ingest/run_ingest.py --year 2026 --source media
python pro/ingest/run_ingest.py --year 2026 --dry-run
```

Reconcile/rebuild cache:

```bash
python pro/ingest/reconcile_events.py --year 2026
```

Merge ESPN mock draft picks into the consensus board:

```bash
python pro/ingest/merge_espn_mock.py --year 2026
python pro/ingest/merge_espn_mock.py --year 2026 --url "https://www.espn.com/nfl/draft2026/story/_/id/48299038/2026-nfl-mock-draft-seven-rounds-257-picks-projections-matt-miller"
python pro/ingest/merge_espn_mock.py --year 2026 --dry-run
```

## Suggested cron schedule

```cron
0 */6 * * *  cd /Users/v/Downloads/Drafti && /Users/v/Downloads/Drafti/.venv/bin/python pro/ingest/run_ingest.py --year 2026 --source nfl
30 */12 * * * cd /Users/v/Downloads/Drafti && /Users/v/Downloads/Drafti/.venv/bin/python pro/ingest/run_ingest.py --year 2026 --source team
15 */6 * * * cd /Users/v/Downloads/Drafti && /Users/v/Downloads/Drafti/.venv/bin/python pro/ingest/run_ingest.py --year 2026 --source media
0 2 * * *    cd /Users/v/Downloads/Drafti && /Users/v/Downloads/Drafti/.venv/bin/python pro/ingest/reconcile_events.py --year 2026
```

## Notes

- This is intentionally conservative; manual review is still recommended for final eligibility decisions.
- Respect each source's terms of service and robots policies before expanding source adapters.
- Beat reporter feeds/pages are hardcoded in `run_ingest.py` (ESPN blog pages + CBS team pages).
- NFL tracker pages are JS-heavy. The parser uses best-effort text extraction and treats listed players as `declared` unless a stronger status signal is detected.
- For tracker pages, ingestion now attempts Playwright-rendered fallback when static HTML parsing returns no rows.
- To enable rendered fallback locally:
  - `pip install playwright`
  - `playwright install chromium`
- `_ingest` metadata now includes:
  - `render_fallback_attempted`
  - `render_fallback_succeeded`
  - `render_fallback_sources` (per-source diagnostic details)
- HTML source links are filtered to likely article URLs (`/story/`, `/blog/.../post/`, `/news/`) to reduce navigation noise.
- If you add new sources, update both:
  - `SOURCE_CATALOG`
  - `ALLOWED_SOURCE_HOSTS` / per-source `allowed_item_hosts`

