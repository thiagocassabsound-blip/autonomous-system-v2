"""
infrastructure/product_lifecycle_persistence.py
Persistence for product lifecycle states (product_lifecycle_state.json).
No deletes permitted.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("ProductLifecyclePersistence")


class ProductLifecyclePersistence:
    """
    Reads/writes product_lifecycle_state.json.

    Schema:
        {
          "product_id": {
            "beta_start":      ISO8601,
            "beta_end":        ISO8601,
            "classification":  null | "elegivel" | "nao_elegivel",
            "last_transition": ISO8601,
            "beta_closed_at":  null | ISO8601
          },
          ...
        }

    Overwrites only via Orchestrator pathway.
    No record deletion permitted.
    """

    def __init__(self, filepath: str = "product_lifecycle_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load product lifecycle state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save product lifecycle state: {e}")
