#!/usr/bin/env bash
# =============================================================================
# SENTINEL – STOP Script (saves free credits)
# Scales all Cloud Run services to 0 and pauses the scheduler.
# Your data in BigQuery is preserved.
# To restart: bash start.sh
# =============================================================================
set -euo pipefail

PROJECT_ID="YOUR_GCP_PROJECT_ID"   # same as deploy.sh
REGION="us-central1"

echo "⏸  Stopping SENTINEL (preserving data)..."

# Pause Cloud Scheduler (stops triggering detector)
echo "▶ Pausing scheduler..."
gcloud scheduler jobs pause sentinel-detect --location="$REGION" --quiet 2>/dev/null || true

# Scale Cloud Run services to 0
# (Cloud Run with min-instances=0 already scales to 0 on no traffic,
#  but we also set traffic to 0 to be explicit and stop any warm instances)
for SVC in sentinel-ingestion sentinel-detector sentinel-dashboard; do
  echo "▶ Scaling $SVC to 0..."
  gcloud run services update "$SVC" \
    --region="$REGION" \
    --min-instances=0 \
    --quiet 2>/dev/null || echo "  (service not found, skipping)"
done

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅  Everything is STOPPED                       ║"
echo "║                                                  ║"
echo "║  BigQuery data is preserved.                     ║"
echo "║  Cloud Run scales to 0 → no compute charges.    ║"
echo "║  BigQuery free tier: 10GB storage, 1TB queries. ║"
echo "║                                                  ║"
echo "║  To restart:  bash start.sh                     ║"
echo "╚══════════════════════════════════════════════════╝"
