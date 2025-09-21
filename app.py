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
    project = os.getenv("GCP_PROJECT") or "autogreenops"
    # The app will pass use_live when constructing the BigQuery client; default False
    bq = BigQueryClient(project=project)
    end = datetime.utcnow().date()
    start = end - timedelta(days=6)
    df = bq.get_gke_costs_by_service(start.isoformat(), end.isoformat())
    return df


def main():
    st.title("GreenOps Agent — GKE Cost & Carbon Insights")

    st.sidebar.header("Settings")
    data_source = st.sidebar.selectbox(
        "Data source",
        [
            "BigQuery mock dataset",
            "BigQuery live dataset",
        ],
        index=0,
    )

    # Show active project
    active_project = os.getenv("GCP_PROJECT") or "autogreenops"
    st.sidebar.markdown("Environment: \n- GCP_PROJECT: `{}`".format(active_project))

    # Table env overrides
    live_table = os.getenv("LIVE_BQ_TABLE") or "autogreenops.billing_dataset.gcp_billing_export_resource_v1_018317_83DA9C_15D7B1"
    mock_table = os.getenv("MOCK_BQ_TABLE") or "autogreenops.billing_dataset.mock_billing_data"

    st.sidebar.markdown(f"Selected data source: **{data_source}**")

    # Test connection button
    if st.sidebar.button("Test connection"):
        try:
            if data_source == "BigQuery live dataset":
                bq_test = BigQueryClient(project=active_project, use_live=True, table=live_table)
            else:
                bq_test = BigQueryClient(project=active_project, use_live=True, table=mock_table)
            ok, msg = bq_test.test_table_connection()
            if ok:
                st.sidebar.success("Connection OK: " + msg)
            else:
                st.sidebar.error("Connection failed: " + msg)
        except Exception as e:
            st.sidebar.error(f"Connection test error: {e}")

    with st.spinner("Querying BigQuery for costs..."):
        try:
            end = datetime.utcnow().date()
            start = end - timedelta(days=6)
            if data_source == "BigQuery mock dataset":
                bq = BigQueryClient(project=active_project, use_live=True, table=mock_table)
                df = bq.get_gke_costs_by_service(start.isoformat(), end.isoformat())
            else:
                bq = BigQueryClient(project=active_project, use_live=True, table=live_table)
                df = bq.get_gke_costs_by_service(start.isoformat(), end.isoformat())
        except Exception as e:
            st.error(
                f"BigQuery fetch failed: {e}\n\nIf you intended to use live data, make sure:\n"
                "1) BigQuery API is enabled for your project.\n"
                "2) The billing export table exists and the table path is correct.\n"
                "3) The service account running this app has permission to read BigQuery.\n"
                "4) For Cloud Run/Compute, provide credentials via Workload Identity or set GOOGLE_APPLICATION_CREDENTIALS.\n\n"
            )
            st.exception(e)
            df = None

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
    carbon_api = CarbonAPI(use_mock=(data_source == "BigQuery mock dataset"))
    with st.spinner("Estimating carbon footprint..."):
        footprint = carbon_api.estimate_from_costs(df.to_dict(orient="records"))

    st.json(footprint)

    st.header("Gemini Recommendations")
    vg = VertexGen(use_mock=(data_source == "BigQuery mock dataset"))
    prompt = "Provide optimization recommendations for the following costs and carbon footprint: \n" + json.dumps({"costs": df.to_dict(orient="records"), "footprint": footprint}, indent=2)
    with st.spinner("Generating recommendations via Gemini..."):
        rec = vg.generate_recommendations(prompt)

    st.subheader("Recommendation")
    st.markdown(rec.get("recommendation_markdown", "No recommendation returned."))


if __name__ == "__main__":
    main()
