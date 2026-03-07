"""
infrastructure/version_persistence.py
Persistence for governed version state (version_state.json).
version_history is always append-only — no entry deletion permitted.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("VersionPersistence")


class VersionPersistence:
    """
    Reads/writes version_state.json.

    Schema (flat product-keyed dict):
    {
      "product_id": {
        "product_id":                  str,
        "baseline_version":             str | None,
        "baseline_metrics_snapshot_id": str | None,
        "candidate_version":            str | None,
        "version_history": [
          {
            "version_id":          str,
            "type":                "BASELINE" | "CANDIDATE" | "ROLLED_BACK",
            "linked_snapshot_id":  str | None,
            "linked_price":        float | None,
            "timestamp":           ISO8601
          },
          ...
        ]
      },
      ...
    }

    version_history entries are immutable — never deleted or overwritten.
    """

    def __init__(self, filepath: str = "version_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load version state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save version state: {e}")
