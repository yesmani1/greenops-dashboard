#!/usr/bin/env bash
set -euo pipefail

# deploy_cloud_run.sh
# Automated deploy script for GreenOps Agent (Cloud Run)
# Run this in Cloud Shell or any environment with gcloud authenticated as a project admin.

# === Configuration: override these by exporting env vars before running ===
# Example (Cloud Shell):
# export GCP_PROJECT="autogreenops"; export DELETE_BEFORE_DEPLOY=true; bash ./scripts/deploy_cloud_run.sh

# Primary project (GCP_PROJECT recommended). Falls back to 'autogreenops' if unset.
GCP_PROJECT=${GCP_PROJECT:-"autogreenops"}
PROJECT="${GCP_PROJECT}"

# Region and service defaults
REGION=${REGION:-"us-central1"}
SERVICE=${SERVICE:-"greenops-agent"}

# Container image (can override IMAGE env var if you want to push to a different registry)
IMAGE=${IMAGE:-"gcr.io/${PROJECT}/greenops-agent"}

# Service account settings
SA_NAME=${SA_NAME:-"greenops-sa"}
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

# Default BigQuery table paths (override with LIVE_TABLE / MOCK_TABLE env vars as needed)
LIVE_TABLE=${LIVE_TABLE:-"${PROJECT}.billing_dataset.gcp_billing_export_resource_v1_018317_83DA9C_15D7B1"}
MOCK_TABLE=${MOCK_TABLE:-"${PROJECT}.billing_dataset.mock_billing_data"}

# Optional behavior flags (set to "true"/"false"). Default: safe (false).
# DELETE_BEFORE_DEPLOY=true    -> delete existing Cloud Run service before deploy
# TEMP_DISABLE_PUBLIC=true    -> remove public allUsers invoker before deploy
# RESTORE_PUBLIC=true         -> if TEMP_DISABLE_PUBLIC used, restore public after deploy
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

# Optionally bake a local service account key into the image (INSECURE).
# Set KEY_SRC to the path of your local JSON key file to include it in the image.
# Example: export KEY_SRC="/home/nandhaji/GreenOps_Agent/greenops-sa-key.json"
KEY_SRC=${KEY_SRC:-"/home/nandhaji/GreenOps_Agent/greenops-sa-key.json"}
KEY_DST_NAME=${KEY_DST_NAME:-"greenops-sa-key.json"}
INCLUDE_KEY_IN_IMAGE=false

if [ -f "${KEY_SRC}" ]; then
  echo "Including service account key from ${KEY_SRC} into build context as ${KEY_DST_NAME} (will be removed after build)."
  cp "${KEY_SRC}" "./${KEY_DST_NAME}"
  chmod 600 "./${KEY_DST_NAME}"
  INCLUDE_KEY_IN_IMAGE=true
  # ensure cleanup on exit
  trap 'rm -f "./${KEY_DST_NAME}"' EXIT
else
  echo "No local key found at ${KEY_SRC}; building without baking credentials into the image."
fi

# Sanity check: ensure a Dockerfile exists in the build context. Cloud Build will
# fail with "Dockerfile required" if it's missing or you're in the wrong folder.
if [ ! -f Dockerfile ]; then
  echo "ERROR: Dockerfile not found in $(pwd). Please run this script from the repository root where the Dockerfile lives or create a Dockerfile."
  echo "Current directory listing:"; ls -la
  exit 1
fi

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

# Build env var string for deployment; include credentials path if key was baked in
DEPLOY_ENV_VARS="GCP_PROJECT=${PROJECT},LIVE_BQ_TABLE=${LIVE_TABLE},MOCK_BQ_TABLE=${MOCK_TABLE}"
if [ "${INCLUDE_KEY_IN_IMAGE}" = true ] || [ "${INCLUDE_KEY_IN_IMAGE}" = "true" ]; then
  DEPLOY_ENV_VARS=",GOOGLE_APPLICATION_CREDENTIALS=/app/${KEY_DST_NAME},${DEPLOY_ENV_VARS}"
  # Ensure GOOGLE_APPLICATION_CREDENTIALS is first so it's available during startup
  DEPLOY_ENV_VARS="GOOGLE_APPLICATION_CREDENTIALS=/app/${KEY_DST_NAME},${DEPLOY_ENV_VARS#*,}"
fi

gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --service-account "${SA_EMAIL}" \
  --set-env-vars "${DEPLOY_ENV_VARS}"

# Optionally restore public access after deploy
if [ "${TEMP_DISABLE_PUBLIC}" = "true" ] && [ "${RESTORE_PUBLIC}" = "true" ]; then
  echo "7.b) Restoring public invoker binding to ${SERVICE}"
  gcloud run services add-iam-policy-binding "${SERVICE}" --member="allUsers" --role="roles/run.invoker" --platform=managed --region="${REGION}" --project="${PROJECT}" || true
  echo "  Public access restored"
fi

echo "Deployment complete. Get service URL:" 
gcloud run services describe "${SERVICE}" --region "${REGION}" --platform managed --format 'value(status.url)'

echo "NOTE: If your organization blocks API enablement, please have an org admin run this script or enable APIs via the Cloud Console."
