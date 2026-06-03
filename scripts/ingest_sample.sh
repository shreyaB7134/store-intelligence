#!/bin/bash
# Load sample events and POS data into the running API
# Usage: ./scripts/ingest_sample.sh

set -e

API_URL="${API_URL:-http://localhost:8000}"
STORE_ID="${STORE_ID:-ST1076}"

echo "Checking API health..."
curl -sf "${API_URL}/health" | python3 -m json.tool

echo ""
echo "Loading sample events..."
python3 pipeline/load_sample_data.py

echo ""
echo "Fetching metrics for store ${STORE_ID}..."
curl -s "${API_URL}/stores/${STORE_ID}/metrics" | python3 -m json.tool

echo ""
echo "Fetching funnel for store ${STORE_ID}..."
curl -s "${API_URL}/stores/${STORE_ID}/funnel" | python3 -m json.tool

echo ""
echo "Done! Open http://localhost:8501 for the live dashboard."
