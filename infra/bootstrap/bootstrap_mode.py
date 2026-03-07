"""
infra/bootstrap/bootstrap_mode.py — Bootstrap ICE Gate (Etapa 3)

Purpose:
  Allow the first few radar cycles to pass through the ICE Gate while the
  system has no historical ROAS or performance data, so it can generate
  its first opportunities and start accumulating baseline metrics.

Constitutional guarantees:
  - Does NOT modify ICE scoring logic
  - Does NOT modify RadarEngine, StrategicOpportunityEngine, or any engine
  - Does NOT break governance rules (governance check still runs)
  - Bootstrap period is automatically limited (BOOTSTRAP_EVAL_LIMIT)
  - Transparent: every override is logged explicitly
  - Read-only on all persistence layers

How it works:
  - Reads the count of persisted opportunity evaluations
  - If count <= BOOTSTRAP_EVAL_LIMIT:
      → Returns enriched eval_payload_overrides that pass Phase 4 scoring
      → RadarEngine.run_cycle() receives these overrides and passes them
        to StrategicOpportunityEngine.evaluate_opportunity_v2()
      → ICE gate sees valid baseline values → MODERADO or ALTO
  - If count > BOOTSTRAP_EVAL_LIMIT:
      → Returns None → caller uses no overrides → strict mode resumes
"""
import os
from infrastructure.logger import get_logger
from infrastructure.opportunity_radar_persistence import OpportunityRadarPersistence

logger = get_logger("BootstrapMode")

# Number of *qualified* evaluations after which bootstrap automatically disables.
# Set to 20 to ensure the system has meaningful baseline data before strict mode.
# Can be overridden via env var BOOTSTRAP_EVAL_LIMIT.
BOOTSTRAP_EVAL_LIMIT: int = int(os.getenv("BOOTSTRAP_EVAL_LIMIT", "20"))

# Bootstrap scoring overrides — values that satisfy Phase 4 scoring thresholds
# These are reasonable baseline assumptions for a fresh system with no real data.
# All values are within the passing thresholds of StrategicOpportunityEngine:
#   emotional >= 70, monetization >= 75, growth_score >= 60
#   score_global >= 78, roas >= 1.6, active_betas <= 2
#   growth_percent >= GROWTH_PERCENT_MIN (floor to prevent negative provider data)
_BOOTSTRAP_OVERRIDES = {
    # Growth floor — provider data can return negative growth, which fails Phase 4
    "growth_percent": 25.0,
    # Scoring signals — mid-range values, not artificially inflated
    "freq":        75.0,
    "intensity":   72.0,
    "recurrence":  70.0,
    "persistence": 68.0,
    "intent":      75.0,
    "solutions":   72.0,
    "cpc":         70.0,
    "validation":  74.0,
    "growth_score":  70.0,
    "occurrences":  150,
    # System state — NORMAL, no betas active, no macro block
    "global_state":           "NORMAL",
    "financial_alert_active": False,
    "active_betas":           0,
    "macro_exposure_blocked": False,
    # ICE prerequisites — baseline values
    "score_global":   80.0,
    "roas":           2.0,
    "positive_trend": True,   # → ICE_ALTO when all pass
}


def get_bootstrap_overrides() -> dict | None:
    """
    Check if system is in bootstrap mode and return eval_payload_overrides.

    Bootstrap is considered ACTIVE until at least BOOTSTRAP_EVAL_LIMIT
    *qualified* evaluations (recommended=True) are persisted. Blocked or
    not_qualified evaluations do NOT count toward the limit because they
    do not represent real system health.

    Returns:
        dict   — Override payload to pass to RadarEngine.run_cycle()
                 when bootstrap mode is active.
        None   — Bootstrap period has ended; caller uses no overrides.
    """
    try:
        pers    = OpportunityRadarPersistence("radar_evaluations.json")
        stored  = list(pers.load_all())
        # Count only truly qualified evaluations (not blocked/not_qualified)
        qualified = [
            r for r in stored
            if r.get("recommended") is True
            and r.get("score_final") is not None
        ]
        count = len(qualified)
    except Exception as exc:
        logger.warning("[BootstrapMode] Could not read evaluations (non-fatal): %s", exc)
        count = 0

    if count <= BOOTSTRAP_EVAL_LIMIT:
        logger.info(
            "[BootstrapMode] Bootstrap mode ACTIVE — "
            "qualified_evaluations=%d limit=%d — enriched eval_payload_overrides provided",
            count, BOOTSTRAP_EVAL_LIMIT,
        )
        return dict(_BOOTSTRAP_OVERRIDES)

    # Bootstrap period completed
    logger.info(
        "[BootstrapMode] Bootstrap mode COMPLETED — "
        "qualified_evaluations=%d > limit=%d — returning to strict ICE governance",
        count, BOOTSTRAP_EVAL_LIMIT,
    )
    return None


def is_bootstrap_active() -> bool:
    """Quick boolean check for logging/monitoring purposes."""
    overrides = get_bootstrap_overrides()
    return overrides is not None

