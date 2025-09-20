import streamlit as st
import pandas as pd
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

agent_url = "http://greenops-selfheal.boutique.svc.cluster.local:8081/status"

try:
    response = requests.get(agent_url, timeout=5)
    if response.status_code == 200:
        events = response.json()
        if events:
            st.table(events)
        else:
            st.write("✅ No healing events yet.")
    else:
        st.error(f"Agent returned status: {response.status_code}")
except Exception as e:
    st.warning(f"Could not reach Self-Healing Agent. Error: {e}")
