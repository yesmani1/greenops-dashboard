import os
from typing import Tuple, Optional
import pandas as pd


class BigQueryClient:
    """Minimal BigQuery client wrapper.

    Methods:
      - get_gke_costs_by_service(start_date, end_date) -> pd.DataFrame
      - test_table_connection() -> (bool, message)

    Use `use_live=True` to run real BigQuery queries. In mock mode the client
    returns deterministic synthetic data and `test_table_connection` returns OK.
    """

    def __init__(self, project: Optional[str] = None, use_live: bool = False, table: Optional[str] = None):
        self.project = project or os.getenv("GCP_PROJECT")
        self.table = table or os.getenv("BQ_TABLE")
        self.use_live = use_live
        self._client = None

        if self.use_live:
            try:
                from google.cloud import bigquery

                self._client = bigquery.Client(project=self.project)
            except Exception as e:
                raise RuntimeError(f"BigQuery client initialization failed: {e}")

    def get_gke_costs_by_service(self, start_date: str, end_date: str) -> pd.DataFrame:
        """Return a DataFrame with columns (date, service, cost).

        In mock mode returns a small synthetic DataFrame covering the date range.
        In live mode performs an aggregation against the configured table.
        """
        if not self.use_live:
            dates = pd.date_range(start=start_date, end=end_date)
            services = ["frontend", "backend", "payments", "redis", "batch"]
            rows = []
            for d in dates:
                for s in services:
                    rows.append({
                        "date": d.date().isoformat(),
                        "service": s,
                        "cost": round(0.5 + (hash((d, s)) % 100) / 100, 2),
                    })
            return pd.DataFrame(rows)

        if not self._client:
            raise RuntimeError("BigQuery client not initialized. Ensure google-cloud-bigquery is installed and credentials are available.")

        table_ref = self.table or f"{self.project}.billing.gke_billing_export"
        query = (
            "SELECT DATE(usage_start_time) AS date, service.description AS service, SUM(cost) AS cost "
            + f"FROM `{table_ref}` "
            + f"WHERE DATE(usage_start_time) BETWEEN '{start_date}' AND '{end_date}' "
            + "GROUP BY date, service "
            + "ORDER BY date"
        )

        try:
            job = self._client.query(query)
            df = job.to_dataframe()
        except Exception as e:
            raise RuntimeError(f"BigQuery query failed: {e}. Check APIs/permissions/table path.")

        # Ensure required columns
        if "service" not in df.columns:
            df["service"] = "unknown"
        if "cost" not in df.columns:
            df["cost"] = 0.0

        return df[["date", "service", "cost"]]

    def test_table_connection(self) -> Tuple[bool, str]:
        """Run a lightweight connectivity check against the configured table.

        Returns (success, message). For mock mode returns success immediately.
        """
        if not self.use_live:
            return True, "Client configured for mock mode (use_live=False) — no live check performed."

        if not self._client:
            return False, "BigQuery client not initialized"

        table_ref = self.table or f"{self.project}.billing.gke_billing_export"
        query = f"SELECT COUNT(1) AS cnt FROM `{table_ref}` LIMIT 1"
        try:
            job = self._client.query(query)
            df = job.to_dataframe()
            cnt = int(df.iloc[0]["cnt"]) if not df.empty else 0
            return True, f"OK, table accessible (sample rows: {cnt})"
        except Exception as e:
            return False, str(e)
import os
from typing import Tuple
import pandas as pd


class BigQueryClient:
    """Minimal BigQuery client wrapper.

    Use `use_live=True` to attempt real BigQuery queries. Provide `table` to
    query a specific table (e.g. billing export or mock dataset).
    """

    def __init__(self, project: str = None, use_live: bool = False, table: str = None):
        import os
        from typing import Tuple, Optional
        import pandas as pd


        class BigQueryClient:
            """Minimal BigQuery client wrapper.

            When `use_live` is False the client returns a small mocked DataFrame.
            """

            def __init__(self, project: Optional[str] = None, use_live: bool = False, table: Optional[str] = None):
                self.project = project or os.getenv("GCP_PROJECT")
                # Allow explicit table override or fall back to env var BQ_TABLE
                self.table = table or os.getenv("BQ_TABLE")
                self.use_live = use_live
                self._client = None
                if use_live:
                    try:
                        from google.cloud import bigquery  # imported only when needed

                        self._client = bigquery.Client(project=self.project)
                    except Exception as e:
                        # Keep initialization lazy-failing so callers can present helpful UI
                        raise RuntimeError(f"BigQuery client initialization failed: {e}")

            def get_gke_costs_by_service(self, start_date: str, end_date: str) -> pd.DataFrame:
                """Return a DataFrame with columns: date, service, cost.

                For local/debug (use_live=False) this returns synthetic data. For live
                mode this runs a BigQuery aggregation against the configured table.
                """
                if not self.use_live:
                    dates = pd.date_range(start=start_date, end=end_date)
                    services = ["frontend", "backend", "payments", "redis", "batch"]
                    rows = []
                    for d in dates:
                        for s in services:
                            rows.append({
                                "date": d.date().isoformat(),
                                "service": s,
                                "cost": round(0.5 + (hash((d, s)) % 100) / 100, 2),
                            })
                    return pd.DataFrame(rows)

                if not self._client:
                    raise RuntimeError("BigQuery client not initialized. Ensure the BigQuery SDK is installed and credentials are available.")

                table_ref = self.table or f"{self.project}.billing.gke_billing_export"
                query = (
                    "SELECT DATE(usage_start_time) AS date, service.description AS service, SUM(cost) AS cost "
                    + f"FROM `{table_ref}` "
                    + f"WHERE DATE(usage_start_time) BETWEEN '{start_date}' AND '{end_date}' "
                    + "GROUP BY date, service "
                    + "ORDER BY date"
                )

                try:
                    job = self._client.query(query)
                    df = job.to_dataframe()
                except Exception as e:
                    raise RuntimeError(
                        f"BigQuery query failed: {e}. Check that BigQuery API is enabled for project '{self.project}' and that the billing export table path is correct."
                    )

                # Normalize columns if BigQuery returns unexpected schema
                if "service" not in df.columns:
                    df["service"] = "unknown"
                if "cost" not in df.columns:
                    df["cost"] = 0.0
                import os
                from typing import Tuple, Optional
                import pandas as pd


                class BigQueryClient:
                    """Minimal BigQuery client wrapper.

                    When `use_live` is False the client returns a small mocked DataFrame.
                    """

                    def __init__(self, project: Optional[str] = None, use_live: bool = False, table: Optional[str] = None):
                        self.project = project or os.getenv("GCP_PROJECT")
                        # Allow explicit table override or fall back to env var BQ_TABLE
                        self.table = table or os.getenv("BQ_TABLE")
                        self.use_live = use_live
                        self._client = None
                        if use_live:
                            try:
                                from google.cloud import bigquery  # imported only when needed

                                self._client = bigquery.Client(project=self.project)
                            except Exception as e:
                                # Keep initialization lazy-failing so callers can present helpful UI
                                raise RuntimeError(f"BigQuery client initialization failed: {e}")

                    def get_gke_costs_by_service(self, start_date: str, end_date: str) -> pd.DataFrame:
                        """Return a DataFrame with columns: date, service, cost.

                        For local/debug (use_live=False) this returns synthetic data. For live
                        mode this runs a BigQuery aggregation against the configured table.
                        """
                        if not self.use_live:
                            dates = pd.date_range(start=start_date, end=end_date)
                            services = ["frontend", "backend", "payments", "redis", "batch"]
                            rows = []
                            for d in dates:
                                for s in services:
                                    rows.append({
                                        "date": d.date().isoformat(),
                                        "service": s,
                                        "cost": round(0.5 + (hash((d, s)) % 100) / 100, 2),
                                    })
                            return pd.DataFrame(rows)

                        if not self._client:
                            raise RuntimeError("BigQuery client not initialized. Ensure the BigQuery SDK is installed and credentials are available.")

                        table_ref = self.table or f"{self.project}.billing.gke_billing_export"
                        query = (
                            "SELECT DATE(usage_start_time) AS date, service.description AS service, SUM(cost) AS cost "
                            + f"FROM `{table_ref}` "
                            + f"WHERE DATE(usage_start_time) BETWEEN '{start_date}' AND '{end_date}' "
                            + "GROUP BY date, service "
                            + "ORDER BY date"
                        )

                        try:
                            job = self._client.query(query)
                            df = job.to_dataframe()
                        except Exception as e:
                            raise RuntimeError(
                                f"BigQuery query failed: {e}. Check that BigQuery API is enabled for project '{self.project}' and that the billing export table path is correct."
                            )

                        # Normalize columns if BigQuery returns unexpected schema
                        if "service" not in df.columns:
                            df["service"] = "unknown"
                        if "cost" not in df.columns:
                            df["cost"] = 0.0
                        return df[["date", "service", "cost"]]

                    def test_table_connection(self) -> Tuple[bool, str]:
                        """Run a lightweight connectivity check against the configured table.

                        Returns (success, message). In mock mode this returns success without
                        querying BigQuery.
                        """
                        if not self.use_live:
                            return True, "Client configured for mock mode (use_live=False) — no live check performed."
                        if not self._client:
                            return False, "BigQuery client not initialized"

                        table_ref = self.table or f"{self.project}.billing.gke_billing_export"
                        query = f"SELECT COUNT(1) AS cnt FROM `{table_ref}` LIMIT 1"
                        try:
                            job = self._client.query(query)
                            df = job.to_dataframe()
                            cnt = int(df.iloc[0]["cnt"]) if not df.empty else 0
                            return True, f"OK, table accessible (sample rows: {cnt})"
                        except Exception as e:
                            return False, str(e)
