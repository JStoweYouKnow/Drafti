"""Rebuild player status cache from transaction wire.

Usage:
    python pro/ingest/reconcile_events.py --year 2026
"""
from __future__ import annotations

import argparse

from run_ingest import run_ingestion


def main():
    parser = argparse.ArgumentParser(description="Reconcile transaction wire and rebuild status cache.")
    parser.add_argument("--year", type=int, required=True, help="Draft year")
    args = parser.parse_args()
    # Dry-run False writes wire + status cache; source=all ensures metadata refresh.
    result = run_ingestion(year=args.year, source_group="all", dry_run=False)
    print("Reconciled:", result)


if __name__ == "__main__":
    main()

