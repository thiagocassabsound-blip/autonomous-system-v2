"""
infrastructure/feedback_incentive_persistence.py
Append-only JSON-Lines persistence for B3 Feedback Incentivado Engine.

File: infrastructure/feedback_incentive_state.json

Each record is a JSON object on its own line:
  - event_id, timestamp, user_id, product_id, event_type, metadata
  - engagement evaluations, feedback submissions/validations/rejections
  - lifetime_upgrade_granted / lifetime_upgrade_revoked / access_revoked

Nothing is ever deleted, overwritten, or mutated after writing.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("FeedbackIncentivePersistence")


class FeedbackIncentivePersistence:
    """Absolute append-only JSON-Lines store for B3 feedback incentive records."""

    def __init__(
        self,
        filepath: str = "infrastructure/feedback_incentive_state.json",
    ):
        self.filepath = filepath

    def append_record(self, record: dict) -> None:
        """Append one record. Never overwrites existing lines."""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"[B3] Failed to append feedback record: {e}")

    def load_all(self) -> list[dict]:
        """Read all records in append order."""
        if not os.path.exists(self.filepath):
            return []
        records = []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except IOError as e:
            logger.error(f"[B3] Failed to read feedback incentive state: {e}")
        return records
