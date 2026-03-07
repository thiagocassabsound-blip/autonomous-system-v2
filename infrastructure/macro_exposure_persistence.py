"""
infrastructure/macro_exposure_persistence.py
Append-only JSON-Lines persistence for Bloco 29 Macro Exposure Governance Engine.

File: infrastructure/macro_exposure_state.json

Each record is a JSON object on one line:
  - event_id, timestamp
  - product_id, channel_id
  - active_limits (product / channel / global / mode)
  - projected_exposures (product / channel / global)
  - roas_avg, score_global, refund_ratio_avg
  - global_state
  - adaptive_mode_active (bool)
  - decision ("validated" | "blocked" | "adapted" | "reverted")
  - violations (list[str])

Nothing is ever deleted, overwritten, or mutated after writing.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("MacroExposurePersistence")


class MacroExposurePersistence:
    """Absolute append-only JSON-Lines store for Bloco 29 audit records."""

    def __init__(
        self,
        filepath: str = "infrastructure/macro_exposure_state.json",
    ):
        self.filepath = filepath

    def append_record(self, record: dict) -> None:
        """Append one audit record. Never overwrites existing lines."""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"[Bloco29] Failed to append exposure record: {e}")

    def load_all(self) -> list[dict]:
        """Read all audit records in append order."""
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
            logger.error(f"[Bloco29] Failed to read macro exposure state: {e}")
        return records
