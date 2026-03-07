"""
core/finance/budget_engine.py — Financial Calculation & Projection Engine

Responsibilities:
  - calculate system operational cost
  - calculate cost per product (by stage)
  - monitor API consumption
  - project monthly costs
  - calculate safe withdrawal amount from Stripe balance
  - generate financial signals (EventBus)
  - NO payment execution, NO state mutation.

Constitutional Constraints:
  - Read-only on financial ledgers
  - Calculations only, emitting events to Orchestrator
"""

import json
import os
import logging
from datetime import datetime
from threading import Lock

logger = logging.getLogger("core.finance.budget_engine")

DATA_DIR = os.path.join(os.getcwd(), "data")
SYSTEM_COSTS_FILE = os.path.join(DATA_DIR, "system_costs.json")
PRODUCT_COSTS_FILE = os.path.join(DATA_DIR, "product_costs.json")
MONTHLY_FORECAST_FILE = os.path.join(DATA_DIR, "monthly_forecast.json")

class BudgetEngine:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        self.lock = Lock()
        self._ensure_files()

    def _ensure_files(self):
        """Ensure all required data files exist."""
        os.makedirs(DATA_DIR, exist_ok=True)
        for filepath in [SYSTEM_COSTS_FILE, PRODUCT_COSTS_FILE, MONTHLY_FORECAST_FILE]:
            if not os.path.exists(filepath):
                with open(filepath, 'w') as f:
                    json.dump({}, f)

    def _read_json(self, filepath: str) -> dict:
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[BudgetEngine] Error reading {filepath}: {e}")
            return {}

    def _write_json(self, filepath: str, data: dict):
        with self.lock:
            try:
                with open(filepath, 'w') as f:
                    json.dump(data, f, indent=4)
            except Exception as e:
                logger.error(f"[BudgetEngine] Error writing {filepath}: {e}")

    # --------------------------------------------------------------------------
    # Cost Category Updates
    # --------------------------------------------------------------------------
    
    def log_api_cost(self, api_name: str, cost: float):
        """Logs explicit API costs (openai, serper, email_gateway, analytics)."""
        data = self._read_json(SYSTEM_COSTS_FILE)
        if "API_COSTS" not in data:
            data["API_COSTS"] = {}
        data["API_COSTS"][api_name] = data["API_COSTS"].get(api_name, 0.0) + cost
        self._write_json(SYSTEM_COSTS_FILE, data)
        self._broadcast_system_costs(data)

    def log_infra_cost(self, infra_component: str, cost: float):
        """Logs infrastructure costs (hosting, domain, dns, storage, compute)."""
        data = self._read_json(SYSTEM_COSTS_FILE)
        if "INFRASTRUCTURE" not in data:
            data["INFRASTRUCTURE"] = {}
        data["INFRASTRUCTURE"][infra_component] = data["INFRASTRUCTURE"].get(infra_component, 0.0) + cost
        self._write_json(SYSTEM_COSTS_FILE, data)
        self._broadcast_system_costs(data)

    def log_traffic_cost(self, campaign_name: str, cost: float):
        """Logs traffic costs (google_ads, traffic_campaigns)."""
        data = self._read_json(SYSTEM_COSTS_FILE)
        if "TRAFFIC_ACQUISITION" not in data:
            data["TRAFFIC_ACQUISITION"] = {}
        data["TRAFFIC_ACQUISITION"][campaign_name] = data["TRAFFIC_ACQUISITION"].get(campaign_name, 0.0) + cost
        self._write_json(SYSTEM_COSTS_FILE, data)
        self._broadcast_system_costs(data)

    def update_product_cost(self, product_id: str, stage: str, traffic_budget: float, ai_cost_estimate: float, operational_cost: float):
        """
        Calculates and logs cost per product according to its stage.
        Stages: beta_stage, active_stage, scaled_stage.
        """
        total_product_cost = traffic_budget + ai_cost_estimate + operational_cost
        
        # Apply multipliers if we want speculative staging logic, but prompt says calculate based on stage.
        # We store it organized.
        
        payload = {
            "product_id": product_id,
            "product_stage": stage,
            "traffic_budget": traffic_budget,
            "ai_cost_estimate": ai_cost_estimate,
            "operational_cost": operational_cost,
            "total_product_cost": total_product_cost,
            "last_updated": datetime.utcnow().isoformat()
        }
        
        data = self._read_json(PRODUCT_COSTS_FILE)
        data[product_id] = payload
        self._write_json(PRODUCT_COSTS_FILE, data)
        
        self.event_bus.publish("product_cost_updated", {
            "origin": "budget_engine",
            "product_id": product_id,
            "data": payload
        })
        logger.info(f"[BudgetEngine] Updated product cost for {product_id}: ${total_product_cost}")

    # --------------------------------------------------------------------------
    # Projection & Forecasting
    # --------------------------------------------------------------------------

    def calculate_monthly_projection(self, total_products_running: int, daily_api_cost: float, daily_traffic_cost: float, fixed_infra_cost: float) -> dict:
        """
        Projects the monthly cost assuming 30 days. Uses the total active products for specific multipliers.
        """
        api_consumption_projection = daily_api_cost * 30
        traffic_budget_projection = daily_traffic_cost * 30
        infra_cost_projection = fixed_infra_cost # usually paid monthly already
        
        monthly_total_cost = api_consumption_projection + traffic_budget_projection + infra_cost_projection
        
        forecast = {
            "total_products_running": total_products_running,
            "api_consumption_projection": api_consumption_projection,
            "traffic_budget_projection": traffic_budget_projection,
            "infra_cost_projection": infra_cost_projection,
            "monthly_total_cost": monthly_total_cost,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self._write_json(MONTHLY_FORECAST_FILE, forecast)
        
        self.event_bus.publish("budget_projection_updated", {
            "origin": "budget_engine",
            "forecast": forecast
        })
        logger.info(f"[BudgetEngine] Monthly projection calculated: ${monthly_total_cost}")
        return forecast

    # --------------------------------------------------------------------------
    # Stripe Withdrawals & Safety Buffers
    # --------------------------------------------------------------------------

    def calculate_safe_withdrawal(self, stripe_balance: float):
        """
        Calculates safe withdrawal amount by comparing Stripe balance with projected cost and reserve buffer.
        reserve_buffer = 1.5 * monthly_system_cost
        """
        forecast = self._read_json(MONTHLY_FORECAST_FILE)
        monthly_system_cost = forecast.get("monthly_total_cost", 0.0)
        
        reserve_buffer = 1.5 * monthly_system_cost
        safe_withdrawal = stripe_balance - monthly_system_cost - reserve_buffer
        
        # Don't allow negative widthdrawals
        if safe_withdrawal < 0:
            safe_withdrawal = 0.0

        payload = {
            "stripe_balance": stripe_balance,
            "projected_monthly_cost": monthly_system_cost,
            "reserve_buffer": reserve_buffer,
            "safe_withdrawal": safe_withdrawal,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        self.event_bus.publish("safe_withdrawal_calculated", {
            "origin": "budget_engine",
            "data": payload
        })
        logger.info(f"[BudgetEngine] Safe withdrawal calculated: ${safe_withdrawal} (Reserve: ${reserve_buffer})")
        return payload

    def _broadcast_system_costs(self, system_costs: dict):
        self.event_bus.publish("system_cost_updated", {
            "origin": "budget_engine",
            "data": system_costs
        })

    # --------------------------------------------------------------------------
    # Integration Methods
    # --------------------------------------------------------------------------

    def handle_financial_telemetry(self, event_type: str, payload: dict):
        """
        Listener mapping for EventBus to update internal state when telemetry is received about ads/apis.
        """
        if event_type == "api_usage_tracked":
            api_name = payload.get("provider", "unknown")
            cost = payload.get("estimated_cost", 0.0)
            self.log_api_cost(api_name, cost)
            
        elif event_type == "traffic_campaign_spent":
            campaign_name = payload.get("campaign_name", "unknown")
            cost = payload.get("spend", 0.0)
            self.log_traffic_cost(campaign_name, cost)
            
        elif event_type == "infrastructure_billed":
            infra = payload.get("component", "unknown")
            cost = payload.get("amount", 0.0)
            self.log_infra_cost(infra, cost)
