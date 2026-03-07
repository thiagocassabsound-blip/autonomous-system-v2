"""
infrastructure/commercial_persistence.py
Persistence for commercial user/license state (commercial_state.json).

Records are keyed by user_id. Status transitions (ACTIVE → REVOKED)
update the record in-place; history is preserved via the EventBus ledger.
No record is ever deleted.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("CommercialPersistence")


class CommercialPersistence:
    """
    Reads/writes commercial_state.json.

    Schema (flat user_id-keyed dict):
    {
      "user_id": {
        "user_id":      str,
        "product_id":   str,
        "license_id":   str,
        "access_token": str | None,
        "status":       "ACTIVE" | "REVOKED",
        "payment_id":   str,
        "created_at":   ISO8601,
        "revoked_at":   ISO8601 | None
      },
      ...
    }

    Access history is immutable via the EventBus ledger.
    State transitions are the only in-place mutations.
    """

    def __init__(self, filepath: str = "commercial_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load commercial state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save commercial state: {e}")
