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
set GCP_PROJECT=your-project-id; \
streamlit run app.py
```

Notes
- By default the app uses mocked data for BigQuery, Carbon API, and Vertex unless the relevant SDKs and credentials are available.
