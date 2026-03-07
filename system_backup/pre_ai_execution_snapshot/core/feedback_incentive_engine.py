"""
core/feedback_incentive_engine.py — B3 / Bloco 27: Feedback Incentivado Engine

Classification: Operational Subordinate — ZERO executive authority.

Responsibilities:
  • Track engagement per product+user and emit feedback_requested when triggered
  • Validate submitted feedback text (≥ 50 characters)
  • Grant lifetime upgrade after validated feedback
  • Revoke lifetime upgrade automatically when A10 refund_completed fires

Prohibitions (absolute):
  ✗ Does NOT create products
  ✗ Does NOT initiate betas
  ✗ Does NOT alter Score_Global / GlobalState
  ✗ Does NOT alter pricing or market cycles
  ✗ Does NOT promote versions (A8 handles that)
  ✗ Does NOT write outside the Orchestrator path

Subordination chain:
  Orchestrator → FeedbackIncentiveEngine → EventBus
  A10 refund_completed → Orchestrator → revoke_lifetime_upgrade()

Engagement trigger:
  engagement_ratio = engagement_value / engagement_metric_total
  if ratio ≥ engagement_threshold (default 0.30) → emit feedback_requested
  Extra guard for usage_time: also requires tempo_real ≥ 300 seconds

Feedback validation:
  text ≥ 50 chars → feedback_submitted + feedback_validated
  text < 50 chars → feedback_rejected_invalid

Lifetime upgrade:
  Granted after feedback_validated → lifetime_upgrade_granted
  Revoked on refund_completed     → lifetime_upgrade_revoked + access_revoked
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("FeedbackIncentiveEngine")

# Constants
ENGAGEMENT_THRESHOLD_DEFAULT = 0.30
USAGE_TIME_MIN_SECONDS       = 300
FEEDBACK_MIN_CHARS           = 50

VALID_METRIC_TYPES = {
    "module_progress",
    "usage_time",
    "execution_count",
    "custom",
}


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class FeedbackDirectExecutionError(Exception):
    """Raised when code attempts to call engine methods directly (outside Orchestrator)."""

class FeedbackConfigurationError(Exception):
    """Raised when product configuration is invalid (caught during Orchestrator validation)."""

class FeedbackEngineVersionPromotionError(Exception):
    """Raised if any code path attempts to promote a version from inside this engine."""


# ---------------------------------------------------------------------------
# Product Configuration
# ---------------------------------------------------------------------------

class FeedbackProductConfig:
    """
    Per-product configuration for the feedback incentive flow.

    Validated before any evaluation:
      engagement_metric_total > 0
      0 < engagement_threshold ≤ 1
    """
    __slots__ = (
        "product_id",
        "engagement_metric_type",
        "engagement_metric_total",
        "engagement_threshold",
    )

    def __init__(
        self,
        product_id:              str,
        engagement_metric_type:  str,
        engagement_metric_total: float,
        engagement_threshold:    float = ENGAGEMENT_THRESHOLD_DEFAULT,
    ):
        if engagement_metric_type not in VALID_METRIC_TYPES:
            raise FeedbackConfigurationError(
                f"Invalid engagement_metric_type='{engagement_metric_type}'. "
                f"Must be one of {sorted(VALID_METRIC_TYPES)}."
            )
        if engagement_metric_total <= 0:
            raise FeedbackConfigurationError(
                f"engagement_metric_total must be > 0, got {engagement_metric_total}."
            )
        if not (0 < engagement_threshold <= 1):
            raise FeedbackConfigurationError(
                f"engagement_threshold must be in (0, 1], got {engagement_threshold}."
            )
        self.product_id              = str(product_id)
        self.engagement_metric_type  = engagement_metric_type
        self.engagement_metric_total = float(engagement_metric_total)
        self.engagement_threshold    = float(engagement_threshold)


# ---------------------------------------------------------------------------
# Feedback Incentive Engine
# ---------------------------------------------------------------------------

class FeedbackIncentiveEngine:
    """
    B3 / Bloco 27 — Feedback Incentivado Engine.

    All mutations are emitted exclusively as EventBus events and persisted
    in append-only JSON-Lines format. No direct state writes permitted.
    """

    def __init__(self, orchestrator, persistence, now_fn=None):
        self.orchestrator = orchestrator
        self._pers       = persistence
        self._now     = now_fn or (lambda: datetime.now(timezone.utc))
        all_records   = persistence.load()
        self._records = list(all_records)

        # In-memory index: (user_id, product_id) → grant record
        self._grants: dict[tuple, dict] = {}
        for r in self._records:
            if r.get("event_type") == "lifetime_upgrade_granted":
                key = (r["user_id"], r["product_id"])
                self._grants[key] = r
            elif r.get("event_type") == "lifetime_upgrade_revoked":
                key = (r["user_id"], r["product_id"])
                self._grants.pop(key, None)

        logger.info(
            f"FeedbackIncentiveEngine initialized. "
            f"Total records: {len(self._records)}, "
            f"Active lifetime grants: {len(self._grants)}"
        )

    # ==================================================================
    # INTERNAL HELPERS
    # ==================================================================

    def _write(self, record: dict) -> None:
        """Persist record (append-only) and emit matching event via Orchestrator."""
        self._pers.append(record)
        self._records.append(record)
        self.orchestrator.emit_event(
            event_type=record["event_type"],
            product_id=record.get("product_id"),
            user_id=record.get("user_id"),
            payload=record,
            source="system",
        )

    # ==================================================================
    # 1. ENGAGEMENT EVALUATION
    # ==================================================================

    def evaluate_engagement(
        self,
        *,
        config:           FeedbackProductConfig,
        user_id:          str,
        engagement_value: float,
        tempo_real:       float = 0.0,
    ) -> dict:
        """
        Evaluate a user's engagement and emit feedback_requested if threshold met.

        Returns a dict with keys: triggered, engagement_ratio, reason.

        Special rule for usage_time:
          trigger only if ratio ≥ threshold AND tempo_real ≥ 300 seconds.
        """
        pid       = config.product_id
        uid       = str(user_id)
        now       = self._now()
        event_id  = str(uuid.uuid4())

        ratio    = round(engagement_value / config.engagement_metric_total, 6)
        passed   = ratio >= config.engagement_threshold
        reason   = None

        # usage_time extra guard
        if passed and config.engagement_metric_type == "usage_time":
            if tempo_real < USAGE_TIME_MIN_SECONDS:
                passed = False
                reason = (
                    f"usage_time blindagem: tempo_real={tempo_real}s "
                    f"< {USAGE_TIME_MIN_SECONDS}s required"
                )

        if not passed and reason is None:
            reason = (
                f"engagement_ratio={ratio} "
                f"< threshold={config.engagement_threshold}"
            )

        result = {
            "event_id":         event_id,
            "product_id":       pid,
            "user_id":          uid,
            "timestamp":        now.isoformat(),
            "event_type":       "engagement_evaluated",
            "engagement_ratio": ratio,
            "triggered":        passed,
            "reason":           reason,
            "metadata": {
                "metric_type":        config.engagement_metric_type,
                "metric_total":       config.engagement_metric_total,
                "engagement_value":   engagement_value,
                "threshold":          config.engagement_threshold,
                "tempo_real":         tempo_real,
            },
        }
        self._write(result)

        if passed:
            trigger_record = {
                "event_id":   str(uuid.uuid4()),
                "product_id": pid,
                "user_id":    uid,
                "timestamp":  now.isoformat(),
                "event_type": "feedback_requested",
                "metadata":   {"engagement_ratio": ratio},
            }
            self._write(trigger_record)
            logger.info(
                f"[B3] feedback_requested for user='{uid}' product='{pid}' "
                f"ratio={ratio}"
            )
        else:
            logger.info(
                f"[B3] No trigger for user='{uid}' product='{pid}': {reason}"
            )

        return {
            "triggered":        passed,
            "engagement_ratio": ratio,
            "reason":           reason,
            "event_id":         event_id,
        }

    # ==================================================================
    # 2. FEEDBACK VALIDATION
    # ==================================================================

    def submit_feedback(
        self,
        *,
        user_id:     str,
        product_id:  str,
        feedback_text: str,
    ) -> dict:
        """
        Validate submitted feedback text.

        Returns dict with keys: valid, reason.

        If text ≥ 50 chars → emit feedback_submitted + feedback_validated.
        If text < 50 chars  → emit feedback_rejected_invalid.
        """
        pid      = str(product_id)
        uid      = str(user_id)
        now      = self._now()
        text_len = len(feedback_text.strip())
        valid    = text_len >= FEEDBACK_MIN_CHARS

        if valid:
            # Emit submitted
            self._write({
                "event_id":   str(uuid.uuid4()),
                "product_id": pid,
                "user_id":    uid,
                "timestamp":  now.isoformat(),
                "event_type": "feedback_submitted",
                "metadata": {
                    "text_length": text_len,
                },
            })

            # Emit validated
            val_id = str(uuid.uuid4())
            self._write({
                "event_id":   val_id,
                "product_id": pid,
                "user_id":    uid,
                "timestamp":  now.isoformat(),
                "event_type": "feedback_validated",
                "metadata": {
                    "text_length": text_len,
                },
            })

            logger.info(
                f"[B3] Feedback validated for user='{uid}' product='{pid}' "
                f"text_length={text_len}"
            )
            return {"valid": True, "reason": None}
        else:
            self._write({
                "event_id":   str(uuid.uuid4()),
                "product_id": pid,
                "user_id":    uid,
                "timestamp":  now.isoformat(),
                "event_type": "feedback_rejected_invalid",
                "metadata": {
                    "text_length": text_len,
                    "reason": (
                        f"text_length={text_len} < {FEEDBACK_MIN_CHARS} chars required"
                    ),
                },
            })

            logger.warning(
                f"[B3] Feedback rejected for user='{uid}' product='{pid}': "
                f"text_length={text_len} < {FEEDBACK_MIN_CHARS}"
            )
            return {
                "valid": False,
                "reason": f"text_length={text_len} < {FEEDBACK_MIN_CHARS} chars required",
            }

    # ==================================================================
    # 3. LIFETIME UPGRADE GRANT
    # ==================================================================

    def grant_lifetime_upgrade(
        self,
        *,
        user_id:    str,
        product_id: str,
        metadata:   dict | None = None,
    ) -> dict:
        """
        Grant permanent access to this product and future A8-promoted versions.

        Does NOT:
          • Promote version
          • Create candidate_version
          • Alter baseline
          • Execute any structural upgrade

        Emits: lifetime_upgrade_granted
        Returns: the grant record dict.
        """
        pid      = str(product_id)
        uid      = str(user_id)
        now      = self._now()
        event_id = str(uuid.uuid4())

        grant = {
            "event_id":   event_id,
            "product_id": pid,
            "user_id":    uid,
            "timestamp":  now.isoformat(),
            "event_type": "lifetime_upgrade_granted",
            "metadata":   metadata or {},
        }

        key = (uid, pid)
        self._grants[key] = grant
        self._write(grant)

        logger.info(
            f"[B3] lifetime_upgrade_granted for user='{uid}' product='{pid}'"
        )
        return grant

    # ==================================================================
    # 4. LIFETIME UPGRADE REVOCATION (A10 integration)
    # ==================================================================

    def revoke_lifetime_upgrade(
        self,
        *,
        user_id:    str,
        product_id: str,
        reason:     str = "refund_completed",
    ) -> bool:
        """
        Revoke lifetime upgrade on refund_completed from A10.

        Emits: lifetime_upgrade_revoked + access_revoked (if grant existed).
        Returns: True if a grant was active and revoked, False otherwise.
        """
        pid = str(product_id)
        uid = str(user_id)
        now = self._now()
        key = (uid, pid)

        if key not in self._grants:
            logger.info(
                f"[B3] No active lifetime grant for user='{uid}' product='{pid}'. "
                f"Nothing to revoke."
            )
            return False

        del self._grants[key]

        # Emit revocation
        self._write({
            "event_id":   str(uuid.uuid4()),
            "product_id": pid,
            "user_id":    uid,
            "timestamp":  now.isoformat(),
            "event_type": "lifetime_upgrade_revoked",
            "metadata":   {"reason": reason},
        })

        # Emit access_revoked (A10 symmetry)
        self._write({
            "event_id":   str(uuid.uuid4()),
            "product_id": pid,
            "user_id":    uid,
            "timestamp":  now.isoformat(),
            "event_type": "access_revoked",
            "metadata":   {"reason": reason, "source": "B3_revoke"},
        })

        logger.warning(
            f"[B3] lifetime_upgrade_revoked for user='{uid}' product='{pid}' "
            f"reason='{reason}'"
        )
        return True

    # ==================================================================
    # Read-only helpers
    # ==================================================================

    def has_lifetime_grant(self, user_id: str, product_id: str) -> bool:
        """Return True if user has an active (non-revoked) lifetime upgrade."""
        return (str(user_id), str(product_id)) in self._grants

    def get_all_records(
        self, user_id: str | None = None, product_id: str | None = None
    ) -> list[dict]:
        """Return records optionally filtered by user_id and/or product_id."""
        recs = list(self._records)
        if user_id    is not None: recs = [r for r in recs if r.get("user_id")    == str(user_id)]
        if product_id is not None: recs = [r for r in recs if r.get("product_id") == str(product_id)]
        return recs

    # ==================================================================
    # Execution guards
    # ==================================================================

    def promote_version_directly(self, *args, **kwargs) -> None:
        """Always raises. Version promotion belongs to A8 via Orchestrator."""
        raise FeedbackEngineVersionPromotionError(
            "promote_version_directly() is permanently forbidden in B3. "
            "Version promotion is handled exclusively by A8 (VersionManager) "
            "triggered by a human action via the Orchestrator."
        )

    @staticmethod
    def execute_directly(*args, **kwargs) -> None:
        """Always raises FeedbackDirectExecutionError."""
        raise FeedbackDirectExecutionError(
            "execute_directly() is permanently forbidden. "
            "All FeedbackIncentiveEngine operations must be routed through "
            "Orchestrator.receive_event('feedback_evaluation_requested', ...)."
        )
