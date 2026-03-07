"""
core/snapshot_manager.py — Snapshot & Rollback
All snapshots are append-only. Rollback generates a new snapshot record.
"""
import copy
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("SnapshotManager")


class SnapshotManager:
    """
    Manages product snapshots in an append-only store.
    Snapshots are never deleted or overwritten.
    Rollback creates a new snapshot based on a previous one.
    """

    def __init__(self, orchestrator, snapshot_persistence):
        self.orchestrator = orchestrator
        self._persistence = snapshot_persistence

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_snapshot(
        self,
        product_id: str,
        metrics: dict,
        state: str,
        price: float | None,
        active_version: str | None,
    ) -> dict:
        """
        Create a snapshot of the current product state.
        Appends snapshot_created event to the ledger.
        """
        snapshot = {
            "snapshot_id":     str(uuid.uuid4()),
            "product_id":      str(product_id),
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "state":           state,
            "metrics":         copy.deepcopy(metrics),
            "price":           price,
            "active_version":  active_version,
            "restored_from":   None,
        }

        self._persistence.append(snapshot)

        self.orchestrator.emit_event(
            event_type="snapshot_created",
            product_id=str(product_id),
            payload={"snapshot_id": snapshot["snapshot_id"]},
            source="system",
        )

        logger.info(
            f"Snapshot {snapshot['snapshot_id'][:8]}... created "
            f"for product '{product_id}' (state={state})."
        )
        return snapshot

    def restore_snapshot(
        self,
        product_id: str,
        snapshot_id: str,
    ) -> dict:
        """
        Restore from a previous snapshot.
        Creates a NEW snapshot record (never deletes history).
        Appends rollback_executed event to the ledger.
        """
        target = self._find_snapshot(product_id, snapshot_id)
        if not target:
            raise ValueError(
                f"Snapshot '{snapshot_id}' not found for product '{product_id}'."
            )

        restore_record = {
            "snapshot_id":    str(uuid.uuid4()),
            "product_id":     str(product_id),
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "state":          target["state"],
            "metrics":        copy.deepcopy(target["metrics"]),
            "price":          target["price"],
            "active_version": target["active_version"],
            "restored_from":  snapshot_id,
        }

        self._persistence.append(restore_record)

        self.orchestrator.emit_event(
            event_type="rollback_executed",
            product_id=str(product_id),
            payload={
                "new_snapshot_id":  restore_record["snapshot_id"],
                "restored_from":    snapshot_id,
            },
            source="system",
        )

        logger.info(
            f"Rollback to '{snapshot_id[:8]}...' executed for product '{product_id}'. "
            f"New snapshot: {restore_record['snapshot_id'][:8]}..."
        )
        return restore_record

    def list_snapshots(self, product_id: str) -> list:
        """Return all snapshots for a product."""
        return [
            s for s in self._persistence.load()
            if s.get("product_id") == str(product_id)
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _find_snapshot(self, product_id: str, snapshot_id: str) -> dict | None:
        for s in self._persistence.load():
            if (s.get("product_id") == str(product_id)
                    and s.get("snapshot_id") == snapshot_id):
                return s
        return None
