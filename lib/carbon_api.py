import os
from typing import List, Dict, Any


class CarbonAPI:
    """Wrapper for a carbon footprint API.

    If `use_mock` is True, returns deterministic mock values. Real integration
    would call an external service and map costs/usage to CO2.
    """

    def __init__(self, api_key: str = None, use_mock: bool = True):
        self.api_key = api_key or os.getenv("CARBON_API_KEY")
        self.use_mock = use_mock

    def estimate_from_costs(self, costs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Estimate CO2 from cost rows. Returns a JSON-serializable dict."""
        if not costs:
            return {"total_co2_kg": 0.0, "per_service": []}

        if self.use_mock:
            per = []
            total = 0.0
            for r in costs:
                c = float(r.get("cost", 0.0))
                # simple mock: 0.2 kg CO2 per USD
                co2 = round(c * 0.2, 3)
                total += co2
                per.append({"service": r.get("service"), "date": r.get("date"), "co2_kg": co2})
            return {"total_co2_kg": round(total, 3), "per_service": per}

        # Real implementation placeholder
        # ...call external API with self.api_key...
        raise NotImplementedError("Carbon API integration not implemented")
