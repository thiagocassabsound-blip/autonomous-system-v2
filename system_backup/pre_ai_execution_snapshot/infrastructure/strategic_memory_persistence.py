"""
infrastructure/strategic_memory_persistence.py
Append-only persistence for monthly consolidated records (strategic_memory.json).

Format: JSON Lines — one record per line, never overwritten.
Each call to append_record() adds exactly one new line.
No records are ever deleted or modified after writing.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("StrategicMemoryPersistence")


class StrategicMemoryPersistence:
    """
    Absolute append-only storage for strategic memory records.

    Schema per line:
    {
      "product_id":           str,
      "month_id":             "YYYY-MM",
      "baseline_version":     str,
      "baseline_price":       float,
      "rpm_final":            float,
      "roas_final":           float,
      "cac_final":            float,
      "margin_final":         float,
      "total_active_seconds": int,
      "total_revenue":        float,
      "total_ad_spend":       float,
      "snapshot_reference":   str,
      "consolidated_at":      ISO8601
    }
    """

    def __init__(self, filepath: str = "strategic_memory.json"):
        self.filepath = filepath

    def append_record(self, record: dict) -> None:
        """Append a single consolidated record. Never overwrites existing lines."""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"Failed to append strategic memory record: {e}")

    def load_all(self) -> list[dict]:
        """Read all consolidated records in append order."""
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
            logger.error(f"Failed to read strategic memory: {e}")
        return records
