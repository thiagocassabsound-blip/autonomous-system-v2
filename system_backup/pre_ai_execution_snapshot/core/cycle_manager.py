"""
core/cycle_manager.py — Formal Business Cycle Manager
One open cycle per product. Closure is irreversible.
Metrics become immutable once a cycle is closed.
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("CycleManager")


class CycleAlreadyOpenError(Exception):
    """Raised when opening a cycle while one is already open for the product."""


class CycleNotFoundError(Exception):
    """Raised when no open cycle exists for the requested product."""


class CycleManager:
    """
    Governs formal business cycles per product.

    Rules:
    - Only 1 open cycle per product at a time.
    - Closure is irreversible.
    - Emits cycle_closed to the formal ledger on closure.
    - Closed cycle records are kept in history permanently.
    """

    def __init__(self, persistence=None):
        self._persistence = persistence
        data = {}
        if persistence:
            data = persistence.load()

        self._open_cycles: dict = data.get("open_cycles", {})   # product_id → cycle
        self._history: list     = data.get("history", [])

        logger.info(
            f"CycleManager initialized. "
            f"Open: {len(self._open_cycles)}. History: {len(self._history)}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def open_cycle(self, product_id: str, orchestrator) -> dict:
        """
        Open a new formal cycle for a product.
        Raises CycleAlreadyOpenError if one is already open.
        """
        product_id = str(product_id)

        if product_id in self._open_cycles:
            existing = self._open_cycles[product_id]
            raise CycleAlreadyOpenError(
                f"Product '{product_id}' already has an open cycle "
                f"({existing['cycle_id']}). Close it before opening a new one."
            )

        cycle = {
            "cycle_id":        str(uuid.uuid4()),
            "product_id":      product_id,
            "start_timestamp": datetime.now(timezone.utc).isoformat(),
            "end_timestamp":   None,
            "status":          "open",
        }

        self._open_cycles[product_id] = cycle
        self._save()

        orchestrator.emit_event(
            event_type="cycle_opened",
            payload={"cycle_id": cycle["cycle_id"]},
            source="CycleManager",
            product_id=product_id
        )

        logger.info(
            f"Cycle {cycle['cycle_id'][:8]}... opened for product '{product_id}'."
        )
        return cycle

    def close_cycle(self, product_id: str, orchestrator) -> dict:
        """
        Close the open cycle for a product.
        Raises CycleNotFoundError if no open cycle exists.
        Returns the closed cycle record.
        """
        product_id = str(product_id)
        cycle = self._open_cycles.get(product_id)

        if not cycle:
            raise CycleNotFoundError(
                f"No open cycle found for product '{product_id}'."
            )

        closed = dict(cycle)
        closed["end_timestamp"] = datetime.now(timezone.utc).isoformat()
        closed["status"]        = "closed"

        # Archive — permanent history
        self._history.append(closed)
        del self._open_cycles[product_id]
        self._save()

        orchestrator.emit_event(
            event_type="cycle_closed",
            payload={
                "cycle_id":        closed["cycle_id"],
                "start_timestamp": closed["start_timestamp"],
                "end_timestamp":   closed["end_timestamp"],
            },
            source="CycleManager",
            product_id=product_id
        )

        logger.info(
            f"Cycle {closed['cycle_id'][:8]}... closed for product '{product_id}'."
        )
        return closed

    def get_open_cycle(self, product_id: str) -> dict | None:
        """Return the currently open cycle, or None."""
        return self._open_cycles.get(str(product_id))

    def list_cycles(self, product_id: str) -> list:
        """Return all cycles (open + history) for a product, oldest first."""
        history = [c for c in self._history if c.get("product_id") == str(product_id)]
        open_c  = self._open_cycles.get(str(product_id))
        return history + ([open_c] if open_c else [])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if self._persistence:
            self._persistence.save({
                "open_cycles": self._open_cycles,
                "history":     self._history,
            })
