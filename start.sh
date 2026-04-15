#!/bin/bash
set -e

# Persistent volume on Railway; falls back to bundled data for local dev
DATA_DIR="${DRAFTI_DATA_DIR:-/app/pro/data}"
mkdir -p "$DATA_DIR"

# Seed volume on first deploy — never overwrites already-refreshed data
if [ "$DATA_DIR" != "/app/pro/data" ]; then
    for f in /app/pro/data/*.json; do
        fname=$(basename "$f")
        if [ ! -f "$DATA_DIR/$fname" ]; then
            echo "[seed] $fname"
            cp "$f" "$DATA_DIR/$fname"
        fi
    done
fi

exec streamlit run pro/app_pro.py \
    --server.address 0.0.0.0 \
    --server.port "${PORT:-8080}" \
    --server.headless true
