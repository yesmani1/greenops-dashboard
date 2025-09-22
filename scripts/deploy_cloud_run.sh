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
  secretmanager.googleapis.com
  carbonfootprint.googleapis.com
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

# 3) Enable required APIs (robust)
enable_api() {
  local api_name="$1"
  local max_retries=10
  local wait_seconds=3

  echo "Ensuring API enabled: $api_name"

  # Try to enable the API (may require permissions)
  if ! gcloud services enable "$api_name" --project="$PROJECT_ID" 2>/tmp/enable_${api_name//./_}.err; then
    echo "Warning: initial attempt to enable $api_name failed. See /tmp/enable_${api_name//./_}.err for details"
  fi

  # Poll until the API appears in the enabled list or we hit max_retries
  local i=0
  while [ $i -lt $max_retries ]; do
    if gcloud services list --enabled --project="$PROJECT_ID" --filter="NAME:${api_name}" --format="value(NAME)" | grep -x "$api_name" >/dev/null 2>&1; then
      echo "API enabled: $api_name"
      return 0
    fi
    i=$((i+1))
    echo "Waiting for $api_name to become enabled... (attempt $i/$max_retries)"
    sleep $wait_seconds
  done

  # If we reach here the API is not enabled — fail with guidance
  echo "ERROR: Could not enable API $api_name for project $PROJECT_ID after multiple attempts." >&2
  echo "This is often caused by insufficient IAM permissions or organization policy restrictions." >&2
  echo "Possible remedies:" >&2
  echo " - Ensure you have permission to enable services (roles/serviceusage.serviceUsageAdmin or project owner)." >&2
  echo " - Ask your org admin to enable the API for the project or organization." >&2
  echo " - Manually enable in the Cloud Console: https://console.cloud.google.com/apis/library/$api_name?project=$PROJECT_ID" >&2
  return 1
}

for api in "${REQUIRED_APIS[@]}"; do
  if ! enable_api "$api"; then
    echo "Failed enabling required API: $api" >&2
    exit 1
  fi
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

# proceed to advanced build & deploy (Artifact Registry + Workload Identity + Secret Manager)
# 6) Advanced build & deploy (Artifact Registry + Workload Identity + Secret Manager)
ARTIFACT_REPO_NAME=${ARTIFACT_REPO_NAME:-greenops-repo}
ARTIFACT_LOCATION=${ARTIFACT_LOCATION:-$REGION}

echo "Preparing Artifact Registry repository: ${ARTIFACT_REPO_NAME} in ${ARTIFACT_LOCATION}"
if ! gcloud artifacts repositories list --location="$ARTIFACT_LOCATION" --project="$PROJECT_ID" --format="value(name)" | grep -x "$ARTIFACT_REPO_NAME" >/dev/null 2>&1; then
  echo "Creating Artifact Registry repository $ARTIFACT_REPO_NAME"
  gcloud artifacts repositories create "$ARTIFACT_REPO_NAME" --repository-format=docker --location="$ARTIFACT_LOCATION" --project="$PROJECT_ID" || true
else
  echo "Artifact Registry repo $ARTIFACT_REPO_NAME already exists"
fi

# Use Artifact Registry image name
IMAGE_NAME="${ARTIFACT_LOCATION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO_NAME}/${SERVICE_NAME}:latest"

echo "Image will be: $IMAGE_NAME"

# 7) Ensure service account exists and grant roles
SA_EMAIL=${SA_EMAIL:-}
if [ -z "$SA_EMAIL" ]; then
  SA_EMAIL="greenops-run-sa@${PROJECT_ID}.iam.gserviceaccount.com"
fi

if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT_ID" >/dev/null 2>&1; then
  echo "Creating service account $SA_EMAIL"
  gcloud iam service-accounts create "$(echo "$SA_EMAIL" | cut -d@ -f1)" --display-name="GreenOps Run SA" --project="$PROJECT_ID"
fi

echo "Granting minimal roles to $SA_EMAIL"
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="roles/bigquery.dataViewer" || true
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="roles/aiplatform.user" || true
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="roles/secretmanager.secretAccessor" || true
gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:${SA_EMAIL}" --role="roles/logging.logWriter" || true

# 8) If CARBON_API_KEY present, create/refresh Secret Manager secret
SECRET_NAME=""
if [ -n "${CARBON_API_KEY:-}" ]; then
  SECRET_NAME=greenops-carbon-key
  if ! gcloud secrets describe "$SECRET_NAME" --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "Creating secret $SECRET_NAME in Secret Manager"
    printf '%s' "$CARBON_API_KEY" | gcloud secrets create "$SECRET_NAME" --data-file=- --project="$PROJECT_ID"
  else
    echo "Adding new secret version for $SECRET_NAME"
    printf '%s' "$CARBON_API_KEY" | gcloud secrets versions add "$SECRET_NAME" --data-file=- --project="$PROJECT_ID"
  fi

  # Grant access to SA
  gcloud secrets add-iam-policy-binding "$SECRET_NAME" --member="serviceAccount:${SA_EMAIL}" --role="roles/secretmanager.secretAccessor" --project="$PROJECT_ID" || true
fi

# 9) Build image with Cloud Build and push to Artifact Registry
echo "Building and pushing image to Artifact Registry: $IMAGE_NAME"
#gcloud builds submit supports Artifact Registry tags
gcloud builds submit --tag "$IMAGE_NAME" .

# 10) Delete existing Cloud Run service (if exists)
EXISTING=$(gcloud run services list --platform=managed --region="$CLOUD_RUN_REGION" --format="value(metadata.name)" --project="$PROJECT_ID" | grep -x "$SERVICE_NAME" || true)
if [ -n "$EXISTING" ]; then
  echo "Deleting existing Cloud Run service: $SERVICE_NAME"
  gcloud run services delete "$SERVICE_NAME" --region="$CLOUD_RUN_REGION" --quiet --project="$PROJECT_ID"
fi

# 11) Deploy to Cloud Run with service account and secret injection (Workload Identity recommended)
echo "Deploying $SERVICE_NAME to Cloud Run with service account ${SA_EMAIL}"
DEPLOY_CMD=(gcloud run deploy "$SERVICE_NAME"
  --image "$IMAGE_NAME"
  --region "$CLOUD_RUN_REGION"
  --platform managed
  --service-account "$SA_EMAIL"
  --allow-unauthenticated
  --set-env-vars "PROJECT_ID=${PROJECT_ID},REGION=${REGION},BILLING_TABLE=${BILLING_TABLE},VERTEX_MODEL_ID=${VERTEX_MODEL_ID},STREAMLIT_PORT=8080"
  --port 8080
  --project "$PROJECT_ID")

if [ -n "$SECRET_NAME" ]; then
  # Inject secret as environment variable CARBON_API_KEY
  DEPLOY_CMD+=(--update-secrets "CARBON_API_KEY=${SECRET_NAME}:latest")
fi

"${DEPLOY_CMD[@]}"

# 12) Post-deploy info
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$CLOUD_RUN_REGION" --platform=managed --format="value(status.url)" --project="$PROJECT_ID")

echo "Deployment completed. Service URL: $SERVICE_URL"
echo "Service is running as service account: $SA_EMAIL"

echo "Security notes:"
echo " - Workload Identity is used by setting the Cloud Run service account. Avoid mounting key files in production."
echo " - CARBON_API_KEY (if provided) is stored in Secret Manager and injected at runtime; do not store secrets in source control."

echo "Done."
