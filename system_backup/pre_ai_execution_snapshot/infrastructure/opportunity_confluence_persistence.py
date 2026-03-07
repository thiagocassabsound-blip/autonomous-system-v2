"""
infrastructure/opportunity_confluence_persistence.py
Append-only JSON-Lines persistence for B2 confluence validation records.

File: infrastructure/opportunity_confluence_state.json

Each record = one validation result with event_id, timestamps,
categories_confirmed, growth_percent, intensity_score, status, motivo_bloqueio.
Nothing is ever deleted, overwritten, or mutated after writing.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("OpportunityConfluencePersistence")


class OpportunityConfluencePersistence:
    """Absolute append-only JSON-Lines store for B2 confluence validation records."""

    def __init__(
        self,
        filepath: str = "infrastructure/opportunity_confluence_state.json",
    ):
        self.filepath = filepath

    def append_record(self, record: dict) -> None:
        """Append one validation record. Never overwrites existing lines."""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"[B2] Failed to append confluence record: {e}")

    def load_all(self) -> list[dict]:
        """Read all validation records in append order."""
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
            logger.error(f"[B2] Failed to read confluence state: {e}")
        return records
