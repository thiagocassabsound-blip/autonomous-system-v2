"""
infrastructure/pricing_persistence.py
Persistence for product pricing state (pricing_state.json).
price_history entries are append-only — no record deletion permitted.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("PricingPersistence")


class PricingPersistence:
    """
    Reads/writes pricing_state.json.

    Schema:
        {
          "product_id": {
            "product_id":                str,
            "base_price":                float,
            "current_price":             float,
            "rpm_base_reference":        float,
            "offensive_increases_count": int,
            "last_price_change_timestamp": ISO8601 | None,
            "price_history": [
              {
                "old_price": float,
                "new_price": float,
                "type":      "OFFENSIVE" | "DEFENSIVE" | "ROLLBACK",
                "reason":    str,
                "timestamp": ISO8601
              },
              ...
            ]
          },
          ...
        }

    price_history is always appended, never truncated or deleted.
    """

    def __init__(self, filepath: str = "pricing_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load pricing state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save pricing state: {e}")
