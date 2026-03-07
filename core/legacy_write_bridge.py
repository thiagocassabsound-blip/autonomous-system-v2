"""
core/legacy_write_bridge.py — C3A Transition Observability Layer
Intercepts legacy writes to state and event ledger for monitoring.
"""
import json
import inspect
import os
from datetime import datetime, timezone
from pathlib import Path

# --- Configuration ---
LEGACY_BRIDGE_ENABLED = True
LOG_FILE = Path("logs/legacy_write_monitor.jsonl")

# Ensure logs directory exists
os.makedirs(LOG_FILE.parent, exist_ok=True)

class LegacyWriteBridge:
    """
    Non-blocking interceptor for legacy state and event writes.
    Provides observability during the C3A transition.
    """

    @staticmethod
    def _get_caller_module():
        """Identify the calling module, ignoring internal bridge frames."""
        stack = inspect.stack()
        # Modules to skip to find the actual origin engine
        skip_list = ["legacy_write_bridge", "event_bus", "state_machine", "global_state"]
        
        for frame in stack[1:]:
            module = inspect.getmodule(frame[0])
            if module:
                module_name = module.__name__
                if not any(skip in module_name for skip in skip_list):
                    return module_name
        return "unknown"

    @staticmethod
    def _log_write(data: dict):
        """Append entry to legacy monitor log."""
        if not LEGACY_BRIDGE_ENABLED:
            return

        entry = {
            "type": "legacy_write",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data
        }

        try:
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            # Failure to log must NEVER break the application flow
            pass

    @classmethod
    def intercept_event_write(cls, event: dict):
        """Monitor direct calls to event_bus.append_event()."""
        caller = cls._get_caller_module()
        cls._log_write({
            "origin": caller,
            "write_type": "event",
            "details": {
                "event_type": event.get("event_type"),
                "product_id": event.get("product_id")
            }
        })

    @classmethod
    def intercept_state_write(cls, old_state: str, new_state: str):
        """Monitor direct calls to state_machine.transition()."""
        caller = cls._get_caller_module()
        cls._log_write({
            "origin": caller,
            "write_type": "state",
            "details": {
                "old_state": old_state,
                "new_state": new_state
            }
        })

    @classmethod
    def intercept_global_state_write(cls, old_value: str, new_value: str, legacy_warning: bool = False, severity: str = None):
        """Monitor direct calls to global_state.update_state()."""
        caller = cls._get_caller_module()
        log_data = {
            "origin": caller,
            "write_type": "global_state",
            "details": {
                "old_value": old_value,
                "new_value": new_value
            }
        }
        if legacy_warning:
            log_data["legacy_warning"] = legacy_warning
            log_data["severity"] = severity or "GLOBAL_STATE_DIRECT_WRITE"
            
        cls._log_write(log_data)
