#!/usr/bin/env bash
set -euo pipefail

# deploy_cloud_run.sh
# Automated deploy script for GreenOps Agent (Cloud Run)
# Run this in Cloud Shell or any environment with gcloud authenticated as a project admin.

PROJECT="autogreenops"
REGION="us-central1"
IMAGE="gcr.io/${PROJECT}/greenops-agent"
SERVICE="greenops-agent"
SA_NAME="greenops-sa"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
LIVE_TABLE="autogreenops.billing_dataset.gcp_billing_export_resource_v1_018317_83DA9C_15D7B1"
MOCK_TABLE="autogreenops.billing_dataset.mock_billing_data"
# Optional behavior flags (set in the environment or export before running):
# DELETE_BEFORE_DEPLOY=true   -> delete existing Cloud Run service before deploy
# TEMP_DISABLE_PUBLIC=true   -> remove public access (allUsers) before deploy
# RESTORE_PUBLIC=true        -> if TEMP_DISABLE_PUBLIC used, restore public after deploy

DELETE_BEFORE_DEPLOY=${DELETE_BEFORE_DEPLOY:-"false"}
TEMP_DISABLE_PUBLIC=${TEMP_DISABLE_PUBLIC:-"false"}
RESTORE_PUBLIC=${RESTORE_PUBLIC:-"false"}

echo "Starting GreenOps Agent automated deploy for project: ${PROJECT}"

echo "1) Validate project exists and current account"
gcloud config set project "${PROJECT}"
gcloud projects describe "${PROJECT}" >/dev/null
echo "  Project OK"

echo "2) Enable required APIs"
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com bigquery.googleapis.com containerregistry.googleapis.com storage.googleapis.com --project="${PROJECT}"
echo "  APIs enabled"

# If requested, temporarily remove public access so the running service stops serving anonymous traffic
if [ "${TEMP_DISABLE_PUBLIC}" = "true" ]; then
  echo "2.a) Temporarily removing public invoker binding from ${SERVICE} (if present)"
  if gcloud run services get-iam-policy "${SERVICE}" --platform=managed --region="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
    gcloud run services remove-iam-policy-binding "${SERVICE}" --member="allUsers" --role="roles/run.invoker" --platform=managed --region="${REGION}" --project="${PROJECT}" || true
    echo "  Public access removed (if it existed)"
  else
    echo "  Service ${SERVICE} not present yet; skipping public access removal"
  fi
fi

echo "3) Create service account if missing: ${SA_EMAIL}"
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" --display-name="GreenOps Agent service account" --project="${PROJECT}"
  echo "  Service account created"
else
  echo "  Service account already exists"
fi

echo "4) Grant BigQuery roles to service account"
gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${SA_EMAIL}" --role="roles/bigquery.dataViewer"
gcloud projects add-iam-policy-binding "${PROJECT}" --member="serviceAccount:${SA_EMAIL}" --role="roles/bigquery.jobUser"
echo "  Granted BigQuery roles"

echo "5) (Optional) Grant deployer roles to current user so they can deploy and use SA"
CURRENT_ACCOUNT=$(gcloud config get-value account)
echo "  Current account: ${CURRENT_ACCOUNT}"
gcloud projects add-iam-policy-binding "${PROJECT}" --member="user:${CURRENT_ACCOUNT}" --role="roles/run.admin" || true
gcloud projects add-iam-policy-binding "${PROJECT}" --member="user:${CURRENT_ACCOUNT}" --role="roles/iam.serviceAccountUser" || true

echo "6) Build and push container with Cloud Build"
gcloud builds submit --tag "${IMAGE}" .

echo "7) Deploy to Cloud Run using service account ${SA_EMAIL}"

# If requested, delete the existing service before deploying (ensures old revisions removed)
if [ "${DELETE_BEFORE_DEPLOY}" = "true" ]; then
  echo "7.a) Deleting existing Cloud Run service ${SERVICE} before deploy"
  if gcloud run services describe "${SERVICE}" --platform=managed --region="${REGION}" --project="${PROJECT}" >/dev/null 2>&1; then
    gcloud run services delete "${SERVICE}" --platform=managed --region="${REGION}" --project="${PROJECT}" --quiet || true
    echo "  Existing service deleted"
  else
    echo "  No existing service to delete"
  fi
fi

gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --service-account "${SA_EMAIL}" \
  --set-env-vars "GCP_PROJECT=${PROJECT},LIVE_BQ_TABLE=${LIVE_TABLE},MOCK_BQ_TABLE=${MOCK_TABLE}"

# Optionally restore public access after deploy
if [ "${TEMP_DISABLE_PUBLIC}" = "true" ] && [ "${RESTORE_PUBLIC}" = "true" ]; then
  echo "7.b) Restoring public invoker binding to ${SERVICE}"
  gcloud run services add-iam-policy-binding "${SERVICE}" --member="allUsers" --role="roles/run.invoker" --platform=managed --region="${REGION}" --project="${PROJECT}" || true
  echo "  Public access restored"
fi

echo "Deployment complete. Get service URL:" 
gcloud run services describe "${SERVICE}" --region "${REGION}" --platform managed --format 'value(status.url)'

echo "NOTE: If your organization blocks API enablement, please have an org admin run this script or enable APIs via the Cloud Console."
