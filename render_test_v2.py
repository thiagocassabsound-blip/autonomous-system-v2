
import os
import json
import time
from datetime import datetime, timezone
from jinja2 import Environment, FileSystemLoader

# Mock DashboardStateManager logic
PROJECT_ROOT = os.getcwd()
PERSISTENCE_DIR = PROJECT_ROOT

class MockState:
    def __init__(self, mode="REAL"):
        self.mode = mode
        self.cache = {
            "global_state": {"state": "NORMAL (TEST)"},
            "evaluations":  [
                {"timestamp": "2026-03-10T09:00:00Z", "product_id": "p1", "ice": "ALTO", "score_final": 0.85, "recommended": True}
            ],
            "products":     {"p1": {"product_id": "p1", "created_at": "2026-03-10T08:00:00Z"}},
            "budget":       {"calls_today": 10, "max_calls_per_day": 50, "cost_today_usd": 0.50},
            "commercial":   {},
            "last_updated": time.time()
        }
    def get_data(self): return self.cache

mock_state = MockState()

def _get_base_context(data):
    """Mirroring api/routes/dashboard_routes.py helper."""
    last_ts = data.get("last_updated", 0)
    last_updated_str = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    budget = data.get("budget", {})
    evals_list = data.get("evaluations", [])
    products_raw = data.get("products", {})
    
    total_evals = len(evals_list)
    total_drafts = len(products_raw) if isinstance(products_raw, dict) else 0

    return {
        "system_status": data.get("global_state", {}).get("state", "UNKNOWN"),
        "mode": mock_state.mode,
        "username": "tester",
        "last_updated": last_updated_str,
        "total_evals": total_evals,
        "total_drafts": total_drafts,
        "budget_calls": budget.get("calls_today", 0),
        "budget_max": budget.get("max_calls_per_day", 100),
        "budget_cost": f"{float(budget.get('cost_today_usd', 0.0)):.2f}",
        "error_alerts": []
    }

def render_all():
    env = Environment(loader=FileSystemLoader('templates'))
    template = env.get_template('dashboard.html')
    data = mock_state.get_data()
    
    sections = [
        {"name": "Overview", "ctx": {"section": "overview", "evals": list(reversed(data["evaluations"][-10:])), "products": list(data["products"].values())[:10]}},
        {"name": "Radar", "ctx": {"section": "radar", "evals": data["evaluations"]}},
        {"name": "Opportunities", "ctx": {"section": "opportunities", "recommendations": [e for e in data["evaluations"] if e.get("recommended")]}}
    ]

    for sec in sections:
        print(f"Testing section: {sec['name']}...")
        context = {**_get_base_context(data), **sec["ctx"]}
        try:
            template.render(**context)
            print(f"  SUCCESS: {sec['name']} rendered.")
        except Exception as e:
            print(f"  FAILED: {sec['name']} error: {e}")
            raise

if __name__ == "__main__":
    render_all()
