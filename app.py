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
    if CARBON_API_KEY:
        headers['Authorization'] = f"Bearer {CARBON_API_KEY}"
    try:
        r = requests.post(url, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        st.error(f"Carbon API call failed: {e}")
        return {}


def generate_recommendations(prompt: str) -> str:
    """Call Vertex AI text generation (Gemini) via REST.
    This function uses the Vertex REST API endpoint. For production, use google-cloud-aiplatform.
    """
    # Build request
    endpoint = f"{VERTEX_API_ENDPOINT}/v1/projects/{PROJECT_ID}/locations/{REGION}/publishers/google/models/{VERTEX_MODEL_ID}:predict"
    # Note: this REST path may differ depending on model and API; in many cases you should use the google-cloud-aiplatform SDK
    headers = {
        'Content-Type': 'application/json'
    }
    # If using ADC with service account, requests can use metadata server. For simplicity we expect the environment to handle credentials.
    data = {
        'instances': [
            {'content': prompt}
        ]
    }
    try:
        r = requests.post(endpoint, headers=headers, json=data)
        r.raise_for_status()
        resp = r.json()
        # Parse response - this is dependent on model
        return json.dumps(resp, indent=2)
    except Exception as e:
        st.error(f"Vertex AI call failed: {e}")
        return ""


# --- Streamlit UI ---

st.title('GreenOps Agent — Online Boutique')

col1, col2 = st.columns([2, 1])

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

st.sidebar.title('Settings')
st.sidebar.write(f'Project: {PROJECT_ID}')
st.sidebar.write(f'Region: {REGION}')

st.sidebar.markdown('---')
if st.sidebar.button('Refresh credentials'):
    st.experimental_rerun()

# Allow running via `python app.py` for dev (Streamlit will normally be used)
if __name__ == '__main__':
    print('Start Streamlit app on port', STREAMLIT_PORT)
