import streamlit as st
import pandas as pd
import os
import requests

st.set_page_config(page_title="GreenOps Agent Dashboard", layout="wide")
st.title("🌱 GreenOps Agent Dashboard")

# ------------------------
# Section 1: Cost Chart (mocked)
# ------------------------
cost_data = pd.DataFrame({
    "service": ["frontend", "cartservice", "recommendationservice"],
    "cost": [12.3, 7.8, 4.5]
})
st.subheader("1. GKE Cost (Last 7 days)")
st.bar_chart(cost_data.set_index("service"))

# ------------------------
# Section 2: Carbon Footprint (mocked)
# ------------------------
st.subheader("2. Carbon Footprint Data")
carbon_data = {
    "region": "us-central1",
    "co2_kg": 2.8,
    "note": "This is mock data for demo purposes."
}
st.json(carbon_data)

# ------------------------
# Section 3: Gemini Recommendation (mocked)
# ------------------------
st.subheader("3. Gemini Recommendation")
recommendation = "Consider scaling down idle services at night to save costs and reduce CO₂."
st.info(recommendation)

# ------------------------
# Section 4: Self-Healing Agent Events
# ------------------------
st.subheader("4. Self-Healing Agent Events")

DEFAULT_AGENT_URL = "http://greenops-selfheal.boutique.svc.cluster.local:8081/status"
AGENT_STATUS_URL = os.getenv("AGENT_STATUS_URL", DEFAULT_AGENT_URL)


@st.cache_data(ttl=15)
def fetch_agent_events(url: str):
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            return [data]
        if isinstance(data, list):
            return data
        return [{"message": str(data)}]
    except requests.RequestException as e:
        return {"error": f"request_error: {e}"}
    except Exception as e:
        return {"error": f"parse_error: {e}"}


events_resp = fetch_agent_events(AGENT_STATUS_URL)
if isinstance(events_resp, dict) and "error" in events_resp:
    st.warning(f"Could not reach Self-Healing Agent. {events_resp['error']}")
else:
    events = events_resp
    if events:
        if isinstance(events, list) and all(isinstance(e, dict) for e in events):
            st.table(events)
        else:
            st.json(events)
