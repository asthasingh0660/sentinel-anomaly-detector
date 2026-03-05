#!/usr/bin/env bash
# =============================================================================
# SENTINEL – Full GCP Deploy Script
# Run this once to deploy everything. Free-tier safe.
# Usage: bash deploy.sh
# =============================================================================
set -euo pipefail

# ── EDIT THESE ────────────────────────────────────────────────────────────────
PROJECT_ID="YOUR_GCP_PROJECT_ID"          # e.g. my-sentinel-project
REGION="us-central1"                       # free-tier region
ANTHROPIC_API_KEY="YOUR_ANTHROPIC_KEY"     # from console.anthropic.com
# ─────────────────────────────────────────────────────────────────────────────

BQ_DATASET="anomaly_detection"
REPO="sentinel-repo"
IMAGE_BASE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPO"

echo "╔══════════════════════════════════════════╗"
echo "║  SENTINEL – Deploy to GCP                ║"
echo "╚══════════════════════════════════════════╝"

# 1. Set project
gcloud config set project "$PROJECT_ID"

# 2. Enable required APIs (one-time, takes ~60s)
echo "▶ Enabling APIs..."
gcloud services enable \
  run.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com \
  --quiet

# 3. Create Artifact Registry repo
echo "▶ Creating Artifact Registry..."
gcloud artifacts repositories create "$REPO" \
  --repository-format=docker \
  --location="$REGION" \
  --quiet 2>/dev/null || echo "  (already exists)"

# 4. Auth Docker
gcloud auth configure-docker "$REGION-docker.pkg.dev" --quiet

# ── Build & Push images ────────────────────────────────────────────────────────
build_and_push() {
  local name=$1
  local dir=$2
  echo "▶ Building $name..."
  docker build -t "$IMAGE_BASE/$name:latest" "$dir"
  docker push "$IMAGE_BASE/$name:latest"
}

build_and_push "ingestion" "./ingestion"
build_and_push "detector"  "./detector"
build_and_push "dashboard" "./dashboard"

# ── Deploy Cloud Run services ─────────────────────────────────────────────────

echo "▶ Deploying ingestion service..."
gcloud run deploy sentinel-ingestion \
  --image="$IMAGE_BASE/ingestion:latest" \
  --region="$REGION" \
  --platform=managed \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,BQ_DATASET=$BQ_DATASET,POLL_SECONDS=60" \
  --memory=256Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=1 \
  --quiet

echo "▶ Deploying detector service..."
gcloud run deploy sentinel-detector \
  --image="$IMAGE_BASE/detector:latest" \
  --region="$REGION" \
  --platform=managed \
  --no-allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,BQ_DATASET=$BQ_DATASET,ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY,Z_THRESHOLD=2.5,LOOKBACK_HOURS=24" \
  --memory=512Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=1 \
  --timeout=120 \
  --quiet

echo "▶ Deploying dashboard service..."
DASHBOARD_URL=$(gcloud run deploy sentinel-dashboard \
  --image="$IMAGE_BASE/dashboard:latest" \
  --region="$REGION" \
  --platform=managed \
  --allow-unauthenticated \
  --set-env-vars="GCP_PROJECT_ID=$PROJECT_ID,BQ_DATASET=$BQ_DATASET" \
  --memory=256Mi \
  --cpu=1 \
  --min-instances=0 \
  --max-instances=1 \
  --quiet \
  --format="value(status.url)")

echo "  Dashboard URL: $DASHBOARD_URL"

# ── Cloud Scheduler (trigger detector every 5 min) ────────────────────────────
DETECTOR_URL=$(gcloud run services describe sentinel-detector \
  --region="$REGION" --format="value(status.url)")

# Create a service account for scheduler to invoke Cloud Run
SA_NAME="sentinel-scheduler"
SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SA_NAME" \
  --display-name="Sentinel Scheduler SA" --quiet 2>/dev/null || true

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA_EMAIL" \
  --role="roles/run.invoker" --quiet

echo "▶ Creating Cloud Scheduler job (every 5 min)..."
gcloud scheduler jobs create http sentinel-detect \
  --location="$REGION" \
  --schedule="*/5 * * * *" \
  --uri="$DETECTOR_URL/detect" \
  --http-method=POST \
  --oidc-service-account-email="$SA_EMAIL" \
  --quiet 2>/dev/null || \
gcloud scheduler jobs update http sentinel-detect \
  --location="$REGION" \
  --schedule="*/5 * * * *" \
  --uri="$DETECTOR_URL/detect" \
  --http-method=POST \
  --oidc-service-account-email="$SA_EMAIL" \
  --quiet

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  ✅  DEPLOY COMPLETE                             ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  Dashboard → $DASHBOARD_URL"
echo "║  Detector  → $DETECTOR_URL"
echo "╠══════════════════════════════════════════════════╣"
echo "║  To STOP everything (save credits):              ║"
echo "║    bash stop.sh                                  ║"
echo "╚══════════════════════════════════════════════════╝"
