import os
import json

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

STATE_FILE = os.path.join(DATA_DIR, "state.json")
RADAR_FILE = os.path.join(DATA_DIR, "radar_snapshots.jsonl")
TELEMETRY_FILE = os.path.join(DATA_DIR, "telemetry_accumulators.json")
STRATEGY_FILE = os.path.join(DATA_DIR, "strategy_memory.json")
MONTHLY_FORECAST_FILE = os.path.join(DATA_DIR, "monthly_forecast.json")
SYSTEM_COSTS_FILE = os.path.join(DATA_DIR, "system_costs.json")
PRODUCT_COSTS_FILE = os.path.join(DATA_DIR, "product_costs.json")
RUNTIME_LOG_FILE = os.path.join(LOGS_DIR, "runtime_events.log")
SERVICE_ACCOUNTS_FILE = os.path.join(BASE_DIR, "system_registry", "service_accounts_registry.json")

def _read_json(filepath, default):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default

def _read_jsonl_last_lines(filepath, num_lines=50):
    if not os.path.exists(filepath):
        return []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            return [json.loads(line) for line in lines[-num_lines:] if line.strip()]
    except Exception:
        return []

class DashboardStateStore:
    """
    Read-only aggregation layer for the dashboard.
    Never mutates system state or ledgers.
    """
    
    @staticmethod
    def get_system_overview():
        state = _read_json(STATE_FILE, {})
        radar_lines = _read_jsonl_last_lines(RADAR_FILE, 10)
        
        products = state.get("products", {})
        active_products = sum(1 for p in products.values() if p.get("lifecycle_state") == "active")
        
        # Landings could be inferred from products having landing_url
        active_landings = sum(1 for p in products.values() if p.get("landing_url"))
        
        # Radar opportunities is total opportunities in the last snapshot
        radar_opps = 0
        if radar_lines:
            last_snapshot = radar_lines[-1]
            radar_opps = len(last_snapshot.get("items", []))
            
        return {
            "products_active": active_products,
            "landings_active": active_landings,
            "radar_opportunities": radar_opps,
            "system_status": "ONLINE",
            "dry_run_mode": True # Governed architecture runs strictly under this guard
        }
        
    @staticmethod
    def get_radar_opportunities():
        radar_lines = _read_jsonl_last_lines(RADAR_FILE, 10)
        if not radar_lines:
            return {"latest_snapshot_id": None, "opportunities": []}
            
        last_snapshot = radar_lines[-1]
        
        return {
            "latest_snapshot_id": last_snapshot.get("timestamp"),
            "opportunities": last_snapshot.get("items", [])
        }
        
    @staticmethod
    def get_products():
        state = _read_json(STATE_FILE, {})
        products = state.get("products", {})
        
        return list(products.values())
        
    @staticmethod
    def get_landings():
        state = _read_json(STATE_FILE, {})
        products = state.get("products", {})
        
        landings = []
        for p_id, p in products.items():
            if p.get("landing_url"):
                landings.append({
                    "product_id": p_id,
                    "name": p.get("generated_copy", {}).get("name", "Unknown"),
                    "landing_url": p.get("landing_url"),
                    "status": "LIVE"
                })
        return landings
        
    @staticmethod
    def get_traffic_metrics():
        telemetry = _read_json(TELEMETRY_FILE, {})
        return telemetry.get("traffic", {})
        
    @staticmethod
    def get_revenue_metrics():
        telemetry = _read_json(TELEMETRY_FILE, {})
        return telemetry.get("financial", {})

    @staticmethod
    def get_intelligence_signals():
        strategy = _read_json(STRATEGY_FILE, {})
        # Flatten strategy points to a timeline
        timeline = []
        for key, arr in strategy.items():
            if isinstance(arr, list):
                for item in arr:
                    item['_category'] = key
                    timeline.append(item)
                    
        # Sort by timestamp desc
        timeline.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return timeline[:50]

    @staticmethod
    def get_finance_overview():
        forecast = _read_json(MONTHLY_FORECAST_FILE, {})
        system_costs = _read_json(SYSTEM_COSTS_FILE, {})
        product_costs = _read_json(PRODUCT_COSTS_FILE, {})
        
        telemetry = _read_json(TELEMETRY_FILE, {})
        financial = telemetry.get("financial", {})
        
        stripe_balance = financial.get("total_mrr", 0.0) # Using MRR as a dummy balance if none natively exists
        monthly_system_cost = forecast.get("monthly_total_cost", 0.0)
        reserve_buffer = 1.5 * monthly_system_cost
        safe_withdrawal = max(0.0, stripe_balance - monthly_system_cost - reserve_buffer)
        
        return {
            "stripe_balance": stripe_balance,
            "projected_monthly_cost": monthly_system_cost,
            "api_costs": system_costs.get("API_COSTS", {}),
            "traffic_budget": forecast.get("traffic_budget_projection", 0.0),
            "product_cost_breakdown": product_costs,
            "safe_withdrawal": safe_withdrawal
        }

    @staticmethod
    def get_infrastructure_health():
        events = _read_jsonl_last_lines(RUNTIME_LOG_FILE, 200)
        
        infra = {
            "domain": {"status": "UNKNOWN", "details": ""},
            "dns": {"status": "UNKNOWN", "details": ""},
            "ssl": {"status": "UNKNOWN", "details": ""},
            "hosting": {"status": "UNKNOWN", "details": ""},
            "billing": {"status": "UNKNOWN", "details": ""}
        }
        
        for ev in events:
            ev_type = ev.get("event_type", "")
            payload = ev.get("payload", {})
            
            if ev_type.startswith("domain_"):
                if "ok" in ev_type:
                    infra["domain"] = {"status": "OK", "details": f"expires in: {payload.get('days_remaining', 'N/A')} days"}
                else:
                    infra["domain"] = {"status": "WARNING", "details": ev_type}
            elif ev_type.startswith("dns_"):
                if "ok" in ev_type:
                    infra["dns"] = {"status": "OK", "details": "resolved"}
                else:
                    infra["dns"] = {"status": "ERROR", "details": ev_type}
            elif ev_type.startswith("ssl_"):
                if "valid" in ev_type:
                    infra["ssl"] = {"status": "OK", "details": f"expires in: {payload.get('days_remaining', 'N/A')} days"}
                else:
                    infra["ssl"] = {"status": "WARNING", "details": ev_type}
            elif ev_type.startswith("hosting_"):
                if "ok" in ev_type:
                    infra["hosting"] = {"status": "OK", "details": "healthy"}
                else:
                    infra["hosting"] = {"status": "ERROR", "details": ev_type}
            elif ev_type.startswith("billing_"):
                if "ok" in ev_type:
                    infra["billing"] = {"status": "OK", "details": f"next renewal: {payload.get('next_renewal_days', 'N/A')} days"}
                else:
                    infra["billing"] = {"status": "WARNING", "details": ev_type}
                    
        return infra

    @staticmethod
    def get_system_health():
        # Radar Status
        radar_lines = _read_jsonl_last_lines(RADAR_FILE, 10)
        radar_opps = len(radar_lines[-1].get("items", [])) if radar_lines else 0
        radar_status = "OK" if radar_opps >= 10 else ("LOW" if radar_opps > 0 else "WARNING")

        # Product Pipeline Status
        state = _read_json(STATE_FILE, {})
        active_products = sum(1 for p in state.get("products", {}).values() if p.get("lifecycle_state") == "active")
        product_status = "OK" if active_products > 0 else "WARNING"

        # Traffic & Conversion & Revenue Status
        telemetry = _read_json(TELEMETRY_FILE, {})
        t = telemetry.get("traffic", {})
        f = telemetry.get("financial", {})

        traffic_status = "OK" if t.get("total_visitors", 0) > 100 else ("LOW" if t.get("total_visitors", 0) > 0 else "WARNING")
        conv_status = "OK" if t.get("avg_conversion_rate", 0) >= 2.0 else ("LOW" if t.get("avg_conversion_rate", 0) > 0 else "WARNING")
        rev_status = "OK" if f.get("total_mrr", 0) > 0 else "WARNING"

        return {
            "radar_status": radar_status,
            "product_status": product_status,
            "traffic_status": traffic_status,
            "conversion_status": conv_status,
            "revenue_status": rev_status,
            "alerts": {
                "radar_drop": radar_status != "OK",
                "traffic_drop": traffic_status != "OK",
                "conversion_drop": conv_status != "OK",
                "revenue_anomaly": rev_status != "OK"
            }
        }

    @staticmethod
    def get_evolution():
        strategy = _read_json(STRATEGY_FILE, {})
        return {
            "winning_patterns": strategy.get("winning_copy_patterns", []) + strategy.get("seo_keyword_patterns", []),
            "failed_products": strategy.get("failed_products", []),
            "strategy_insights": strategy.get("buyer_segments", []) + strategy.get("pricing_patterns", [])
        }
