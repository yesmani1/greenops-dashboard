import os
from typing import List, Dict
from datetime import datetime

import pandas as pd


class BigQueryClient:
    """Minimal BigQuery client wrapper.

    This module uses the `google-cloud-bigquery` client if available; otherwise
    it falls back to a mocked dataset for local development.
    """

    def __init__(self, project: str = None):
        self.project = project or os.getenv("GCP_PROJECT")
        try:
            from google.cloud import bigquery

            self._client = bigquery.Client(project=self.project)
        except Exception:
            self._client = None

    def get_gke_costs_by_service(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return a DataFrame with columns: date, service, cost

        start_date and end_date are ISO date strings (YYYY-MM-DD)
        """
        if not self._client:
            # Return a mocked DataFrame
            dates = pd.date_range(start=start_date, end=end_date)
            services = ["frontend", "backend", "payments", "redis", "batch"]
            rows = []
            for d in dates:
                for s in services:
                    rows.append({"date": d.date().isoformat(), "service": s, "cost": round(0.5 + hash((d, s)) % 100 / 100, 2)})
            return pd.DataFrame(rows)

        # Real BigQuery path
        query = f"""
        SELECT DATE(usage_start_time) AS date, service.description AS service, SUM(cost) AS cost
        FROM `{self.project}.billing.gke_billing_export`
        WHERE DATE(usage_start_time) BETWEEN '{start_date}' AND '{end_date}'
        GROUP BY date, service
        ORDER BY date
        """
        job = self._client.query(query)
        df = job.to_dataframe()
        # Ensure columns
        if "service" not in df.columns:
            df["service"] = "unknown"
        if "cost" not in df.columns:
            df["cost"] = 0.0
        return df[["date", "service", "cost"]]
