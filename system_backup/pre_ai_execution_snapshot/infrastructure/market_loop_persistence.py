"""
infrastructure/market_loop_persistence.py
Persistence for market loop cycle history (market_loop_state.json).
Append-only — cycles are never deleted.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("MarketLoopPersistence")


class MarketLoopPersistence:
    """
    Reads/writes market_loop_state.json.

    Schema:
        {
          "product_id": [
            {
              "cycle_id":                  UUID,
              "product_id":                str,
              "current_phase":             int,
              "phases_completed":          [int, ...],
              "baseline_snapshot_version": int | None,
              "candidate_version":         str | None,
              "last_substitution_at":      ISO8601 | None,
              "started_at":               ISO8601,
              "closed_at":                ISO8601 | None,
              "status":                   "open" | "closed"
            },
            ...
          ],
          ...
        }

    No record deletion permitted.
    """

    def __init__(self, filepath: str = "market_loop_state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load market loop state: {e}")
            return {}

    def save(self, data: dict) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save market loop state: {e}")
