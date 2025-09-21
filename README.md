# GreenOps Agent (Streamlit)

Small Streamlit microservice to show GKE cost and carbon footprint estimates, and generate recommendations via Vertex AI (Gemini).

Requirements
- Python 3.8+
- Install dependencies: `pip install -r requirements.txt`

Environment
- `GCP_PROJECT` - (optional) GCP project id for real BigQuery/Vertex calls.
- `CARBON_API_KEY` - (optional) API key for a carbon footprint service.

Run

```powershell
set GCP_PROJECT=autogreenops; \
streamlit run app.py
```

Notes
- By default the app uses mocked data for BigQuery, Carbon API, and Vertex unless the relevant SDKs and credentials are available.

Enable live BigQuery data (step-by-step)

1) Enable BigQuery API and export
	- In the Google Cloud Console, enable the BigQuery API for your project.
	- Make sure you have exported billing data to a BigQuery dataset/table or have another table with GKE usage/costs. The current SQL in `lib/bigquery_client.py` assumes a table at `<PROJECT>.billing.gke_billing_export`. Update the table path in that file if your export path is different.

2) Create and grant a service account (for VM/Cloud Run)
	- Create a service account: `gcloud iam service-accounts create greenops-sa --project YOUR_PROJECT`
	- Grant it BigQuery Data Viewer and BigQuery Job User roles, e.g.:
	  ```powershell
	  gcloud projects add-iam-policy-binding YOUR_PROJECT --member="serviceAccount:greenops-sa@YOUR_PROJECT.iam.gserviceaccount.com" --role="roles/bigquery.dataViewer"
	  gcloud projects add-iam-policy-binding YOUR_PROJECT --member="serviceAccount:greenops-sa@YOUR_PROJECT.iam.gserviceaccount.com" --role="roles/bigquery.jobUser"
	  ```
	- Create a key (if running on a VM or locally):
	  ```powershell
	  gcloud iam service-accounts keys create key.json --iam-account=greenops-sa@YOUR_PROJECT.iam.gserviceaccount.com --project=YOUR_PROJECT
	  ```

3) Provide credentials to the app
	- Locally or on a VM: set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable to point to the JSON key file, then run `streamlit run app.py --server.port=8080 --server.address=0.0.0.0`.
	  ```powershell
	  $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\path\to\key.json"; streamlit run app.py --server.port=8080 --server.address=0.0.0.0 --server.enableCORS=false --server.enableXsrfProtection=false
	  ```
	- On Cloud Run: use Workload Identity or attach the service account to the Cloud Run service (recommended) so you don't need a key file.

4) Switch the app to live mode
	- In the app sidebar uncheck `Use mocks for external APIs` to let the dashboard attempt live BigQuery queries.

If you see an error similar to "BigQuery query failed: ... The project X has not enabled BigQuery", enable the BigQuery API from the Cloud Console and verify the `GCP_PROJECT` environment variable is set correctly for the app runtime.

Automated deploy script
-----------------------
There is a helper script at `scripts/deploy_cloud_run.sh` that an admin can run from Cloud Shell to enable required APIs, create the service account, grant roles, build the container image, and deploy the app to Cloud Run. Typical usage (run as a project admin):

```powershell
# From repo root in Cloud Shell (admin account)
chmod +x scripts/deploy_cloud_run.sh; ./scripts/deploy_cloud_run.sh
```

If your organization blocks enabling APIs via scripts, ask an org owner to either run the script or enable the following APIs manually in the Cloud Console before deploying: `artifactregistry.googleapis.com`, `cloudbuild.googleapis.com`, `run.googleapis.com`, `bigquery.googleapis.com`, and `storage.googleapis.com`.
