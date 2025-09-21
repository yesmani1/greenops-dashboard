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

echo "Starting GreenOps Agent automated deploy for project: ${PROJECT}"

echo "1) Validate project exists and current account"
gcloud config set project "${PROJECT}"
gcloud projects describe "${PROJECT}" >/dev/null
echo "  Project OK"

echo "2) Enable required APIs"
gcloud services enable artifactregistry.googleapis.com cloudbuild.googleapis.com run.googleapis.com bigquery.googleapis.com containerregistry.googleapis.com storage.googleapis.com --project="${PROJECT}"
echo "  APIs enabled"

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
gcloud run deploy "${SERVICE}" \
  --image "${IMAGE}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --service-account "${SA_EMAIL}" \
  --set-env-vars "GCP_PROJECT=${PROJECT},LIVE_BQ_TABLE=${LIVE_TABLE},MOCK_BQ_TABLE=${MOCK_TABLE}"

echo "Deployment complete. Get service URL:" 
gcloud run services describe "${SERVICE}" --region "${REGION}" --platform managed --format 'value(status.url)'

echo "NOTE: If your organization blocks API enablement, please have an org admin run this script or enable APIs via the Cloud Console."
