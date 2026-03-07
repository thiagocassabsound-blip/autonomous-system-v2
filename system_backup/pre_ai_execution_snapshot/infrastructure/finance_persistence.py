"""
infrastructure/finance_persistence.py — Finance-Specific Persistence Backends

finance_state.json        — overwritable financial state (via Orchestrator only)
financial_projections.json — append-only projection history
global_state.json          — overwritable global state file
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("FinancePersistence")


class FinanceStatePersistence:
    """
    Reads/writes finance_state.json.
    State can be overwritten — but only via Orchestrator pathway.
    """

    def __init__(self, filepath: str = "finance_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load finance state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save finance state: {e}")


class FinanceProjectionsPersistence:
    """
    Append-only projection log → financial_projections.json.
    Projections are never deleted or updated.
    """

    def __init__(self, filepath: str = "financial_projections.json"):
        self.filepath = filepath

    def load(self) -> list:
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load projections: {e}")
            return []

    def append(self, projection: dict) -> None:
        projections = self.load()
        projections.append(projection)
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(projections, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to persist projection: {e}")


class GlobalStatePersistence:
    """Reads/writes global_state.json (overwritable)."""

    def __init__(self, filepath: str = "global_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load global state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save global state: {e}")
