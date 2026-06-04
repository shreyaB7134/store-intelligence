#!/bin/bash
# Store Intelligence Pipeline Runner
# This script processes all sample video clips with one command.
# It expects the Intelligence API to be running (e.g. via docker-compose or Render).

set -e

# Configuration
API_URL="${API_URL:-http://localhost:8000}"
STORE_ID="${STORE_ID:-ST1008}"

echo "=========================================================="
echo " Starting Store Intelligence AI Pipeline (Edge Simulation)"
echo " Target API: ${API_URL}"
echo " Store ID:   ${STORE_ID}"
echo "=========================================================="

echo "[1/2] Processing Entry Camera Feed..."
python -m pipeline.video_processor \
  --store-id "${STORE_ID}" \
  --camera-id "CAM_ENTRY" \
  --video-path "Store 1/CAM 3 - entry.mp4" \
  --api-url "${API_URL}"

echo ""
echo "[2/2] Processing Billing Camera Feed..."
python -m pipeline.video_processor \
  --store-id "${STORE_ID}" \
  --camera-id "CAM_BILLING" \
  --video-path "Store 1/billing_queue.mp4" \
  --api-url "${API_URL}"

echo ""
echo "=========================================================="
echo " Pipeline execution complete! Check your Streamlit dashboard"
echo " to see the real-time AI analytics."
echo "=========================================================="
