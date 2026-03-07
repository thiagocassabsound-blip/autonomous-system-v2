"""
infrastructure/uptime_persistence.py
Persistence for product uptime state (uptime_state.json).

Each product record is written on every pause/resume/init.
total_active_seconds is always the authoritative accumulated value —
it can only grow, never be reset. Records are never deleted.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("UptimePersistence")


class UptimePersistence:
    """
    Reads/writes uptime_state.json.

    Schema:
    {
      "product_id": {
        "product_id":             str,
        "created_at":             ISO8601,
        "last_resume_timestamp":  ISO8601 | null,
        "total_active_seconds":   int,
        "is_active":              bool
      },
      ...
    }

    Records are never deleted. total_active_seconds only ever grows.
    """

    def __init__(self, filepath: str = "uptime_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load uptime state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save uptime state: {e}")
