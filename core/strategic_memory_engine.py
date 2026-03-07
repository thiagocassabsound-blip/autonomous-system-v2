"""
core/strategic_memory_engine.py — A12 Strategic Memory Engine

Governs monthly consolidation of product performance data:
  - month_id is mandatory (format YYYY-MM), validated via regex
  - Each product can only consolidate each month ONCE
  - Consolidated data is frozen at the moment of consolidation
  - No recalculation, reopening, or retroactive update is permitted
  - All records are append-only; nothing is ever deleted
  - All transitions emit formal EventBus events
  - No direct writes outside Orchestrator

Domain exceptions:
  InvalidMonthIdError               — bad format or future month
  MonthAlreadyConsolidatedError     — second consolidation attempt
  StrategicMemoryImmutableError     — any reopen/edit/recalc attempt
"""
import re
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("StrategicMemoryEngine")

# YYYY-MM format, basic validation
_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class InvalidMonthIdError(Exception):
    """Raised when month_id is malformed or refers to a future month."""

class MonthAlreadyConsolidatedError(Exception):
    """Raised when a product+month pair has already been consolidated."""

class StrategicMemoryImmutableError(Exception):
    """Raised on any attempt to edit, reopen, or recalculate a closed month."""


# ---------------------------------------------------------------------------
# Strategic Memory Engine
# ---------------------------------------------------------------------------

class StrategicMemoryEngine:
    """
    Append-only monthly consolidation engine.

    Each consolidated record captures a frozen snapshot of:
      baseline_version, baseline_price, RPM, ROAS, CAC, margin,
      total_active_seconds, total_revenue, total_ad_spend,
      snapshot_reference, consolidated_at.

    Parameters
    ----------
    persistence : StrategicMemoryPersistence duck type (load / append / load_all)
    now_fn      : Injectable clock for deterministic tests
    """

    def __init__(self, orchestrator, persistence, now_fn=None):
        self.orchestrator = orchestrator
        self._pers       = persistence
        self._now        = now_fn or (lambda: datetime.now(timezone.utc))

        # Build in-memory index: (product_id, month_id) → record
        self._index: dict[tuple, dict] = {}
        for rec in persistence.load_all():
            key = (rec.get("product_id"), rec.get("month_id"))
            self._index[key] = rec

        logger.info(
            f"StrategicMemoryEngine initialized. "
            f"Consolidated records: {len(self._index)}"
        )

    # =======================================================================
    # Monthly Consolidation — Item 73 / 74
    # =======================================================================

    def consolidate_month(
        self,
        product_id:           str,
        month_id:             str,
        baseline_version:     str,
        baseline_price:       float,
        rpm_final:            float,
        roas_final:           float,
        cac_final:            float,
        margin_final:         float,
        total_active_seconds: int,
        total_revenue:        float,
        total_ad_spend:       float,
        snapshot_reference:   str,
    ) -> dict:
        """
        Freeze and persist the performance data for product_id in month_id.

        Validations (in order):
          1. month_id format (YYYY-MM regex)
          2. month_id is not in the future
          3. (product_id, month_id) not already consolidated

        Raises: InvalidMonthIdError, MonthAlreadyConsolidatedError
        Emits:  monthly_consolidated
        Returns: consolidated record (dict)
        """
        pid = str(product_id)
        mid = str(month_id)

        # --- Validate format ---
        self._validate_month_id(mid)

        # --- Validate not already consolidated ---
        key = (pid, mid)
        if key in self._index:
            raise MonthAlreadyConsolidatedError(
                f"Product '{pid}' month '{mid}' has already been consolidated "
                f"(consolidated_at={self._index[key]['consolidated_at']}). "
                f"Closed months are immutable — no recalculation permitted."
            )

        now = self._now()
        record = {
            "product_id":           pid,
            "month_id":             mid,
            "baseline_version":     str(baseline_version),
            "baseline_price":       float(baseline_price),
            "rpm_final":            float(rpm_final),
            "roas_final":           float(roas_final),
            "cac_final":            float(cac_final),
            "margin_final":         float(margin_final),
            "total_active_seconds": int(total_active_seconds),
            "total_revenue":        float(total_revenue),
            "total_ad_spend":       float(total_ad_spend),
            "snapshot_reference":   str(snapshot_reference),
            "consolidated_at":      now.isoformat(),
        }

        # Persist first (append-only), then update in-memory index
        self._pers.append_record(record)
        self._index[key] = record

        self.orchestrator.emit_event(
            event_type="monthly_consolidated",
            product_id=pid,
            payload={
                "product_id":         pid,
                "month_id":           mid,
                "baseline_version":   record["baseline_version"],
                "baseline_price":     record["baseline_price"],
                "rpm_final":          record["rpm_final"],
                "roas_final":         record["roas_final"],
                "margin_final":       record["margin_final"],
                "total_revenue":      record["total_revenue"],
                "snapshot_reference": record["snapshot_reference"],
                "consolidated_at":    record["consolidated_at"],
            },
            source="system",
        )
        logger.info(
            f"Month consolidated: product='{pid}' month='{mid}' "
            f"revenue={total_revenue} roas={roas_final}"
        )
        return record

    # =======================================================================
    # Immutability Guards — Item 76 / 75
    # =======================================================================

    def reopen_month(self, product_id: str, month_id: str) -> None:
        """Always raises StrategicMemoryImmutableError."""
        raise StrategicMemoryImmutableError(
            f"reopen_month() is permanently forbidden. "
            f"Consolidated month '{month_id}' for product='{product_id}' "
            f"is sealed and immutable. No reopening permitted."
        )

    def update_consolidation(self, product_id: str, month_id: str, **kwargs) -> None:
        """Always raises StrategicMemoryImmutableError."""
        raise StrategicMemoryImmutableError(
            f"update_consolidation() is permanently forbidden. "
            f"Month '{month_id}' for product='{product_id}' cannot be updated. "
            f"All monthly records are append-only."
        )

    def reprocess_metrics(self, product_id: str, month_id: str) -> None:
        """Always raises StrategicMemoryImmutableError."""
        raise StrategicMemoryImmutableError(
            f"reprocess_metrics() is permanently forbidden. "
            f"Retroactive recalculation of month '{month_id}' for "
            f"product='{product_id}' violates strategic memory integrity."
        )

    # =======================================================================
    # Read-only accessors
    # =======================================================================

    def get_record(self, product_id: str, month_id: str) -> dict | None:
        return self._index.get((str(product_id), str(month_id)))

    def get_all_records(self, product_id: str | None = None) -> list[dict]:
        """Return all consolidated records, optionally filtered by product_id."""
        all_recs = list(self._index.values())
        if product_id is not None:
            all_recs = [r for r in all_recs if r["product_id"] == str(product_id)]
        return all_recs

    def is_consolidated(self, product_id: str, month_id: str) -> bool:
        return (str(product_id), str(month_id)) in self._index

    # =======================================================================
    # Validation
    # =======================================================================

    def _validate_month_id(self, month_id: str) -> None:
        """
        Raise InvalidMonthIdError if month_id is:
          - Not matching YYYY-MM
          - Referring to a future month
        """
        if not _MONTH_RE.match(month_id):
            raise InvalidMonthIdError(
                f"month_id '{month_id}' is invalid. "
                f"Required format: YYYY-MM (e.g. '2026-02'). "
                f"Only past or current months may be consolidated."
            )

        now = self._now()
        current_ym = now.strftime("%Y-%m")
        if month_id > current_ym:
            raise InvalidMonthIdError(
                f"month_id '{month_id}' is in the future "
                f"(current month: '{current_ym}'). "
                f"Only past or current months may be consolidated."
            )
