"""
core/macro_exposure_governance_engine.py — Bloco 29: Macro Exposure Governance Engine

Classification: Governance Subordinate — ZERO executive / allocation authority.

Validates whether a requested capital allocation would exceed acceptable exposure
limits at product, channel, and global levels, using adaptive (elevated) limits
when strict performance criteria are met.

BASE LIMITS (always-available floor):
  product_exposure_max = 20 %
  channel_exposure_max = 40 %
  global_exposure_max  = 60 %

ADAPTIVE LIMITS (elevated, only when ALL criteria satisfied):
  product_exposure_max = 30 %
  channel_exposure_max = 50 %
  global_exposure_max  = 70 %

Adaptive eligibility requires simultaneously:
  roas_avg >= 2.0
  score_global >= 85
  refund_ratio_avg <= 0.10
  global_state == "NORMAL"
  credit_low_warning == False  AND  credit_critical_warning == False

This engine:
  ✗ Does NOT create products
  ✗ Does NOT modify allocations directly
  ✗ Does NOT modify prices
  ✗ Does NOT modify global_state
  ✗ Does NOT override Finance Engine or ICE
  ✗ Does NOT execute automatically
  ✗ Does NOT bypass Orchestrator
  ✓ Emits formal events and returns a structured validation verdict

Subordination: Orchestrator → MacroExposureGovernanceEngine → EventBus + Persistence
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("MacroExposureGovernanceEngine")

# ---------------------------------------------------------------------------
# Limit constants
# ---------------------------------------------------------------------------

_BASE_PRODUCT_LIMIT  = 0.20
_BASE_CHANNEL_LIMIT  = 0.40
_BASE_GLOBAL_LIMIT   = 0.60

_ADAPT_PRODUCT_LIMIT = 0.30
_ADAPT_CHANNEL_LIMIT = 0.50
_ADAPT_GLOBAL_LIMIT  = 0.70

# Adaptive eligibility thresholds
_ADAPT_MIN_ROAS          = 2.0
_ADAPT_MIN_SCORE_GLOBAL  = 85.0
_ADAPT_MAX_REFUND_RATIO  = 0.10
_ADAPT_REQUIRED_STATE    = "NORMAL"


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class MacroExposureDirectExecutionError(Exception):
    """Raised whenever engine methods are invoked without Orchestrator routing."""


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _is_adaptive_eligible(
    roas_avg:              float,
    score_global:          float,
    refund_ratio_avg:      float,
    global_state:          str,
    financial_alert_active: bool,
) -> bool:
    """Return True only when ALL adaptive conditions are simultaneously satisfied."""
    return (
        roas_avg >= _ADAPT_MIN_ROAS
        and score_global >= _ADAPT_MIN_SCORE_GLOBAL
        and refund_ratio_avg <= _ADAPT_MAX_REFUND_RATIO
        and global_state == _ADAPT_REQUIRED_STATE
        and not financial_alert_active
    )


def _active_limits(adaptive: bool) -> dict:
    if adaptive:
        return {
            "product": _ADAPT_PRODUCT_LIMIT,
            "channel": _ADAPT_CHANNEL_LIMIT,
            "global":  _ADAPT_GLOBAL_LIMIT,
            "mode":    "adaptive",
        }
    return {
        "product": _BASE_PRODUCT_LIMIT,
        "channel": _BASE_CHANNEL_LIMIT,
        "global":  _BASE_GLOBAL_LIMIT,
        "mode":    "base",
    }


def _compute_projections(
    current_product_allocation: float,
    current_channel_allocation: float,
    current_global_allocation:  float,
    requested_allocation:       float,
    total_capital:              float,
) -> dict:
    """Compute projected exposure ratios for product, channel, and global levels."""
    safe_cap = max(total_capital, 1e-9)   # avoid division by zero
    return {
        "product": round(
            (current_product_allocation + requested_allocation) / safe_cap, 6
        ),
        "channel": round(
            (current_channel_allocation + requested_allocation) / safe_cap, 6
        ),
        "global": round(
            (current_global_allocation + requested_allocation) / safe_cap, 6
        ),
    }


# ---------------------------------------------------------------------------
# MacroExposureGovernanceEngine
# ---------------------------------------------------------------------------

class MacroExposureGovernanceEngine:
    """
    Bloco 29 — Macro Exposure Governance Engine.

    Validates capital exposure at three levels (product / channel / global)
    using two-tier adaptive limits.  Emits formal governance events and
    persists an append-only audit record for every validation.
    Zero allocation authority.
    """

    def __init__(self, orchestrator, persistence, now_fn=None):
        self.orchestrator = orchestrator
        self._pers       = persistence
        self._now        = now_fn or (lambda: datetime.now(timezone.utc))
        all_records      = persistence.load_all()
        self._records    = list(all_records)
        # Track whether last evaluation per product was adaptive
        self._last_adaptive: dict[str, bool] = {}

        for r in self._records:
            pid = r.get("product_id")
            if pid is not None:
                self._last_adaptive[pid] = r.get("adaptive_mode_active", False)

        logger.info(
            f"MacroExposureGovernanceEngine initialized. "
            f"Total records: {len(self._records)}, "
            f"Products tracked: {len(self._last_adaptive)}"
        )

    # ==================================================================
    # PRIMARY ENTRY POINT
    # ==================================================================

    def validate_macro_exposure(
        self,
        *,
        product_id:                 str,
        channel_id:                 str,
        requested_allocation:       float,
        current_product_allocation: float,
        current_channel_allocation: float,
        current_global_allocation:  float,
        total_capital:              float,
        roas_avg:                   float,
        score_global:               float,
        refund_ratio_avg:           float,
        global_state:               str,
        financial_alert_active:     bool,
    ) -> dict:
        """
        Validate whether the requested allocation is within exposure limits.

        Returns a dict with at minimum:
          { "allowed": bool, "active_limits": {...}, "projected_values": {...} }
        and optionally:
          { "reason": "macro_limit_exceeded", "violations": [...] }

        Side-effects:
          • Emits one or more governance events (adapted / reverted / validated / blocked)
          • Appends one audit record to persistence
        """
        now = self._now()
        pid = str(product_id)
        cid = str(channel_id)

        # --- Step 1: Determine adaptive eligibility ---
        adaptive = _is_adaptive_eligible(
            roas_avg, score_global, refund_ratio_avg, global_state, financial_alert_active
        )
        limits   = _active_limits(adaptive)
        was_adaptive = self._last_adaptive.get(pid, False)

        # --- Emit mode transition events ---
        if adaptive and not was_adaptive:
            self.orchestrator.emit_event(
                event_type="macro_exposure_adapted",
                product_id=pid,
                payload={
                    "active_limits": limits,
                    "roas_avg":        roas_avg,
                    "score_global":    score_global,
                    "refund_ratio_avg": refund_ratio_avg,
                    "global_state":    global_state,
                },
                source="system",
            )
            logger.info(
                f"[Bloco29] Adaptive limits ACTIVATED for product='{pid}' "
                f"(roas={roas_avg}, score={score_global})"
            )
        elif not adaptive and was_adaptive:
            self.orchestrator.emit_event(
                event_type="macro_exposure_reverted",
                product_id=pid,
                payload={
                    "active_limits": limits,
                    "reason": "adaptive_criteria_no_longer_met",
                    "financial_alert_active": financial_alert_active,
                    "global_state": global_state,
                },
                source="system",
            )
            logger.warning(
                f"[Bloco29] Adaptive limits REVERTED to base for product='{pid}'"
            )

        # --- Step 2: Project exposures ---
        proj = _compute_projections(
            current_product_allocation,
            current_channel_allocation,
            current_global_allocation,
            requested_allocation,
            total_capital,
        )

        # --- Step 3: Check violations ---
        violations: list[str] = []
        if proj["product"] > limits["product"]:
            violations.append(
                f"product_exposure {proj['product']:.4%} > limit {limits['product']:.4%}"
            )
        if proj["channel"] > limits["channel"]:
            violations.append(
                f"channel_exposure {proj['channel']:.4%} > limit {limits['channel']:.4%}"
            )
        if proj["global"] > limits["global"]:
            violations.append(
                f"global_exposure {proj['global']:.4%} > limit {limits['global']:.4%}"
            )

        allowed = len(violations) == 0

        # --- Step 4: Emit main decision event ---
        decision = "validated" if allowed else "blocked"
        if allowed:
            self.orchestrator.emit_event(
                event_type="macro_exposure_validated",
                product_id=pid,
                payload={
                    "channel_id":      cid,
                    "requested":       requested_allocation,
                    "active_limits":   limits,
                    "projected_values": proj,
                    "adaptive_mode":   adaptive,
                },
                source="system",
            )
            logger.info(
                f"[Bloco29] VALIDATED product='{pid}' channel='{cid}' "
                f"requested={requested_allocation} limits={limits['mode']}"
            )
        else:
            self.orchestrator.emit_event(
                event_type="macro_exposure_blocked",
                product_id=pid,
                payload={
                    "channel_id":      cid,
                    "requested":       requested_allocation,
                    "active_limits":   limits,
                    "projected_values": proj,
                    "violations":      violations,
                    "adaptive_mode":   adaptive,
                },
                source="system",
            )
            logger.warning(
                f"[Bloco29] BLOCKED product='{pid}' channel='{cid}' "
                f"violations={violations}"
            )

        # --- Step 5: Persist audit record ---
        event_id = str(uuid.uuid4())
        record = {
            "event_id":            event_id,
            "timestamp":           now.isoformat(),
            "product_id":          pid,
            "channel_id":          cid,
            "active_limits":       limits,
            "projected_exposures": proj,
            "roas_avg":            roas_avg,
            "score_global":        score_global,
            "refund_ratio_avg":    refund_ratio_avg,
            "global_state":        global_state,
            "adaptive_mode_active": adaptive,
            "decision":            decision,
            "violations":          violations,
        }
        self._pers.append_record(record)
        self._records.append(record)
        self._last_adaptive[pid] = adaptive

        # --- Return verdict ---
        if allowed:
            return {
                "allowed":         True,
                "active_limits":   limits,
                "projected_values": proj,
                "adaptive_mode":   adaptive,
            }
        else:
            return {
                "allowed":         False,
                "reason":          "macro_limit_exceeded",
                "violations":      violations,
                "active_limits":   limits,
                "projected_values": proj,
                "adaptive_mode":   adaptive,
            }

    # ==================================================================
    # Read-only helpers
    # ==================================================================

    def get_all_records(self) -> list[dict]:
        """Return all audit records (append order)."""
        return list(self._records)

    def get_product_records(self, product_id: str) -> list[dict]:
        """Return audit records for a specific product."""
        return [r for r in self._records if r.get("product_id") == str(product_id)]

    # ==================================================================
    # Execution guards
    # ==================================================================

    @staticmethod
    def execute_directly(*args, **kwargs) -> None:
        """Always raises MacroExposureDirectExecutionError."""
        raise MacroExposureDirectExecutionError(
            "execute_directly() is permanently forbidden in Bloco 29. "
            "All MacroExposureGovernanceEngine operations must be routed through "
            "Orchestrator.receive_event('macro_exposure_validation_requested', ...)."
        )

    def modify_allocation(self, *args, **kwargs) -> None:
        """Always raises. Bloco 29 has zero allocation authority."""
        raise MacroExposureDirectExecutionError(
            "modify_allocation() is permanently forbidden. "
            "MacroExposureGovernanceEngine only validates; "
            "allocation changes must go through the Finance Engine via Orchestrator."
        )
