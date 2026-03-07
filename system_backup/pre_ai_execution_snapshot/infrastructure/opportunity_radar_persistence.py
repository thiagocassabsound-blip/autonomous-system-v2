"""
infrastructure/opportunity_radar_persistence.py
Append-only persistence for strategic opportunity evaluations.

File: infrastructure/opportunity_radar_state.json (JSON-Lines)

Each evaluation is written as an independent JSON object on its own line.
Nothing is ever deleted, overwritten, or recalculated after writing.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("OpportunityRadarPersistence")


class OpportunityRadarPersistence:
    """
    Absolute append-only JSON-Lines store for opportunity evaluation records.

    Each line = one evaluation record with event_id, timestamp,
    scores, ICE, cluster_ratio, and eligibility.
    """

    def __init__(self, filepath: str = "infrastructure/opportunity_radar_state.json"):
        self.filepath = filepath

    def append_record(self, record: dict) -> None:
        """Append a single evaluation record. Never overwrites existing lines."""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"Failed to append opportunity record: {e}")

    def load_all(self) -> list[dict]:
        """Read all evaluation records in append order."""
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
            logger.error(f"Failed to read opportunity radar: {e}")
        return records
