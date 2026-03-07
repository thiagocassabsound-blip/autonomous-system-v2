"""
infrastructure/user_enrichment_persistence.py
Append-only JSON-Lines persistence for B4 User Enrichment Engine.

File: infrastructure/user_enrichment_state.json

Each record is a JSON object on its own line:
  - event_id, timestamp, user_id
  - metrics_snapshot (LTV, refund_ratio, risk_score, …)
  - classification_tag (list)
  - export_signal_ready (bool)

Nothing is ever deleted, overwritten, or mutated after writing.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("UserEnrichmentPersistence")


class UserEnrichmentPersistence:
    """Absolute append-only JSON-Lines store for B4 user enrichment snapshots."""

    def __init__(
        self,
        filepath: str = "infrastructure/user_enrichment_state.json",
    ):
        self.filepath = filepath

    def append_record(self, record: dict) -> None:
        """Append one enrichment snapshot. Never overwrites existing lines."""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"[B4] Failed to append enrichment record: {e}")

    def load_all(self) -> list[dict]:
        """Read all enrichment snapshots in append order."""
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
            logger.error(f"[B4] Failed to read user enrichment state: {e}")
        return records
