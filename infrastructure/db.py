"""
infrastructure/db.py — Persistence Backends
- FilePersistence: generic JSON state file
- EventLogPersistence: append-only event ledger (events.json)
- SnapshotPersistence: append-only snapshot store (snapshots.json)
"""
import json
import os
import tempfile
from infrastructure.logger import get_logger

logger = get_logger("Persistence")

# ======================================================================
# Generic state file
# ======================================================================

class FilePersistence:
    """Simple JSON key-value store. Used by StateManager."""

    def __init__(self, filepath: str = "state.json"):
        self.filepath = filepath

    def load(self) -> dict:
        if not os.path.exists(self.filepath):
            logger.info(f"No state file at '{self.filepath}'. Starting fresh.")
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"State loaded from '{self.filepath}' ({len(data)} keys).")
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load state: {e}. Starting fresh.")
            return {}

    def save(self, data_dict: dict) -> None:
        """Atomic save using temporary file + rename."""
        try:
            fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(self.filepath), prefix=".tmp_state_")
            with os.fdopen(fd, 'w', encoding="utf-8") as f:
                json.dump(data_dict, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.filepath)
        except IOError as e:
            logger.error(f"Failed to save state: {e}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)


# ======================================================================
# Append-only event ledger
# ======================================================================

class EventLogPersistence:
    """
    Append-only event log persisted to events.json.
    load() returns the full list.
    append() adds one event; never updates or deletes existing entries.
    """

    def __init__(self, filepath: str = "events.json"):
        self.filepath = filepath

    def load(self) -> list:
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load event log: {e}.")
            return []

    def load_all(self) -> list:
        """Alias for load() to support StrategicOpportunityEngine V2."""
        return self.load()

    def append(self, event: dict) -> None:
        """Append one event to the ledger using atomic save."""
        events = self.load()
        events.append(event)
        try:
            fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(self.filepath), prefix=".tmp_events_")
            with os.fdopen(fd, 'w', encoding="utf-8") as f:
                json.dump(events, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.filepath)
        except IOError as e:
            logger.error(f"Failed to persist event: {e}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)

    def append_record(self, record: dict) -> None:
        """Alias for append() to support StrategicOpportunityEngine V2."""
        self.append(record)


# ======================================================================
# Append-only snapshot store
# ======================================================================

class SnapshotPersistence:
    """
    Append-only snapshot store persisted to snapshots.json.
    Snapshots are never deleted or updated.
    """

    def __init__(self, filepath: str = "snapshots.json"):
        self.filepath = filepath

    def load(self) -> list:
        if not os.path.exists(self.filepath):
            return []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load snapshots: {e}.")
            return []

    def append(self, snapshot: dict) -> None:
        """Atomic append to snapshot store."""
        snapshots = self.load()
        snapshots.append(snapshot)
        try:
            fd, temp_path = tempfile.mkstemp(dir=os.path.dirname(self.filepath), prefix=".tmp_snaps_")
            with os.fdopen(fd, 'w', encoding="utf-8") as f:
                json.dump(snapshots, f, indent=2, ensure_ascii=False)
            os.replace(temp_path, self.filepath)
        except IOError as e:
            logger.error(f"Failed to persist snapshot: {e}")
            if 'temp_path' in locals() and os.path.exists(temp_path):
                os.remove(temp_path)

    def append_record(self, record: dict) -> None:
        """Alias for append() to support StrategicOpportunityEngine V2."""
        self.append(record)


# ======================================================================
# Generic JSON persistence (for StateMachine, VersionManager, etc.)
# ======================================================================

class JsonFilePersistence:
    """Generic load/save for arbitrary JSON data (dict or list)."""

    def __init__(self, filepath: str):
        self.filepath = filepath

    def load(self):
        if not os.path.exists(self.filepath):
            return {}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load '{self.filepath}': {e}.")
            return {}

    def save(self, data) -> None:
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save '{self.filepath}': {e}")

# ======================================================================
# Newline-delimited JSON persistence (JSONL)
# ======================================================================

class JSONLPersistence:
    """
    Persistence backend for .jsonl files (one JSON object per line).
    Extremely efficient for large logs as it uses append-only writes.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath

    def load(self) -> list:
        """Read all lines and parse as JSON objects. Supports hybrid format (standard JSON array OR JSONL)."""
        if not os.path.exists(self.filepath):
            return []
            
        items = []
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return []
                
                # Hybrid Detection: If the file starts with '[', treat as a single JSON array
                if content.startswith("["):
                    try:
                        data = json.loads(content)
                        return data if isinstance(data, list) else [data]
                    except json.JSONDecodeError:
                        # Fallback to line-by-line if it's a corrupted array or just lines starting with '['
                        pass
                
                # Standard JSONL processing: line-by-line
                f.seek(0)
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            items.append(json.loads(line))
                        except json.JSONDecodeError as e:
                            logger.error(f"Error parsing line in {self.filepath}: {e}")
            return items
        except IOError as e:
            logger.error(f"Failed to load JSONL from '{self.filepath}': {e}")
            return []

    def load_all(self) -> list:
        """Alias for load()."""
        return self.load()

    def append_record(self, item: dict) -> None:
        """Append one JSON object as a new line."""
        try:
            # Atomic-ish append: directly to file
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"Failed to append to JSONL '{self.filepath}': {e}")

    def append(self, item: dict) -> None:
        """Alias for append_record()."""
        self.append_record(item)
