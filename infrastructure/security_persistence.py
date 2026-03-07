"""
infrastructure/security_persistence.py
Append-only persistence for security events (security_log.json).

Format: JSON Lines — one JSON object per line.
Entries are NEVER deleted or overwritten.
"""
import json
import os
from infrastructure.logger import get_logger

logger = get_logger("SecurityPersistence")


class SecurityPersistence:
    """
    Append-only log for IP access events and security decisions.

    Each entry:
    {
      "ip":        str,
      "endpoint":  str,
      "timestamp": ISO8601,
      "status":    "ALLOWED" | "BLOCKED"
    }
    """

    def __init__(self, filepath: str = "security_log.json"):
        self.filepath = filepath

    def append_log(self, entry: dict) -> None:
        """Append a single log entry. Never overwrites existing entries."""
        try:
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"Failed to append security log: {e}")

    def load_all(self) -> list[dict]:
        """Read all log entries (for audit/inspection)."""
        if not os.path.exists(self.filepath):
            return []
        entries = []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except IOError as e:
            logger.error(f"Failed to read security log: {e}")
        return entries
