import os
import json
import time
from typing import Dict, Any

import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from google.cloud import bigquery
from google.oauth2 import service_account
import google.auth
from google.auth.transport.requests import Request
from google.cloud import aiplatform
from dotenv import load_dotenv

# Load environment
load_dotenv('env.config')

PROJECT_ID = os.getenv('PROJECT_ID')
REGION = os.getenv('REGION')
BILLING_TABLE = os.getenv('BILLING_TABLE')
GOOGLE_APPLICATION_CREDENTIALS = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
CARBON_API_ENDPOINT = os.getenv('CARBON_API_ENDPOINT')
CARBON_API_KEY = os.getenv('CARBON_API_KEY')
VERTEX_MODEL_ID = os.getenv('VERTEX_MODEL_ID')
VERTEX_API_ENDPOINT = os.getenv('VERTEX_API_ENDPOINT')
STREAMLIT_PORT = int(os.getenv('STREAMLIT_PORT', '8080'))
BILLING_QUERY_LIMIT = int(os.getenv('BILLING_QUERY_LIMIT', '10000'))
EMISSION_FACTOR_KG_PER_USD = float(os.getenv('EMISSION_FACTOR_KG_PER_USD', '0.5'))

# Credentials
credentials = None
if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
    credentials = service_account.Credentials.from_service_account_file(GOOGLE_APPLICATION_CREDENTIALS)

# BigQuery client
bq_client = bigquery.Client(project=PROJECT_ID, credentials=credentials)

st.set_page_config(page_title='GreenOps Agent', layout='wide')

# --- Helpers ---

def run_billing_query(query: str) -> pd.DataFrame:
    job_config = bigquery.QueryJobConfig()
    query_job = bq_client.query(query, job_config=job_config)
    result = query_job.result()
    df = result.to_dataframe()
    return df


def fetch_costs_by_project(limit: int = 1000) -> pd.DataFrame:
    query = f"""
    SELECT
      project.id as project_id,
      service.description as service,
      sku.description as sku,
      SUM(cost) as total_cost,
      TIMESTAMP_TRUNC(_PARTITIONTIME, MONTH) AS month
    FROM `{BILLING_TABLE}`
    WHERE cost IS NOT NULL
    GROUP BY project_id, service, sku, month
    ORDER BY month DESC
    LIMIT {limit}
    """
    return run_billing_query(query)


def call_carbon_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Use the Carbon Footprint API - this is a placeholder path that may need updating depending on API version
    url = f"{CARBON_API_ENDPOINT}/projects/{PROJECT_ID}:estimateBillableEmissions"
    headers = {"Content-Type": "application/json"}
    # Acquire an OAuth access token for authenticated calls
    try:
        token = get_access_token()
        if token:
            headers['Authorization'] = f"Bearer {token}"
    except Exception:
        # fall back to API key usage if provided
        pass
    if CARBON_API_KEY:
        # Some services accept api-key in header or as x-api-key; include it if provided
        headers['x-api-key'] = CARBON_API_KEY

    try:
        r = requests.post(url, headers=headers, json=payload)
        # If Carbon API returns 404 (method missing) or other client error, fallback to simple estimator
        if r.status_code == 404:
            st.warning(f"Carbon API returned 404 for url: {url}; falling back to heuristic estimator")
            # payload expected to have cost or we compute from billing separately
            cost = payload.get('cost') if isinstance(payload, dict) else None
            if cost is not None:
                return estimate_co2_from_cost(float(cost))
            return {}
        r.raise_for_status()
        return r.json()
    except requests.HTTPError as e:
        st.error(f"Carbon API call failed: {e}")
        # fallback: estimate using emission factor
        cost = payload.get('cost') if isinstance(payload, dict) else None
        if cost is not None:
            return estimate_co2_from_cost(float(cost))
        return {}
    except Exception as e:
        st.error(f"Carbon API call failed: {e}")
        return {}


def estimate_co2_from_cost(total_cost_usd: float) -> Dict[str, Any]:
    """Simple heuristic fallback: estimate kg CO2 from USD cost using a configurable factor."""
    estimated = total_cost_usd * EMISSION_FACTOR_KG_PER_USD
    return {"estimated_kgCO2": estimated, "factor_kg_per_usd": EMISSION_FACTOR_KG_PER_USD}



import google.generativeai as genai

def generate_recommendations(prompt: str) -> str:
    """Call Gemini using the Google GenAI SDK."""
    try:
        genai.configure(api_key=os.getenv("GENAI_API_KEY"))  # Set your API key

        candidate_models = [VERTEX_MODEL_ID, 'gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-1.0-pro']
        last_error = None

        for model_name in candidate_models:
            if not model_name:
                continue
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content(prompt)
                if response.text:
                    st.success(f"GenAI model succeeded with: {model_name}")
                    return response.text
                else:
                    st.warning(f"Model {model_name} returned empty response")
                    last_error = "Empty response"
            except Exception as e:
                error_msg = str(e)
                st.warning(f"GenAI model {model_name} failed: {error_msg}")
                last_error = error_msg
                continue

        st.error("All candidate GenAI models failed. See messages above for details.")
        return f"Error: All models failed. Last error: {last_error}"

    except Exception as e:
        st.error(f"Failed to initialize GenAI SDK: {e}")
        return f"Error: Failed to initialize GenAI SDK: {e}"


def get_access_token() -> str:
    """Get an OAuth2 access token using ADC or the service account key provided.
    Returns a token string or empty string on failure.
    """
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    creds = None
    try:
        if GOOGLE_APPLICATION_CREDENTIALS and os.path.exists(GOOGLE_APPLICATION_CREDENTIALS):
            creds = service_account.Credentials.from_service_account_file(GOOGLE_APPLICATION_CREDENTIALS, scopes=scopes)
        else:
            creds, _ = google.auth.default(scopes=scopes)
        creds.refresh(Request())
        return creds.token
    except Exception as e:
        # don't raise in UI; return empty so callers may fallback
        st.warning(f"Could not obtain access token: {e}")
        return ""


# --- Streamlit UI ---

st.title('GreenOps Agent — Online Boutique')

col1, col2 = st.columns([2, 1])

# Display current Vertex model and quick hint
st.sidebar.markdown('### Vertex AI model')
st.sidebar.write(f"Model id: {VERTEX_MODEL_ID}")
#st.sidebar.caption('If you get 404s, update `VERTEX_MODEL_ID` in `env.config` to a valid publisher model (e.g., text-bison@001)')

with col1:
    st.header('Costs by project')
    limit = st.number_input('Query limit', min_value=100, max_value=100000, value=1000, step=100)
    if st.button('Fetch billing data'):
        with st.spinner('Querying BigQuery...'):
            df = fetch_costs_by_project(limit)
            st.session_state['billing_df'] = df
            st.success(f'Fetched {len(df)} rows')

    df = st.session_state.get('billing_df')
    if df is not None:
        st.dataframe(df.head(200))
        fig = px.bar(df.groupby('service', as_index=False)['total_cost'].sum(), x='service', y='total_cost', title='Cost by service')
        st.plotly_chart(fig, use_container_width=True)

    st.header('AI Recommendations')
    prompt = st.text_area('Prompt for Gemini (or leave to auto-generate)', height=150)
    if st.button('Generate recommendations'):
        df = st.session_state.get('billing_df')
        if df is None:
            st.warning('Please fetch billing data first')
        else:
            if not prompt:
                # Auto-generate prompt from data
                top_services = df.groupby('service', as_index=False)['total_cost'].sum().sort_values('total_cost', ascending=False).head(5)
                prompt = (
                    f"You are Cloud Cost Optimization assistant. The project {PROJECT_ID} has the following top services by cost: \n"
                    + "\n".join([f"{r['service']}: ${r['total_cost']:.2f}" for _, r in top_services.iterrows()])
                    + "\nProvide 5 practical recommendations to reduce cost and CO2 emissions, prioritized and with estimated savings where possible."
                )
            with st.spinner('Calling Vertex AI Gemini...'):
                rec = generate_recommendations(prompt)
                st.code(rec)
with col2:
    st.header('CO₂ Estimates')
    if st.button('Estimate CO2 from costs'):
        # Build simple payload from billing summary
        df = st.session_state.get('billing_df')
        if df is None:
            st.warning('Please fetch billing data first')
        else:
            summary = df.groupby('project_id', as_index=False)['total_cost'].sum()
            payload = {
                "cost": summary['total_cost'].sum(),
                "project": PROJECT_ID,
            }
            with st.spinner('Calling Carbon Footprint API...'):
                carbon_resp = call_carbon_api(payload)
                st.json(carbon_resp)


st.sidebar.title('Settings')
st.sidebar.write(f'Project: {PROJECT_ID}')
st.sidebar.write(f'Region: {REGION}')

st.sidebar.markdown('---')
if st.sidebar.button('Refresh credentials'):
    st.experimental_rerun()

# Allow running via `python app.py` for dev (Streamlit will normally be used)
if __name__ == '__main__':
    print('Start Streamlit app on port', STREAMLIT_PORT)
