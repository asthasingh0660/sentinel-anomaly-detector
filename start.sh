#!/usr/bin/env bash
# =============================================================================
# SENTINEL – START / Resume Script
# Resumes scheduler. Cloud Run wakes automatically on traffic.
# =============================================================================
set -euo pipefail

PROJECT_ID="YOUR_GCP_PROJECT_ID"   # same as deploy.sh
REGION="us-central1"

echo "▶ Resuming SENTINEL..."

# Resume Cloud Scheduler
gcloud scheduler jobs resume sentinel-detect --location="$REGION" --quiet

DASHBOARD_URL=$(gcloud run services describe sentinel-dashboard \
  --region="$REGION" --format="value(status.url)" 2>/dev/null || echo "(not deployed)")

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅  SENTINEL is running again                   ║"
echo "║  Dashboard → $DASHBOARD_URL"
echo "╚══════════════════════════════════════════════════╝"
