import os
from typing import List, Dict
from datetime import datetime

import pandas as pd


class BigQueryClient:
    """Minimal BigQuery client wrapper.

    Use `use_live=True` to attempt real BigQuery queries. If the BigQuery SDK
    or credentials are unavailable, the client will raise an informative
    exception so the caller can show instructions to the user.
    """

    def __init__(self, project: str = None, use_live: bool = False):
        self.project = project or os.getenv("GCP_PROJECT")
        self.use_live = use_live
        self._client = None
        if use_live:
            try:
                from google.cloud import bigquery

                self._client = bigquery.Client(project=self.project)
            except Exception as e:
                # Keep the exception for higher-level handling
                raise RuntimeError(
                    "BigQuery client initialization failed: {}".format(e)
                )

    def get_gke_costs_by_service(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return a DataFrame with columns: date, service, cost.

        If `use_live` was set but the query fails, raise a RuntimeError with a
        helpful message that downstream code (the Streamlit app) can show.
        """
        if not self.use_live:
            # Return a mocked DataFrame for local development/test
            dates = pd.date_range(start=start_date, end=end_date)
            services = ["frontend", "backend", "payments", "redis", "batch"]
            rows = []
            for d in dates:
                for s in services:
                    rows.append({
                        "date": d.date().isoformat(),
                        "service": s,
                        "cost": round(0.5 + hash((d, s)) % 100 / 100, 2),
                    })
            return pd.DataFrame(rows)

        # Use the BigQuery client for live data
        if not self._client:
            raise RuntimeError(
                "BigQuery client not initialized. Ensure the BigQuery SDK is installed and credentials are available."
            )

        query = f"""
        SELECT DATE(usage_start_time) AS date, service.description AS service, SUM(cost) AS cost
        FROM `{self.project}.billing.gke_billing_export`
        WHERE DATE(usage_start_time) BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY date, service
        ORDER BY date
        """

        try:
            job = self._client.query(query)
            df = job.to_dataframe()
        except Exception as e:
            # Provide a helpful error message upstream
            raise RuntimeError(
                "BigQuery query failed: {}. Check that BigQuery API is enabled for project '{}' and that the billing export table path is correct.".format(
                    e, self.project
                )
            )

        # Ensure columns
        if "service" not in df.columns:
            df["service"] = "unknown"
        if "cost" not in df.columns:
            df["cost"] = 0.0
        return df[["date", "service", "cost"]]
