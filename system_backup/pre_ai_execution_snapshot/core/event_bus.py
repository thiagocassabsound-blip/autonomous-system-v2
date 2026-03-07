"""
core/event_bus.py — Dual-mode EventBus
1. Pub/Sub:  subscribe() / emit()  — internal engine communication (backward-compat)
2. Ledger:   append_event() / get_events()  — append-only formal audit log
"""
import uuid
import threading
from collections import defaultdict
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("EventBus")


STRICT_MODE = True

class EventBus:
    """
    Dual-mode EventBus.
    Pub/Sub is used by engines for internal event routing.
    Ledger is append-only and persisted; used by the Orchestrator for formal events.
    """

    def __init__(self, log_persistence=None):
        self._orchestrated_context = False
        self._lock = threading.Lock() # Internal lock for version/ledger integrity
        # --- Pub/Sub state ---
        self._handlers: dict = defaultdict(list)

        # --- Ledger state ---
        self._log = log_persistence
        self._events: list = []
        self._global_version: int = 0

        if self._log:
            self._events = self._log.load()
            self._global_version = len(self._events)
            logger.info(
                f"EventBus loaded {self._global_version} ledger events from persistence."
            )

    # ==================================================================
    # Pub / Sub API (backward-compatible)
    # ==================================================================

    def subscribe(self, event_type: str, handler) -> None:
        self._handlers[event_type].append(handler)

    def emit(self, event_type: str, payload: dict = None) -> None:
        handlers = list(self._handlers.get(event_type, []))
        logger.info(f"EVENT [{event_type}] → {len(handlers)} handler(s)")
        for handler in handlers:
            try:
                handler(payload or {})
            except Exception as e:
                logger.error(f"Handler error [{event_type}]: {e}", exc_info=True)

    # ==================================================================
    # Formal Ledger API (append-only)
    # ==================================================================

    def generate_event_id(self) -> str:
        return str(uuid.uuid4())

    def _enter_orchestrated_context(self):
        self._orchestrated_context = True

    def _exit_orchestrated_context(self):
        self._orchestrated_context = False

    def append_event(self, event: dict) -> dict:
        from core.legacy_write_bridge import LegacyWriteBridge
        LegacyWriteBridge.intercept_event_write(event)

        if STRICT_MODE and not self._orchestrated_context:
            raise RuntimeError(
                "STRICT_MODE_VIOLATION: append_event outside Orchestrator. "
                f"event_type={event.get('event_type')} source={event.get('source')}"
            )

        if "event_type" not in event:
            raise ValueError("append_event: 'event_type' is required.")
        if "payload" not in event:
            raise ValueError("append_event: 'payload' is required.")

        with self._lock:
            self._global_version += 1
            gv = self._global_version

        formal: dict = {
            "event_id":   event.get("event_id") or self.generate_event_id(),
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "product_id": event.get("product_id"),
            "month_id":   event.get("month_id"),
            "event_type": event["event_type"],
            "payload":    event["payload"],
            "version":    gv,
            "source":     event.get("source", "system"),
        }

        # Append-only — never update or delete
        with self._lock:
            self._events.append(formal)
            
        if self._log:
            self._log.append(formal)

        logger.debug(
            f"Ledger: [{formal['event_type']}] v{formal['version']} "
            f"id={formal['event_id'][:8]}..."
        )
        return formal

    def get_events(
        self,
        product_id: str | None = None,
        month_id: str | None = None,
    ) -> list:
        """Return ledger events, optionally filtered."""
        result = self._events
        if product_id is not None:
            result = [e for e in result if e.get("product_id") == product_id]
        if month_id is not None:
            result = [e for e in result if e.get("month_id") == month_id]
        return list(result)
