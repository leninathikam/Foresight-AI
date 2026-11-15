#!/usr/bin/env bash
# Foresight-AI: Google Cloud Run Automated Deployment Script
# Berkeley x DeepMind Hackathon Submission

set -euo pipefail

REGION="${REGION:-us-central1}"
PROJECT_ID="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
GEMINI_API_KEY="${GEMINI_API_KEY:-}"

echo "============================================================"
echo "  Foresight-AI: Google Cloud Run Deployment Pipeline        "
echo "============================================================"

if ! command -v gcloud &>/dev/null; then
    echo "[ERROR] gcloud CLI not found in PATH."
    echo "Please install Google Cloud SDK: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

if [ -z "${PROJECT_ID}" ] || [ "${PROJECT_ID}" = "(unset)" ]; then
    read -rp "Please enter your GCP Project ID: " PROJECT_ID
fi

echo "[INFO] Using GCP Project: ${PROJECT_ID}"
echo "[INFO] Deployment Region: ${REGION}"
gcloud config set project "${PROJECT_ID}" --quiet

if [ -z "${GEMINI_API_KEY}" ] && [ -f ".env" ]; then
    GEMINI_API_KEY=$(grep -E '^GEMINI_API_KEY=' .env | cut -d '=' -f2- | tr -d '\r\n')
fi

echo "[INFO] Enabling required Cloud Run and Cloud Build APIs..."
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com --project "${PROJECT_ID}"

echo "[INFO] Deploying Backend Service (foresight-api) to Cloud Run..."
BACKEND_ENV="FORESIGHT_LLM_PROVIDER=gemini,FORESIGHT_GEMINI_MODEL=gemini-2.5-flash"
if [ -n "${GEMINI_API_KEY}" ]; then
    BACKEND_ENV="${BACKEND_ENV},GEMINI_API_KEY=${GEMINI_API_KEY}"
fi

API_URL=$(gcloud run deploy foresight-api \
    --source . \
    --platform managed \
    --region "${REGION}" \
    --allow-unauthenticated \
    --set-env-vars "${BACKEND_ENV}" \
    --format "value(status.url)" \
    --project "${PROJECT_ID}")

echo "[SUCCESS] Backend deployed at: ${API_URL}"

echo "[INFO] Deploying Frontend Service (foresight-web) to Cloud Run..."
cd apps/web
WEB_URL=$(gcloud run deploy foresight-web \
    --source . \
    --platform managed \
    --region "${REGION}" \
    --allow-unauthenticated \
    --set-env-vars "NEXT_PUBLIC_API_BASE_URL=${API_URL}" \
    --format "value(status.url)" \
    --project "${PROJECT_ID}")
cd ../..

echo "[SUCCESS] Frontend deployed at: ${WEB_URL}"

echo "[INFO] Updating Backend CORS configuration..."
gcloud run services update foresight-api \
    --update-env-vars "FORESIGHT_CORS_ORIGINS=http://localhost:3000,${WEB_URL}" \
    --region "${REGION}" \
    --project "${PROJECT_ID}" \
    --quiet

echo ""
echo "============================================================"
echo "  Foresight-AI: Cloud Run Deployment Complete!             "
echo "============================================================"
echo "Public Web App:       ${WEB_URL}"
echo "Public API Health:    ${API_URL}/api/health"
echo "Future Arena:         ${WEB_URL}/arena"
echo "Safety Challenge:     ${WEB_URL}/safety-challenge"
echo "Decision Receipts:    ${WEB_URL}/receipts"
echo "============================================================"
