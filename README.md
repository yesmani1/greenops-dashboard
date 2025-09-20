# GreenOps Dashboard and Self-Heal Agent

This repository contains a Streamlit dashboard (`app.py`) and a self-healing agent (`greenops-agent/self_heal.py`) intended to run on GKE.

Quick steps to build, push, and deploy to Google Cloud (GCR + GKE):

1) Configure gcloud and enable required APIs

```powershell
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud services enable container.googleapis.com containerregistry.googleapis.com
```

2) Build and push images (replace `YOUR_PROJECT_ID` and optionally tag)

```powershell
cd path\to\repo\greenops-dashboard
docker build -t gcr.io/YOUR_PROJECT_ID/greenops-dashboard:v0.1.0 .
docker push gcr.io/YOUR_PROJECT_ID/greenops-dashboard:v0.1.0

cd greenops-agent
docker build -t gcr.io/YOUR_PROJECT_ID/greenops-selfheal:v0.1.0 .
docker push gcr.io/YOUR_PROJECT_ID/greenops-selfheal:v0.1.0
```

3) Update Kubernetes manifests

- Replace `gcr.io/PROJECT_ID/greenops-dashboard:latest` with `gcr.io/YOUR_PROJECT_ID/greenops-dashboard:v0.1.0` in `deployment.yaml`.
- Replace `gcr.io/PROJECT_ID/greenops-selfheal:latest` similarly in `greenops-agent/k8s/deployment.yaml`.

4) Deploy to GKE

```powershell
# Create cluster (if not exists)
gcloud container clusters create my-cluster --zone us-central1-a --num-nodes=1
gcloud container clusters get-credentials my-cluster --zone us-central1-a

# Create namespace
kubectl create namespace boutique || true

# Apply manifests
kubectl apply -f deployment.yaml -n boutique
kubectl apply -f greenops-agent/k8s/deployment.yaml -n boutique
kubectl apply -f greenops-agent/k8s/serviceaccount-role.yaml -n boutique
```

5) Optional: viewing logs and status

```powershell
kubectl get pods -n boutique
kubectl logs -l app=greenops-selfheal -n boutique
kubectl port-forward svc/greenops-dashboard 8080:80 -n boutique
# then open http://localhost:8080
```

Notes and caveats
- The `AGENT_STATUS_URL` environment variable can be used to override the default service DNS used by the dashboard.
- The self-heal agent deletes pods when `AUTO_APPLY=true` — use with caution.
