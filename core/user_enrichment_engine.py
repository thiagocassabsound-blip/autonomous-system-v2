"""
core/user_enrichment_engine.py — B4 / Bloco 28: User Enrichment Engine

Classification: Intelligence Subordinate — ZERO executive authority.

Consolidates economic and behavioral intelligence per user_id:
  • lifetime_value     = Σ payment_confirmed − Σ refund_completed
  • total_purchases    = count of valid payment_confirmed events
  • refund_ratio       = total_refunds / total_purchases (0 if no purchases)
  • dominant_channel   = channel with highest purchase frequency
  • device_profile     = dominant device by frequency or last confirmed
  • activity_recency   = days since last purchase (float)
  • risk_score         = 0–100 composite risk indicator
  • classification_tag = list of auto-generated strategic tags
  • export_signal_ready = True if eligible for C9 (signal only, no execution)

This engine:
  ✗ Does NOT alter Score_Global
  ✗ Does NOT alter GlobalState
  ✗ Does NOT alter budget / pricing
  ✗ Does NOT execute media
  ✗ Does NOT interfere with Radar
  ✗ Does NOT write outside the Orchestrator path
  ✓ Prepares export_signal_ready for future C9 integration (read-only flag)

Subordination: Orchestrator → UserEnrichmentEngine → EventBus + Persistence
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("UserEnrichmentEngine")

# Risk score contribution constants
RISK_HIGH_REFUND_RATIO  = 0.5   # +40
RISK_MED_REFUND_RATIO   = 0.3   # +20
RISK_SINGLE_PURCHASE    = 1     # +10 (total_purchases == 1)
RISK_REPEAT_NEGATIVE    = 3     # -20 (total_purchases >= 3)
RISK_RECENCY_DAYS       = 90    # +10 (activity_recency > 90 days)
RISK_LTV_ABOVE_AVG_BONUS = -10  # bonus if LTV above product average

# classification thresholds
HIGH_VALUE_MIN_LTV      = 100.0  # lifetime_value ≥ this → eligible for high_value_user
HIGH_VALUE_MAX_REFUND   = 0.2    # refund_ratio ≤ this   → eligible for high_value_user
EXPORT_SIGNAL_MAX_REFUND = 0.3   # refund_ratio ≤ this for repeat_buyer export


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class UserEnrichmentDirectExecutionError(Exception):
    """Raised when engine methods are invoked directly without Orchestrator routing."""


# ---------------------------------------------------------------------------
# Pure computation helpers
# ---------------------------------------------------------------------------

def compute_lifetime_value(payments: list[float], refunds: list[float]) -> float:
    """LTV = Σ payments − Σ refunds."""
    return round(sum(payments) - sum(refunds), 4)


def compute_refund_ratio(total_refunds: int, total_purchases: int) -> float:
    """refund_ratio = total_refunds / total_purchases, or 0 if no purchases."""
    if total_purchases <= 0:
        return 0.0
    return round(total_refunds / total_purchases, 6)


def compute_dominant_channel(channel_counts: dict[str, int]) -> str | None:
    """Return the channel with the highest purchase count."""
    if not channel_counts:
        return None
    return max(channel_counts, key=lambda k: channel_counts[k])


def compute_dominant_device(device_counts: dict[str, int]) -> str | None:
    """Return the device with the highest usage count."""
    if not device_counts:
        return None
    return max(device_counts, key=lambda k: device_counts[k])


def compute_activity_recency(last_purchase_ts: str | None, now: datetime) -> float:
    """
    activity_recency in days (float) since last purchase.
    Returns float('inf') if no purchase has been recorded.
    """
    if last_purchase_ts is None:
        return float("inf")
    try:
        last = datetime.fromisoformat(last_purchase_ts)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        delta = now - last
        return round(delta.total_seconds() / 86400.0, 4)
    except Exception:
        return float("inf")


def compute_risk_score(
    refund_ratio:     float,
    total_purchases:  int,
    lifetime_value:   float,
    activity_recency: float,
    avg_ltv_product:  float = 0.0,
) -> int:
    """
    Composite risk score 0–100 (higher = riskier).

    Rules:
      +40 if refund_ratio > 0.5
      +20 if refund_ratio > 0.3
      +10 if total_purchases == 1
      -20 if total_purchases >= 3
      -10 if lifetime_value above avg_ltv_product (and avg > 0)
      +10 if activity_recency > 90 days
    """
    score = 0
    if refund_ratio > RISK_HIGH_REFUND_RATIO:
        score += 40
    elif refund_ratio > RISK_MED_REFUND_RATIO:
        score += 20
    if total_purchases == RISK_SINGLE_PURCHASE:
        score += 10
    if total_purchases >= RISK_REPEAT_NEGATIVE:
        score -= 20
    if avg_ltv_product > 0 and lifetime_value > avg_ltv_product:
        score += RISK_LTV_ABOVE_AVG_BONUS   # -10
    if activity_recency > RISK_RECENCY_DAYS:
        score += 10
    return max(0, min(100, score))


def compute_classification_tags(
    lifetime_value:   float,
    refund_ratio:     float,
    total_purchases:  int,
    activity_recency: float,
    risk_score:       int,
) -> list[str]:
    """
    Generate strategic classification tags.

    Tags:
      "high_value_user"  — LTV ≥ threshold AND refund_ratio ≤ 0.2
      "repeat_buyer"     — total_purchases ≥ 3
      "high_refund_risk" — refund_ratio > 0.5
      "inactive_user"    — activity_recency > 90 days
      "stable_user"      — risk_score ≤ 30
    """
    tags: list[str] = []
    if lifetime_value >= HIGH_VALUE_MIN_LTV and refund_ratio <= HIGH_VALUE_MAX_REFUND:
        tags.append("high_value_user")
    if total_purchases >= 3:
        tags.append("repeat_buyer")
    if refund_ratio > RISK_HIGH_REFUND_RATIO:
        tags.append("high_refund_risk")
    if activity_recency > RISK_RECENCY_DAYS:
        tags.append("inactive_user")
    if risk_score <= 30:
        tags.append("stable_user")
    return tags


def compute_export_signal(
    classification_tags: list[str],
    refund_ratio:        float,
) -> bool:
    """
    export_signal_ready = True if:
      "high_value_user" in tags
      OR ("repeat_buyer" in tags AND refund_ratio ≤ 0.3)

    This flag ONLY prepares a signal; it does NOT execute any export.
    """
    if "high_value_user" in classification_tags:
        return True
    if "repeat_buyer" in classification_tags and refund_ratio <= EXPORT_SIGNAL_MAX_REFUND:
        return True
    return False


# ---------------------------------------------------------------------------
# User Enrichment Engine
# ---------------------------------------------------------------------------

class UserEnrichmentEngine:
    """
    B4 / Bloco 28 — User Enrichment Engine.

    All computations are deterministic and pure.
    All writes go through Persistence + EventBus.
    Zero executive authority.
    """

    def __init__(self, orchestrator, persistence, now_fn=None):
        self.orchestrator = orchestrator
        self._pers       = persistence
        self._now        = now_fn or (lambda: datetime.now(timezone.utc))
        all_records   = persistence.load_all()
        self._records = list(all_records)

        # In-memory latest snapshot per user_id
        self._snapshots: dict[str, dict] = {}
        for r in self._records:
            uid = r.get("user_id")
            if uid:
                self._snapshots[uid] = r

        logger.info(
            f"UserEnrichmentEngine initialized. "
            f"Total records: {len(self._records)}, "
            f"Unique users tracked: {len(self._snapshots)}"
        )

    # ==================================================================
    # PRIMARY ENTRY POINT
    # ==================================================================

    def update_user_profile(
        self,
        *,
        user_id:          str,
        payment_amounts:  list[float],   # all confirmed payment amounts
        refund_amounts:   list[float],   # all confirmed refund amounts
        total_refunds:    int,
        channel_counts:   dict[str, int],
        device_counts:    dict[str, int],
        last_purchase_ts: str | None,
        avg_ltv_product:  float = 0.0,
    ) -> dict:
        """
        Consolidate user intelligence and persist a new enrichment snapshot.

        Parameters:
          user_id           — identifier for the user
          payment_amounts   — list of confirmed payment values (from A10)
          refund_amounts    — list of confirmed refund values (from A10)
          total_refunds     — count of refund events
          channel_counts    — {channel_name: purchase_count}
          device_counts     — {device_name: usage_count}
          last_purchase_ts  — ISO-8601 timestamp of last purchase (or None)
          avg_ltv_product   — product-level average LTV for risk scoring
          event_bus         — EventBus instance (mandatory)

        Returns:
          The full enrichment snapshot dict.
        """
        uid = str(user_id)
        now = self._now()

        total_purchases = len(payment_amounts)

        # --- Compute all metrics ---
        ltv              = compute_lifetime_value(payment_amounts, refund_amounts)
        refund_ratio     = compute_refund_ratio(total_refunds, total_purchases)
        dom_channel      = compute_dominant_channel(channel_counts)
        dom_device       = compute_dominant_device(device_counts)
        recency_days     = compute_activity_recency(last_purchase_ts, now)
        risk             = compute_risk_score(
            refund_ratio, total_purchases, ltv, recency_days, avg_ltv_product
        )
        tags             = compute_classification_tags(
            ltv, refund_ratio, total_purchases, recency_days, risk
        )
        export_ready     = compute_export_signal(tags, refund_ratio)

        event_id = str(uuid.uuid4())

        snapshot = {
            "event_id":            event_id,
            "timestamp":           now.isoformat(),
            "user_id":             uid,
            "metrics_snapshot": {
                "lifetime_value":    ltv,
                "total_purchases":   total_purchases,
                "total_refunds":     total_refunds,
                "refund_ratio":      refund_ratio,
                "dominant_channel":  dom_channel,
                "device_profile":    dom_device,
                "activity_recency":  recency_days,
                "risk_score":        risk,
                "avg_ltv_product":   avg_ltv_product,
            },
            "classification_tag":  tags,
            "export_signal_ready": export_ready,
        }

        # --- Persist (append-only) ---
        self._pers.append_record(snapshot)
        self._records.append(snapshot)
        self._snapshots[uid] = snapshot

        # --- Emit event ---
        self.orchestrator.emit_event(
            event_type="user_enrichment_updated",
            user_id=uid,
            payload={
                "event_id":            event_id,
                "classification_tag":  tags,
                "export_signal_ready": export_ready,
                "risk_score":          risk,
                "lifetime_value":      ltv,
                "timestamp":           now.isoformat(),
            },
            source="system",
        )

        if export_ready:
            self.orchestrator.emit_event(
                event_type="user_export_signal_ready",
                user_id=uid,
                payload={
                    "event_id":           event_id,
                    "classification_tag": tags,
                    "timestamp":          now.isoformat(),
                },
                source="system",
            )
            logger.info(
                f"[B4] export_signal_ready=True for user='{uid}' "
                f"tags={tags} LTV={ltv}"
            )
        else:
            logger.info(
                f"[B4] Profile updated for user='{uid}' "
                f"risk={risk} tags={tags} ltv={ltv}"
            )

        return snapshot

    # ==================================================================
    # Read-only helpers
    # ==================================================================

    def get_user_snapshot(self, user_id: str) -> dict | None:
        """Return the latest enrichment snapshot for a user_id."""
        return self._snapshots.get(str(user_id))

    def get_all_snapshots(self) -> list[dict]:
        """Return all stored snapshots (unsorted)."""
        return list(self._records)

    def get_export_ready_users(self) -> list[dict]:
        """Return latest snapshots of users with export_signal_ready=True."""
        return [
            snap for snap in self._snapshots.values()
            if snap.get("export_signal_ready") is True
        ]

    # ==================================================================
    # Execution guards
    # ==================================================================

    @staticmethod
    def execute_directly(*args, **kwargs) -> None:
        """Always raises UserEnrichmentDirectExecutionError."""
        raise UserEnrichmentDirectExecutionError(
            "execute_directly() is permanently forbidden. "
            "All UserEnrichmentEngine operations must be routed through "
            "Orchestrator.receive_event('user_enrichment_update_requested', ...)."
        )

    def execute_media_campaign(self, *args, **kwargs) -> None:
        """Always raises. B4 has zero media/execution authority."""
        raise UserEnrichmentDirectExecutionError(
            "execute_media_campaign() is permanently forbidden in B4. "
            "export_signal_ready is a read-only flag for future C9 integration. "
            "B4 does not execute any external actions."
        )
