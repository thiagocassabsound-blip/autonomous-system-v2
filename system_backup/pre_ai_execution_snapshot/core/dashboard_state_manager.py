"""
core/dashboard_state_manager.py

Lightweight state manager for the Operational Dashboard.
Reads from system persistence files to serve data quickly via an in-memory cache.
Avoids direct disk I/O on every request and provides a history logging mechanism.
Supports switching between REAL and MOCK mode.
"""

import os
import json
import time
from datetime import datetime, timezone

from infrastructure.logger import get_logger

logger = get_logger("DashboardState")

class DashboardStateManager:
    def __init__(self, cache_ttl_seconds=5.0):
        self.cache_ttl = cache_ttl_seconds
        self._mode = "REAL"  # "REAL" or "MOCK"
        
        # In-memory cache
        self._cache = {
            "global_state": {},
            "evaluations": [],
            "products": {},
            "budget": {},
            "last_updated": 0.0
        }
        
        # History log file
        self.history_file = "dashboard_metrics_history.jsonl"
        
        # Load initial
        self.refresh_cache()

    @property
    def mode(self):
        return self._mode

    def toggle_mode(self):
        """Switches between MOCK and REAL mode."""
        if self._mode == "REAL":
            self._mode = "MOCK"
        else:
            self._mode = "REAL"
        
        logger.info(f"[DashboardState] Switched mode to {self._mode}")
        self.refresh_cache(force=True)
        return self._mode

    def get_data(self):
        """Returns the current dashboard data, refreshing if cache is expired."""
        if time.time() - self._cache["last_updated"] > self.cache_ttl:
            self.refresh_cache()
        return self._cache

    def force_refresh(self):
        """Forces a cache refresh immediately and returns the new data."""
        self.refresh_cache(force=True)
        return self._cache

    def refresh_cache(self, force=False):
        """Reads from data sources to update the in-memory cache."""
        now = time.time()
        
        if self._mode == "MOCK":
            self._load_mock_data()
        else:
            self._load_real_data()

        self._cache["last_updated"] = now
        self._append_history()

    def _load_real_data(self):
        try:
            with open("global_state.json", "r", encoding="utf-8") as f:
                self._cache["global_state"] = json.load(f)
        except Exception:
            self._cache["global_state"] = {"state": "UNKNOWN"}

        try:
            evals = []
            with open("radar_evaluations.json", "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        evals.append(json.loads(line))
            self._cache["evaluations"] = evals
        except Exception:
            self._cache["evaluations"] = []

        try:
            with open("product_lifecycle_state.json", "r", encoding="utf-8") as f:
                self._cache["products"] = json.load(f)
        except Exception:
            self._cache["products"] = {}

        try:
            # Safe import of optional llm budget guard
            from infra.llm import llm_budget_guard
            self._cache["budget"] = llm_budget_guard.get_status()
        except ImportError:
            self._cache["budget"] = {}
        except Exception as e:
            logger.warning(f"[DashboardState] Could not load LLM budget: {e}")
            self._cache["budget"] = {}

    def _load_mock_data(self):
        """Loads simulated data for safe UI testing."""
        self._cache["global_state"] = {"state": "NORMAL (MOCK)"}
        self._cache["budget"] = {
            "calls_today": 42,
            "max_calls_per_day": 100,
            "cost_today_usd": 1.25,
            "max_cost_per_day_usd": 5.0
        }
        
        # Generate some mock evaluations
        now_ts = datetime.now(timezone.utc).isoformat()
        self._cache["evaluations"] = [
            {
                "product_id": f"mock-prod-{i:03d}",
                "score_final": 75.0 + i,
                "ice": "ALTO" if i % 2 == 0 else "MODERADO",
                "recommended": True,
                "timestamp": now_ts
            } for i in range(10)
        ]
        
        # Generate mock products
        self._cache["products"] = {
            f"mock-prod-{i:03d}": {
                "product_id": f"mock-prod-{i:03d}",
                "state": "Draft",
                "baseline_version": "1.0",
                "created_at": now_ts
            } for i in range(5)
        }

    def _append_history(self):
        """Append current metrics to the history log."""
        try:
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": self._mode,
                "metrics": {
                    "total_evaluations": len(self._cache["evaluations"]),
                    "total_products": len(self._cache["products"]),
                    "global_state": self._cache["global_state"].get("state", "UNKNOWN")
                }
            }
            with open(self.history_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"[DashboardState] Failed to write history: {e}")

# Global singleton instance to be shared across requests
dashboard_state = DashboardStateManager()
