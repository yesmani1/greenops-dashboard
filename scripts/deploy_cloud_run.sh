#!/usr/bin/env bash
set -euo pipefail

# Automated deploy script for GreenOps Agent (Cloud Run)
# Run this in Cloud Shell (or any environment with gcloud, bq, jq installed)
# Usage: ./scripts/deploy_cloud_run.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Load env.config
if [ ! -f env.config ]; then
  echo "env.config not found in project root. Create it and set required variables." >&2
  exit 1
fi
# shellcheck disable=SC1091
source env.config

# Required env vars
: "${PROJECT_ID:?PROJECT_ID must be set in env.config}"
: "${REGION:?REGION must be set in env.config}"
: "${BILLING_TABLE:?BILLING_TABLE must be set in env.config}"
: "${GOOGLE_APPLICATION_CREDENTIALS:?GOOGLE_APPLICATION_CREDENTIALS must be set in env.config}"
: "${VERTEX_MODEL_ID:?VERTEX_MODEL_ID must be set in env.config}"

SERVICE_NAME=${SERVICE_NAME:-greenops-agent}
IMAGE_NAME="gcr.io/${PROJECT_ID}/${SERVICE_NAME}:latest"
CLOUD_RUN_REGION=${REGION}

REQUIRED_APIS=(
  run.googleapis.com
  cloudbuild.googleapis.com
  containerregistry.googleapis.com
  artifactregistry.googleapis.com
  bigquery.googleapis.com
  billingbudgets.googleapis.com
  cloudbilling.googleapis.com
  aiplatform.googleapis.com
)

echo "Starting deployment for project: ${PROJECT_ID} region: ${REGION} service: ${SERVICE_NAME}"

# 1) Validate gcloud available and authenticated
if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI not found. Please install gcloud or run this in Cloud Shell." >&2
  exit 1
fi

CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null || echo "")
if [ -z "$CURRENT_PROJECT" ]; then
  echo "No gcloud project configured. Setting project to ${PROJECT_ID}" 
  gcloud config set project "$PROJECT_ID"
else
  if [ "$CURRENT_PROJECT" != "$PROJECT_ID" ]; then
    echo "gcloud project ($CURRENT_PROJECT) different from env PROJECT_ID ($PROJECT_ID). Setting project to ${PROJECT_ID}"
    gcloud config set project "$PROJECT_ID"
  fi
fi

CURRENT_ACCOUNT=$(gcloud config get-value account 2>/dev/null || echo "")
if [ -z "$CURRENT_ACCOUNT" ]; then
  echo "No gcloud account configured. Please authenticate: gcloud auth login" >&2
  exit 1
fi

echo "Active account: $CURRENT_ACCOUNT"

# 2) Validate project exists
if ! gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
  echo "Project $PROJECT_ID does not exist or you do not have permission." >&2
  exit 1
fi

# 3) Enable required APIs
for api in "${REQUIRED_APIS[@]}"; do
  echo "Ensuring API enabled: $api"
  gcloud services enable "$api" --project="$PROJECT_ID" || true
done

# 4) Validate service account file
if [ ! -f "$GOOGLE_APPLICATION_CREDENTIALS" ]; then
  echo "Service account key file not found at $GOOGLE_APPLICATION_CREDENTIALS" >&2
  exit 1
fi

# Extract service account email if possible
SA_EMAIL=""
if command -v jq >/dev/null 2>&1; then
  SA_EMAIL=$(jq -r '.client_email // .client_id // empty' "$GOOGLE_APPLICATION_CREDENTIALS" || true)
fi
if [ -z "$SA_EMAIL" ]; then
  echo "Warning: Could not determine service account email from credentials file. Ensure the service account has BigQuery access." >&2
else
  echo "Detected service account: $SA_EMAIL"
fi

# 5) Check BigQuery access to billing table
echo "Checking BigQuery table access for project $PROJECT_ID: $BILLING_TABLE"
if ! command -v bq >/dev/null 2>&1; then
  echo "bq CLI not found. Install Cloud SDK components or run in Cloud Shell." >&2
  exit 1
fi

# Try querying a small preview using the provided credentials (if SA is local we'll rely on ADC)
BQ_EXPORT_TEST_QUERY="SELECT COUNT(1) as c FROM \`${BILLING_TABLE}\` LIMIT 1"
set +e
bq --project_id="$PROJECT_ID" query --nouse_legacy_sql --format=json "$BQ_EXPORT_TEST_QUERY" >/tmp/bq_test.json 2>/tmp/bq_test.err
BQ_EXIT=$?
set -e
if [ $BQ_EXIT -ne 0 ]; then
  echo "Initial BigQuery access check failed. Attempting to grant BigQuery Data Viewer to service account (if SA email is known)."
  if [ -n "$SA_EMAIL" ]; then
    echo "Granting roles/bigquery.dataViewer on dataset to $SA_EMAIL (requires owner privileges)."
    # Attempt to grant dataset-level access using bq -- assuming dataset is like project.dataset.table
    DATASET_ID=$(echo "$BILLING_TABLE" | awk -F'.' '{print $2}') || true
    if [ -n "$DATASET_ID" ]; then
      echo "Attempting to grant dataset-level access to $SA_EMAIL on dataset $PROJECT_ID:$DATASET_ID"
      gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$SA_EMAIL" --role="roles/bigquery.dataViewer" || true
      echo "Re-testing BigQuery query"
      bq --project_id="$PROJECT_ID" query --nouse_legacy_sql --format=json "$BQ_EXPORT_TEST_QUERY" >/tmp/bq_test.json 2>/tmp/bq_test.err || true
      if [ $? -ne 0 ]; then
        echo "BigQuery query still failing after granting role. Check dataset ACLs and billing export table permissions. See /tmp/bq_test.err" >&2
        cat /tmp/bq_test.err || true
        # We continue but warn
      else
        echo "BigQuery query succeeded after granting role."
      fi
    else
      echo "Could not parse dataset id from BILLING_TABLE. Ensure the format project.dataset.table" >&2
    fi
  else
    echo "Service account email unknown; cannot auto-grant roles. Inspect /tmp/bq_test.err for details." >&2
  fi
else
  echo "BigQuery preview query succeeded. Output:" 
  cat /tmp/bq_test.json
fi

# 6) Build container image using Cloud Build
echo "Building container image ${IMAGE_NAME} with Cloud Build"
# Use Cloud Build to push to Artifact Registry / Container Registry
gcloud builds submit --tag "$IMAGE_NAME" .

# 7) Delete existing Cloud Run service (if exists)
EXISTING=$(gcloud run services list --platform=managed --region="$CLOUD_RUN_REGION" --format="value(metadata.name)" --project="$PROJECT_ID" | grep -x "$SERVICE_NAME" || true)
if [ -n "$EXISTING" ]; then
  echo "Deleting existing Cloud Run service: $SERVICE_NAME"
  gcloud run services delete "$SERVICE_NAME" --region="$CLOUD_RUN_REGION" --quiet --project="$PROJECT_ID"
fi

# 8) Deploy to Cloud Run
echo "Deploying to Cloud Run: $SERVICE_NAME"
# Common runtime env vars to pass (we will pass the path to credentials via Secret Manager or mount if needed)
# For this script we pass minimal environment variables; for production store secrets in Secret Manager
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE_NAME" \
  --region "$CLOUD_RUN_REGION" \
  --platform managed \
  --allow-unauthenticated \
  --set-env-vars "PROJECT_ID=${PROJECT_ID},REGION=${REGION},BILLING_TABLE=${BILLING_TABLE},VERTEX_MODEL_ID=${VERTEX_MODEL_ID},STREAMLIT_PORT=8080" \
  --port 8080 \
  --project "$PROJECT_ID"

# 9) Post-deploy info
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$CLOUD_RUN_REGION" --platform=managed --format="value(status.url)" --project="$PROJECT_ID")

echo "Deployment completed. Service URL: $SERVICE_URL"

echo "Note: For the service to access BigQuery and Vertex APIs, configure Workload Identity or mount credentials via Secret Manager and set GOOGLE_APPLICATION_CREDENTIALS accordingly."

echo "Done."
