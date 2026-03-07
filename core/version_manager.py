"""
core/version_manager.py — A8 Version Manager (Governed)

Controls baseline and candidate versions per product with:
  - Only 1 candidate_version per product at a time.
  - baseline_version never overwritten (preserved in append-only history).
  - Promotion requires a formal event AND a linked Telemetry snapshot.
  - Rollback restores previous baseline + metrics snapshot + price.
  - Full immutable audit trail.
  - No direct writes.
"""
import copy
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("VersionManager")


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class VersionCandidateExistsError(Exception):
    """Raised when a second candidate is created before the first is resolved."""

class BaselineSnapshotMissingError(Exception):
    """Raised when promotion is attempted without a valid linked snapshot_id."""

class VersionPromotionPreconditionError(Exception):
    """Raised when promotion preconditions are not met (no candidate, etc.)."""

class NoPreviousBaselineError(Exception):
    """Raised when rollback is attempted but no previous baseline exists."""

class VersionContainmentError(Exception):
    """Raised when a version operation is blocked due to CONTENÇÃO_FINANCEIRA."""

class DeprecatedVersionFlowError(Exception):
    """
    Raised when legacy direct promotion/rollback methods are called.
    All version mutations must flow through Orchestrator.receive_event().
    """

class VersionPromotionViolationError(Exception):
    """
    Raised when promote_candidate() preconditions are not met:
      - no candidate exists
      - snapshot_id not provided or not found
      - system in CONTENÇÃO_FINANCEIRA
      - financial_alert_active == True
    """

class VersionPromotionOutsideOrchestratorError(Exception):
    """
    Raised when promote_candidate() or rollback_to_previous_baseline()
    is called directly without passing through Orchestrator.receive_event().
    Pass orchestrated=True only from Orchestrator service handlers.
    """


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class VersionManager:
    """
    Governed version control per product.

    State schema (per product):
    {
      "product_id":                  str,
      "baseline_version":            str | None,
      "baseline_metrics_snapshot_id": str | None,
      "candidate_version":           str | None,
      "version_history": [
        {
          "version_id":          str,
          "type":                "BASELINE" | "CANDIDATE" | "ROLLED_BACK",
          "linked_snapshot_id":  str | None,
          "linked_price":        float | None,
          "timestamp":           ISO8601
        },
        ...
      ]
    }
    """

    def __init__(self, persistence=None, snapshot_store=None, now_fn=None):
        """
        Parameters
        ----------
        persistence    : VersionPersistence duck type (load/save)
        snapshot_store : Optional object with exists(snapshot_id) → bool
                         for validating that snapshot IDs actually exist.
        now_fn         : Injectable clock for deterministic tests.
        """
        self._persistence     = persistence
        self._snapshot_store  = snapshot_store
        self._now             = now_fn or (lambda: datetime.now(timezone.utc))

        raw = {}
        if persistence:
            raw = persistence.load()

        # Support both old schema {"versions": {...}} and new flat schema {product: {...}}
        if "versions" in raw and isinstance(raw["versions"], dict):
            self._versions: dict = raw["versions"]
        else:
            self._versions: dict = raw if isinstance(raw, dict) else {}

        logger.info(f"VersionManager initialized. Products tracked: {list(self._versions.keys())}")

    # =======================================================================
    # Public API
    # =======================================================================

    def create_candidate(
        self,
        product_id:  str,
        version_id:  str | None = None,
        snapshot_id: str | None = None,
        linked_price: float | None = None,
        orchestrator = None,
    ) -> dict:
        """
        Register a new candidate version for a product.

        Raises VersionCandidateExistsError if one already exists.
        Emits: candidate_version_created
        """
        self._ensure_product(product_id)
        slot = self._versions[product_id]

        if slot["candidate_version"] is not None:
            raise VersionCandidateExistsError(
                f"Product '{product_id}' already has an active candidate "
                f"(id={slot['candidate_version']}). "
                f"Promote or discard it before creating another."
            )

        vid = version_id or str(uuid.uuid4())
        now = self._now()

        entry = {
            "version_id":         vid,
            "type":               "CANDIDATE",
            "linked_snapshot_id": snapshot_id,
            "linked_price":       linked_price,
            "timestamp":          now.isoformat(),
        }
        slot["candidate_version"] = vid
        slot["version_history"].append(entry)
        self._save()

        if orchestrator:
            orchestrator.emit_event(
                event_type="candidate_version_created",
                payload={
                    "version_id":         vid,
                    "linked_snapshot_id": snapshot_id,
                    "linked_price":       linked_price,
                    "created_at":         now.isoformat(),
                },
                source="VersionManager",
                product_id=product_id
            )
        logger.info(f"Candidate version '{vid}' created for '{product_id}'.")
        return entry

    # -----------------------------------------------------------------------

    def promote_candidate(
        self,
        product_id:           str,
        snapshot_id:          str,
        linked_price:         float | None = None,
        orchestrator         = None,
        global_state          = None,
        financial_alert_active: bool       = False,
        orchestrated:         bool         = False,
    ) -> dict:
        """
        Promote the current candidate to baseline.

        CONSTITUTIONAL PRECONDITIONS (all must hold simultaneously):
          1. orchestrated=True  — must be called from Orchestrator._sh_version_promote()
          2. candidate_version exists
          3. snapshot_id provided and (if snapshot_store configured) exists
          4. GlobalState != CONTENÇÃO_FINANCEIRA
          5. financial_alert_active == False

        The previous baseline is preserved in version_history (never deleted).
        Emits: version_promoted
        Raises: VersionPromotionOutsideOrchestratorError, VersionPromotionViolationError,
                VersionContainmentError (kept for backwards compat), BaselineSnapshotMissingError
        """
        from core.global_state import CONTENCAO_FINANCEIRA

        # --- Guard 0: Orchestrator context ---
        if not orchestrated:
            raise VersionPromotionOutsideOrchestratorError(
                f"Product '{product_id}': promote_candidate() called outside Orchestrator context. "
                f"All version promotions must flow through "
                f"Orchestrator.receive_event('version_promotion_requested', ...)."
            )

        # --- Guard 1: Financial containment ---
        if global_state and global_state.get_state() == CONTENCAO_FINANCEIRA:
            raise VersionPromotionViolationError(
                f"Product '{product_id}': version promotion blocked — "
                f"system in CONTENÇÃO_FINANCEIRA."
            )

        # --- Guard 2: Financial alert ---
        if financial_alert_active:
            raise VersionPromotionViolationError(
                f"Product '{product_id}': version promotion blocked — "
                f"financial_alert_active=True. Resolve financial alerts before promoting."
            )

        self._ensure_product(product_id)
        slot = self._versions[product_id]

        # --- Guard 3: Candidate must exist ---
        if slot["candidate_version"] is None:
            raise VersionPromotionViolationError(
                f"Product '{product_id}': no candidate version to promote. "
                f"Call create_candidate() first."
            )

        # --- Guard 4: snapshot_id required ---
        if not snapshot_id:
            raise VersionPromotionViolationError(
                f"Product '{product_id}': promotion requires a valid "
                f"snapshot_id linked to a TelemetryEngine snapshot."
            )

        if self._snapshot_store and not self._snapshot_store.exists(snapshot_id):
            raise VersionPromotionViolationError(
                f"Product '{product_id}': snapshot '{snapshot_id}' does not exist "
                f"in the snapshot store. Cannot promote without a valid telemetry snapshot."
            )

        now              = self._now()
        old_baseline_vid = slot["baseline_version"]
        candidate_vid    = slot["candidate_version"]

        # Archive old baseline in history as ROLLED_BACK reference (never deleted)
        if old_baseline_vid is not None:
            slot["version_history"].append({
                "version_id":         old_baseline_vid,
                "type":               "ROLLED_BACK",
                "linked_snapshot_id": slot["baseline_metrics_snapshot_id"],
                "linked_price":       None,
                "timestamp":          now.isoformat(),
            })

        # Promote candidate → baseline
        slot["baseline_version"]             = candidate_vid
        slot["baseline_metrics_snapshot_id"] = snapshot_id
        slot["candidate_version"]            = None   # candidate consumed

        new_entry = {
            "version_id":         candidate_vid,
            "type":               "BASELINE",
            "linked_snapshot_id": snapshot_id,
            "linked_price":       linked_price,
            "timestamp":          now.isoformat(),
        }
        slot["version_history"].append(new_entry)
        self._save()

        if orchestrator:
            orchestrator.emit_event(
                event_type="version_promoted",
                payload={
                    "new_baseline_version":    candidate_vid,
                    "old_baseline_version":    old_baseline_vid,
                    "snapshot_id":             snapshot_id,
                    "linked_price":            linked_price,
                    "promoted_at":             now.isoformat(),
                },
                source="VersionManager",
                product_id=product_id
            )
        logger.info(
            f"Version '{candidate_vid}' promoted to baseline for '{product_id}'. "
            f"Snapshot: {snapshot_id}. Old baseline: {old_baseline_vid}."
        )
        return new_entry

    # -----------------------------------------------------------------------

    def rollback_to_previous_baseline(
        self,
        product_id:   str,
        orchestrator = None,
        orchestrated: bool = False,
    ) -> dict:
        """
        Restore the previous baseline from history.

        Requires orchestrated=True — must be called via
        Orchestrator.receive_event('version_rollback_requested', ...).

        - Invalidates the current candidate (if any).
        - Restores: baseline_version, baseline_metrics_snapshot_id, linked_price.
        - History is never deleted (old baseline entry kept as ROLLED_BACK).

        Emits: version_rollback_executed
        Raises: VersionPromotionOutsideOrchestratorError, NoPreviousBaselineError
        """
        if not orchestrated:
            raise VersionPromotionOutsideOrchestratorError(
                f"Product '{product_id}': rollback_to_previous_baseline() called outside "
                f"Orchestrator context. All rollbacks must flow through "
                f"Orchestrator.receive_event('version_rollback_requested', ...)."
            )
        self._ensure_product(product_id)
        slot = self._versions[product_id]
        now  = self._now()

        # Find the most recent BASELINE entry in history (i.e., the prior baseline)
        prior = self._find_previous_baseline(slot["version_history"], slot["baseline_version"])
        if prior is None:
            raise NoPreviousBaselineError(
                f"Product '{product_id}': no previous baseline to rollback to."
            )

        # Archive current baseline as an explicit ROLLED_BACK marker
        if slot["baseline_version"]:
            slot["version_history"].append({
                "version_id":         slot["baseline_version"],
                "type":               "ROLLED_BACK",
                "linked_snapshot_id": slot["baseline_metrics_snapshot_id"],
                "linked_price":       None,
                "timestamp":          now.isoformat(),
            })

        # Restore prior baseline
        slot["baseline_version"]             = prior["version_id"]
        slot["baseline_metrics_snapshot_id"] = prior["linked_snapshot_id"]
        slot["candidate_version"]            = None   # invalidate candidate

        self._save()

        if orchestrator:
            orchestrator.emit_event(
                event_type="version_rollback_executed",
                payload={
                    "restored_version":    prior["version_id"],
                    "restored_snapshot_id": prior["linked_snapshot_id"],
                    "restored_price":      prior.get("linked_price"),
                    "rolled_back_at":      now.isoformat(),
                },
                source="VersionManager",
                product_id=product_id
            )
        logger.info(
            f"Version rollback for '{product_id}': restored '{prior['version_id']}' "
            f"(snapshot={prior['linked_snapshot_id']})."
        )
        return prior

    # -----------------------------------------------------------------------
    # DEPRECATED — Legacy direct promotion/rollback (formerly for MarketLoopEngine)
    # -----------------------------------------------------------------------

    def promote_version(self, product_id: str, event_bus=None) -> dict:
        """
        DEPRECATED — raises DeprecatedVersionFlowError unconditionally.

        All version promotions must flow through:
          Orchestrator.receive_event('version_promotion_requested', payload={...})

        Migration path:
          1. Call Orchestrator.receive_event('candidate_version_requested', ...)
          2. Call Orchestrator.receive_event('version_promotion_requested', ...)
        """
        raise DeprecatedVersionFlowError(
            f"promote_version() is permanently forbidden for product '{product_id}'. "
            "Direct version promotion bypasses snapshot validation, containment checks, "
            "and the Orchestrator governance layer. "
            "Use Orchestrator.receive_event('version_promotion_requested', "
            "{\"product_id\": product_id, \"snapshot_id\": snapshot_id, ...}) instead."
        )

    def rollback_version(self, product_id: str, event_bus=None) -> dict:
        """
        DEPRECATED — raises DeprecatedVersionFlowError unconditionally.

        All rollbacks must flow through:
          Orchestrator.receive_event('version_rollback_requested', payload={...})
        """
        raise DeprecatedVersionFlowError(
            f"rollback_version() is permanently forbidden for product '{product_id}'. "
            "Direct rollback bypasses Orchestrator governance. "
            "Use Orchestrator.receive_event('version_rollback_requested', "
            "{\"product_id\": product_id}) instead."
        )

    # -----------------------------------------------------------------------
    # Read-only accessors
    # -----------------------------------------------------------------------

    def get_candidate(self, product_id: str) -> str | None:
        return self._versions.get(product_id, {}).get("candidate_version")

    def get_baseline(self, product_id: str) -> str | None:
        return self._versions.get(product_id, {}).get("baseline_version")

    def get_record(self, product_id: str) -> dict | None:
        return self._versions.get(product_id)

    def get_history(self, product_id: str) -> list:
        return list(self._versions.get(product_id, {}).get("version_history", []))

    # =======================================================================
    # Internal helpers
    # =======================================================================

    def _ensure_product(self, product_id: str) -> None:
        if product_id not in self._versions:
            self._versions[product_id] = {
                "product_id":                  product_id,
                "baseline_version":             None,
                "baseline_metrics_snapshot_id": None,
                "candidate_version":            None,
                "version_history":              [],
            }

    def _find_previous_baseline(self, history: list, current_baseline_id: str | None) -> dict | None:
        """
        Walk history in reverse and return the last BASELINE entry
        that is NOT the current baseline.
        """
        for entry in reversed(history):
            if entry.get("type") == "BASELINE" and entry.get("version_id") != current_baseline_id:
                return entry
        return None

    def _save(self) -> None:
        if self._persistence:
            self._persistence.save(self._versions)
