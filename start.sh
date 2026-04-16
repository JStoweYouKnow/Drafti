#!/bin/bash
echo "[start] PORT=${PORT}"
streamlit run pro/app_pro.py \
    --server.address 0.0.0.0 \
    --server.port ${PORT:-8080} \
    --server.headless true
