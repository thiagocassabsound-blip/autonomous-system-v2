"""
core/dashboard_state_manager.py

Operational Dashboard State Manager.
Definitive Clean Build & Key Alignment (FASE C6.11).
Deterministic, 100% anchored paths, aligned keys for dashboard compatibility.
"""

import os
import json
import time
from datetime import datetime, timezone

from infrastructure.logger import get_logger

logger = get_logger("DashboardState")

# Dynamic Project Root Resolution
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..")
)
PERSISTENCE_DIR = PROJECT_ROOT

class DashboardStateManager:
    """
    Manages the operational dashboard state with an in-memory caching layer.
    Strictly uses absolute anchored paths for all persistence operations.
    """

    def __init__(self, cache_ttl_seconds: float = 5.0):
        self.cache_ttl = cache_ttl_seconds
        self._mode = "REAL"  # Supported: "REAL" or "MOCK"
        
        # Centralized persistence paths (strictly anchored)
        self.paths = {
            "global_state":      os.path.join(PERSISTENCE_DIR, "global_state.json"),
            "radar_evaluations": os.path.join(PERSISTENCE_DIR, "radar_evaluations.json"),
            "product_lifecycle": os.path.join(PERSISTENCE_DIR, "product_lifecycle_state.json"),
            "finance_state":     os.path.join(PERSISTENCE_DIR, "finance_state.json"),
            "commercial_state":  os.path.join(PERSISTENCE_DIR, "commercial_state.json"),
            "history_log":       os.path.join(PERSISTENCE_DIR, "dashboard_metrics_history.jsonl")
        }

        # In-memory cache initialization with unique keys
        self._cache = {
            "global_state": {},
            "evaluations":  [],
            "products":     {},
            "budget":       {},
            "commercial":   {},
            "last_updated": 0.0
        }

        # Trigger initial cache loading
        self.refresh_cache()

    @property
    def mode(self) -> str:
        """Returns the current operational mode (REAL/MOCK)."""
        return self._mode

    def toggle_mode(self, target: str = None) -> str:
        """
        Toggles operational mode (or sets to target) and forces a cache refresh.
        target: Optional "REAL" or "MOCK".
        """
        if target in ["REAL", "MOCK"]:
            self._mode = target
        else:
            self._mode = "MOCK" if self._mode == "REAL" else "REAL"
            
        logger.info(f"[DashboardState] Operational mode set to: {self._mode}")
        self.refresh_cache(force=True)
        return self._mode

    def get_data(self) -> dict:
        """Retrieves cached data, auto-refreshing if TTL has expired."""
        if time.time() - self._cache["last_updated"] > self.cache_ttl:
            self.refresh_cache()
        return self._cache

    def refresh_cache(self, force: bool = False):
        """Synchronizes the in-memory cache with the active data source."""
        if self._mode == "MOCK":
            self._load_mock_data()
        else:
            self._load_real_data()

        self._cache["last_updated"] = time.time()
        self._log_history()

    def _load_real_data(self):
        """
        Loads data from absolute anchored persistence files.
        Aligns keys with dashboard expectations (state instead of status).
        """
        # 1. global_state → JSON load
        try:
            p = self.paths["global_state"]
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._cache["global_state"] = data
                    else:
                        logger.warning(f"[DashboardState] global_state is not a dict: {type(data)}")
                        self._cache["global_state"] = {"state": "DEGRADED", "info": "Invalid structure"}
                logger.info(f"[DashboardState] Loaded global_state: {p}")
            else:
                self._cache["global_state"] = {"state": "UNKNOWN", "info": "Persistence missing"}
        except Exception as e:
            logger.error(f"[DashboardState] Failed global_state: {e}")
            self._cache["global_state"] = {"state": "ERROR"}

        # 2. radar_evaluations → JSONL line-by-line parsing
        try:
            p = self.paths["radar_evaluations"]
            evals = []
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        entry = line.strip()
                        if entry:
                            try:
                                evals.append(json.loads(entry))
                            except json.JSONDecodeError:
                                continue
            self._cache["evaluations"] = evals
        except Exception as e:
            logger.error(f"[DashboardState] Failed radar_evaluations: {e}")
            self._cache["evaluations"] = []

        # 3. product_lifecycle → JSON load
        try:
            p = self.paths["product_lifecycle"]
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cache["products"] = data if isinstance(data, dict) else {}
            else:
                self._cache["products"] = {}
        except Exception as e:
            logger.error(f"[DashboardState] Failed product_lifecycle: {e}")
            self._cache["products"] = {}

        # 4. finance_state → JSON load
        try:
            p = self.paths["finance_state"]
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cache["budget"] = data if isinstance(data, dict) else {}
            else:
                self._cache["budget"] = {}
        except Exception as e:
            logger.error(f"[DashboardState] Failed finance_state: {e}")
            self._cache["budget"] = {}

        # 5. commercial_state → JSON load
        try:
            p = self.paths["commercial_state"]
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._cache["commercial"] = data if isinstance(data, dict) else {}
            else:
                self._cache["commercial"] = {}
        except Exception as e:
            logger.error(f"[DashboardState] Failed commercial_state: {e}")
            self._cache["commercial"] = {}

    def _load_mock_data(self):
        """Provides high-quality synthetic data aligned with dashboard keys."""
        iso_now = datetime.now(timezone.utc).isoformat()
        self._cache["global_state"] = {"state": "NORMAL (MOCK)"}
        self._cache["budget"] = {
            "calls_today": 42,
            "max_calls_per_day": 100,
            "cost_today_usd": 1.25
        }
        self._cache["products"] = {
            "mock_id_1": {"product_id": "mock-prod-1", "state": "ACTIVE", "baseline_version": 1, "created_at": iso_now},
            "mock_id_2": {"product_id": "mock-prod-2", "state": "DRAFT", "baseline_version": 2, "created_at": iso_now}
        }
        self._cache["evaluations"] = [
            {
                "timestamp": iso_now, 
                "product_id": "mock-prod-1", 
                "ice": "ALTO", 
                "score_final": 0.98, 
                "recommended": True
            },
            {
                "timestamp": iso_now, 
                "product_id": "mock-prod-2", 
                "ice": "MEDIO", 
                "score_final": 0.45, 
                "recommended": False
            }
        ]
        self._cache["commercial"] = {"total_leads": 12, "last_synced": iso_now}

    def _log_history(self):
        """Appends a concise operational snapshot using aligned keys."""
        try:
            snapshot = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "mode": self._mode,
                "summary": {
                    "evals": len(self._cache["evaluations"]),
                    "products": len(self._cache["products"]),
                    "state": self._cache["global_state"].get("state", "UNKNOWN")
                }
            }
            p = self.paths["history_log"]
            with open(p, "a", encoding="utf-8") as f:
                f.write(json.dumps(snapshot) + "\n")
        except Exception as e:
            logger.error(f"[DashboardState] History logging failed: {e}")

# Global singleton instance for cross-module usage
dashboard_state = DashboardStateManager()
