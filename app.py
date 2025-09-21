import os
import json
from datetime import datetime, timedelta
import os
import json
from datetime import datetime, timedelta

import streamlit as st
import pandas as pd

from lib.bigquery_client import BigQueryClient
from lib.carbon_api import CarbonAPI
from lib.vertex_gen import VertexGen


st.set_page_config(page_title="GreenOps Agent", layout="wide")


def load_data():
    # Query last 7 days of GKE costs by service
    project = os.getenv("GCP_PROJECT") or "demo-project"
    bq = BigQueryClient(project=project)
    end = datetime.utcnow().date()
    start = end - timedelta(days=6)
    df = bq.get_gke_costs_by_service(start.isoformat(), end.isoformat())
    return df


def main():
    st.title("GreenOps Agent — GKE Cost & Carbon Insights")

    st.sidebar.header("Settings")
    use_mock = st.sidebar.checkbox("Use mocks for external APIs", value=True)

    st.sidebar.markdown("Environment: \n- GCP_PROJECT: `{}`".format(os.getenv("GCP_PROJECT", "demo-project")))

    with st.spinner("Querying BigQuery for costs..."):
        df = load_data()

    st.header("Costs (last 7 days)")
    if df.empty:
        st.info("No cost data returned for the selected date range.")
    else:
        st.plotly_chart(
            pd.DataFrame(df).groupby("service")["cost"].sum().sort_values(ascending=False).reset_index().pipe(
                lambda d: d.rename(columns={"service": "Service", "cost": "Total Cost USD"})
            ).set_index("Service").T.pipe(lambda d: d), use_container_width=True
        )

        st.dataframe(df)

    st.header("Carbon Footprint Estimates")
    carbon_api = CarbonAPI(use_mock=use_mock)
    with st.spinner("Estimating carbon footprint..."):
        footprint = carbon_api.estimate_from_costs(df.to_dict(orient="records"))

    st.json(footprint)

    st.header("Gemini Recommendations")
    vg = VertexGen(use_mock=use_mock)
    prompt = "Provide optimization recommendations for the following costs and carbon footprint: \n" + json.dumps({"costs": df.to_dict(orient="records"), "footprint": footprint}, indent=2)
    with st.spinner("Generating recommendations via Gemini..."):
        rec = vg.generate_recommendations(prompt)

    st.subheader("Recommendation")
    st.markdown(rec.get("recommendation_markdown", "No recommendation returned."))


if __name__ == "__main__":
    main()
