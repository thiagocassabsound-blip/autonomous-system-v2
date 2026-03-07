"""
core/uptime_engine.py — A11 Uptime Governance Engine

Controls the active lifetime of products with full integrity guarantees:
  - created_at is set once and never overwritten
  - total_active_seconds is strictly accumulative (never decreases)
  - pause accumulates elapsed seconds; resume records a fresh timestamp
  - No reset, no retroactive recalculation, no manual overwrite
  - All transitions emit formal EventBus events
  - No direct writes outside Orchestrator

Domain exceptions:
  ProductAlreadyInitializedError — double init attempt
  ProductAlreadyActiveError      — resume on active product
  ProductNotActiveError          — pause on inactive product
  UptimeIntegrityViolationError  — any attempt to reduce/reset total_active_seconds
  ProductNotFoundError           — operation on untracked product
"""
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("UptimeEngine")


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class ProductAlreadyInitializedError(Exception):
    """Raised when product_created is called for an already-tracked product."""

class ProductAlreadyActiveError(Exception):
    """Raised when resume is called on an already-active product."""

class ProductNotActiveError(Exception):
    """Raised when pause is called on an inactive product."""

class UptimeIntegrityViolationError(Exception):
    """Raised when any operation would decrease or reset total_active_seconds."""

class ProductNotFoundError(Exception):
    """Raised when an operation targets an untracked product_id."""


# ---------------------------------------------------------------------------
# Uptime Engine
# ---------------------------------------------------------------------------

class UptimeEngine:
    """
    Deterministic, append-only uptime tracker.

    Each product record has:
      product_id              — stable identifier
      created_at              — ISO8601, set once, never overwritten
      last_resume_timestamp   — ISO8601 | None  (None when paused/stopped)
      total_active_seconds    — int, only ever increases
      is_active               — bool

    Parameters
    ----------
    persistence : UptimePersistence duck type (load / save)
    now_fn      : Injectable clock for deterministic tests
    """

    def __init__(self, persistence, now_fn=None):
        self._pers   = persistence
        self._now    = now_fn or (lambda: datetime.now(timezone.utc))
        raw          = persistence.load()
        self._state: dict = raw if isinstance(raw, dict) else {}
        logger.info(
            f"UptimeEngine initialized. Products tracked: {list(self._state.keys())}"
        )

    # =======================================================================
    # Product Created — Item 68
    # =======================================================================

    def register_product(self, product_id: str, orchestrator) -> dict:
        """
        Register a new product and record its immutable created_at timestamp.

        Raises: ProductAlreadyInitializedError
        Emits:  product_created_timestamped
        """
        pid = str(product_id)
        if pid in self._state:
            raise ProductAlreadyInitializedError(
                f"Product '{pid}' is already initialized "
                f"(created_at={self._state[pid]['created_at']}). "
                f"created_at is immutable and cannot be reset."
            )

        now = self._now()
        record = {
            "product_id":             pid,
            "created_at":             now.isoformat(),
            "last_resume_timestamp":  None,
            "total_active_seconds":   0,
            "is_active":              False,
        }
        self._state[pid] = record
        self._save()

        orchestrator.emit_event(
            event_type="product_created_timestamped",
            payload={
                "product_id": pid,
                "created_at": now.isoformat(),
            },
            source="UptimeEngine",
            product_id=pid
        )
        logger.info(f"Product '{pid}' registered. created_at={now.isoformat()}")
        return record

    # =======================================================================
    # Resume — Item 70
    # =======================================================================

    def resume_product(self, product_id: str, orchestrator) -> dict:
        """
        Mark the product as active and record last_resume_timestamp.

        Precondition: is_active == False
        Raises: ProductAlreadyActiveError
        Emits:  product_resumed
        """
        pid    = str(product_id)
        record = self._require(pid)
        now    = self._now()

        if record["is_active"]:
            raise ProductAlreadyActiveError(
                f"Product '{pid}' is already active "
                f"(last_resume={record['last_resume_timestamp']}). "
                f"Cannot resume an already-running product."
            )

        record["is_active"]              = True
        record["last_resume_timestamp"]  = now.isoformat()
        self._save()

        orchestrator.emit_event(
            event_type="product_resumed",
            payload={
                "product_id":      pid,
                "resumed_at":      now.isoformat(),
                "uptime_at_resume": record["total_active_seconds"],
            },
            source="UptimeEngine",
            product_id=pid
        )
        logger.info(f"Product '{pid}' resumed at {now.isoformat()}")
        return record

    # =======================================================================
    # Pause — Item 71 / Item 69
    # =======================================================================

    def pause_product(self, product_id: str, orchestrator) -> dict:
        """
        Pause the product and accumulate elapsed seconds into total_active_seconds.

        Precondition: is_active == True
        Raises: ProductNotActiveError
        Emits:  product_paused

        Integrity guarantee:
          new_total = old_total + delta  (always >= old_total)
          Any delta < 0 raises UptimeIntegrityViolationError.
        """
        pid    = str(product_id)
        record = self._require(pid)
        now    = self._now()

        if not record["is_active"]:
            raise ProductNotActiveError(
                f"Product '{pid}' is not active — cannot pause. "
                f"total_active_seconds={record['total_active_seconds']}."
            )

        # Calculate elapsed seconds
        resume_dt = datetime.fromisoformat(record["last_resume_timestamp"])
        # Make timezone-aware if necessary
        if resume_dt.tzinfo is None:
            resume_dt = resume_dt.replace(tzinfo=timezone.utc)
        delta = int((now - resume_dt).total_seconds())

        if delta < 0:
            raise UptimeIntegrityViolationError(
                f"Uptime integrity violation: computed delta={delta}s for product='{pid}'. "
                f"Clock skew or manipulated timestamp detected. "
                f"total_active_seconds cannot decrease."
            )

        old_total              = record["total_active_seconds"]
        new_total              = old_total + delta
        record["total_active_seconds"]  = new_total
        record["is_active"]             = False
        record["last_resume_timestamp"] = None
        self._save()

        orchestrator.emit_event(
            event_type="product_paused",
            payload={
                "product_id":           pid,
                "paused_at":            now.isoformat(),
                "active_seconds_delta": delta,
                "total_active_seconds": new_total,
            },
            source="UptimeEngine",
            product_id=pid
        )
        logger.info(
            f"Product '{pid}' paused. delta={delta}s total={new_total}s"
        )
        return record

    # =======================================================================
    # Reset Guard — Item 72 / Item 69
    # =======================================================================

    def reset_uptime(self, product_id: str) -> None:
        """
        Always raises UptimeIntegrityViolationError.
        No reset is ever allowed — this method exists only as an explicit guard.
        """
        raise UptimeIntegrityViolationError(
            f"reset_uptime() is permanently forbidden. "
            f"total_active_seconds for product='{product_id}' is immutable. "
            f"Uptime governance requires strictly accumulative tracking."
        )

    def overwrite_created_at(self, product_id: str, new_ts: str) -> None:
        """Always raises UptimeIntegrityViolationError."""
        raise UptimeIntegrityViolationError(
            f"overwrite_created_at() is permanently forbidden. "
            f"created_at for product='{product_id}' is immutable."
        )

    def set_total_active_seconds(self, product_id: str, value: int) -> None:
        """Always raises UptimeIntegrityViolationError."""
        raise UptimeIntegrityViolationError(
            f"set_total_active_seconds() is permanently forbidden. "
            f"total_active_seconds can only grow via accumulation on pause."
        )

    # =======================================================================
    # Read-only accessors
    # =======================================================================

    def get_record(self, product_id: str) -> dict | None:
        return self._state.get(str(product_id))

    def get_current_uptime_seconds(self, product_id: str) -> int:
        """
        Return total uptime including currently running session (if active).
        """
        record = self._require(str(product_id))
        total  = record["total_active_seconds"]
        if record["is_active"] and record["last_resume_timestamp"]:
            now = self._now()
            resume_dt = datetime.fromisoformat(record["last_resume_timestamp"])
            if resume_dt.tzinfo is None:
                resume_dt = resume_dt.replace(tzinfo=timezone.utc)
            live_delta = max(0, int((now - resume_dt).total_seconds()))
            total += live_delta
        return total

    # =======================================================================
    # Internal helpers
    # =======================================================================

    def _require(self, pid: str) -> dict:
        rec = self._state.get(pid)
        if rec is None:
            raise ProductNotFoundError(
                f"No uptime record found for product='{pid}'. "
                f"Call register_product() first."
            )
        return rec

    def _save(self) -> None:
        self._pers.save(self._state)
