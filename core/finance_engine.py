"""
core/finance_engine.py — A4 Official Finance Engine

Deterministic financial governance:
- Monitors Stripe and OpenAI balances
- Calculates moving-average daily burn rate
- Projects days_remaining with safe zero-division handling
- Emits formal alerts (credit_low_warning / credit_critical_warning)
- Updates GlobalState automatically
- Triggers auto_recharge_triggered event when enabled and in critical state

All mutations go through this engine — no external direct writes.
"""
from datetime import datetime, timezone
from infrastructure.logger import get_logger
from core.global_state import (
    GlobalState, NORMAL, ALERTA_FINANCEIRO, CONTENCAO_FINANCEIRA
)

logger = get_logger("FinanceEngine")

# Sentinel for infinite days remaining (zero burn)
_INF_DAYS = 999_999


class FinanceEngine:
    """
    Official financial accounting and projection engine.

    Configuration (all overridable at construction):
        min_buffer_days:       14  — warn threshold (credit_low_warning)
        auto_recharge_enabled: False
        moving_avg_days:       7   — window for burn-rate moving average

    External API (called by Orchestrator service handlers):
        register_stripe_balance(amount, event_bus)
        register_openai_balance(amount, event_bus)
        register_ad_spend(amount, event_bus)
        register_revenue(amount, event_bus)
        register_stripe_revenue(amount, event_bus)
        register_stripe_refund(amount, event_bus)
        calculate_daily_burn() → float
        project_days_remaining(event_bus) → dict
        validate_financial_health(event_bus) → dict
        trigger_auto_recharge_if_enabled(event_bus, context) → bool
    """

    def __init__(
        self,
        state_persistence,
        projection_persistence=None,
        global_state: GlobalState | None = None,
        min_buffer_days: int   = 14,
        auto_recharge_enabled: bool = False,
        moving_avg_days:  int  = 7,
    ):
        self._state_pers     = state_persistence
        self._proj_pers      = projection_persistence
        self._global_state   = global_state
        self.min_buffer_days = min_buffer_days
        self.auto_recharge   = auto_recharge_enabled
        self.avg_window      = moving_avg_days

        # Load persistent financial state
        raw = state_persistence.load()
        self._fs: dict = {
            "stripe_current_balance": raw.get("stripe_current_balance", 0.0),
            "stripe_total_revenue":   raw.get("stripe_total_revenue",   0.0),
            "stripe_total_refunds":   raw.get("stripe_total_refunds",   0.0),
            "openai_current_balance": raw.get("openai_current_balance", 0.0),
            "openai_total_usage":     raw.get("openai_total_usage",     0.0),
            "ad_spend_sessions":      raw.get("ad_spend_sessions",      []),
        }

        logger.info(
            f"FinanceEngine initialized. "
            f"Stripe={self._fs['stripe_current_balance']} "
            f"OpenAI={self._fs['openai_current_balance']} "
            f"Sessions={len(self._fs['ad_spend_sessions'])} "
            f"Buffer={min_buffer_days}d AutoRecharge={auto_recharge_enabled}"
        )

    # ==================================================================
    # Registration API
    # ==================================================================

    def register_stripe_balance(self, amount: float, orchestrator) -> None:
        self._fs["stripe_current_balance"] = amount
        self._save()
        orchestrator.emit_event(
            event_type="stripe_balance_updated",
            payload={"balance": amount},
            source="FinanceEngine"
        )
        logger.info(f"Stripe balance set: R${amount:.2f}")

    def register_stripe_revenue(self, amount: float, orchestrator) -> None:
        self._fs["stripe_current_balance"] += amount
        self._fs["stripe_total_revenue"]   += amount
        self._save()
        orchestrator.emit_event(
            event_type="stripe_revenue_recorded",
            payload={"amount": amount, "total": self._fs["stripe_total_revenue"]},
            source="FinanceEngine"
        )

    def register_stripe_refund(self, amount: float, orchestrator) -> None:
        self._fs["stripe_current_balance"] -= amount
        self._fs["stripe_total_refunds"]   += amount
        self._save()
        orchestrator.emit_event(
            event_type="stripe_refund_recorded",
            payload={"amount": amount, "total_refunds": self._fs["stripe_total_refunds"]},
            source="FinanceEngine"
        )

    def register_openai_balance(self, amount: float, orchestrator) -> None:
        previous_usage = self._fs["openai_total_usage"]
        if amount < self._fs["openai_current_balance"]:
            # Balance decreased → usage occurred
            used = self._fs["openai_current_balance"] - amount
            self._fs["openai_total_usage"] = previous_usage + used
        self._fs["openai_current_balance"] = amount
        self._save()
        orchestrator.emit_event(
            event_type="openai_balance_updated",
            payload={
                "balance":     amount,
                "total_usage": self._fs["openai_total_usage"],
            },
            source="FinanceEngine"
        )
        logger.info(f"OpenAI balance set: ${amount:.2f}")

    def register_ad_spend(self, amount: float, event_bus) -> None:
        """Record a new ad-spend session (contributes to burn-rate moving average)."""
        sessions: list = self._fs["ad_spend_sessions"]
        sessions.append(amount)
        # Keep list bounded at 365 to avoid unbounded growth
        if len(sessions) > 365:
            self._fs["ad_spend_sessions"] = sessions[-365:]
        self._save()

    def register_revenue(self, amount: float, event_bus) -> None:
        """Generic revenue (not Stripe-specific)."""
        self._fs["stripe_current_balance"] += amount
        self._fs["stripe_total_revenue"]   += amount
        self._save()

    # ==================================================================
    # Burn Rate & Projection
    # ==================================================================

    def calculate_daily_burn(self) -> float:
        """Moving average of the last N ad-spend sessions. Returns 0.0 if no history."""
        sessions = self._fs["ad_spend_sessions"]
        window   = sessions[-self.avg_window:] if sessions else []
        return sum(window) / len(window) if window else 0.0

    def project_days_remaining(self, orchestrator) -> dict:
        """
        Project days of operation remaining.
        Returns _INF_DAYS if daily_burn == 0 (safe zero-division handling).
        Always emits financial_projection_updated.
        """
        stripe   = self._fs["stripe_current_balance"]
        openai   = self._fs["openai_current_balance"]
        total    = stripe + openai
        burn     = self.calculate_daily_burn()
        days     = round(total / burn, 2) if burn > 0 else _INF_DAYS

        projection = {
            "stripe_balance":  stripe,
            "openai_balance":  openai,
            "total_available": round(total, 2),
            "daily_burn":      round(burn, 4),
            "days_remaining":  days,
            "timestamp":       datetime.now(timezone.utc).isoformat(),
        }

        if self._proj_pers:
            self._proj_pers.append(projection)

        orchestrator.emit_event(
            event_type="financial_projection_updated",
            payload=projection,
            source="FinanceEngine"
        )

        return projection

    # ==================================================================
    # Health Validation
    # ==================================================================

    def validate_financial_health(self, orchestrator) -> dict:
        """
        Check financial thresholds and emit alerts if needed.
        Also updates GlobalState accordingly.
        Returns the projection dict.
        """
        proj     = self.project_days_remaining(orchestrator)
        days     = proj["days_remaining"]
        buf      = self.min_buffer_days
        ts       = datetime.now(timezone.utc).isoformat()
        result   = {"projection": proj, "alerts": []}

        # --- Threshold checks (critical is a subset of low) ---
        if days != _INF_DAYS and days <= buf / 2:
            self._emit_warning("credit_critical_warning", days, buf, ts, orchestrator)
            result["alerts"].append("credit_critical_warning")
            self._set_global_state(CONTENCAO_FINANCEIRA, orchestrator, "credit_critical_warning")
            self.trigger_auto_recharge_if_enabled(orchestrator, proj)

        elif days != _INF_DAYS and days <= buf:
            self._emit_warning("credit_low_warning", days, buf, ts, orchestrator)
            result["alerts"].append("credit_low_warning")
            self._set_global_state(ALERTA_FINANCEIRO, orchestrator, "credit_low_warning")

        else:
            # Situation normalized — return to NORMAL
            self._set_global_state(NORMAL, orchestrator, "health_check_passed")

        return result

    def trigger_auto_recharge_if_enabled(self, orchestrator, context: dict) -> bool:
        """Emit auto_recharge_triggered if AUTO_RECHARGE_ENABLED. Never executes real charge."""
        if not self.auto_recharge:
            return False

        orchestrator.emit_event(
            event_type="auto_recharge_triggered",
            payload={
                "days_remaining":  context.get("days_remaining"),
                "total_available": context.get("total_available"),
                "daily_burn":      context.get("daily_burn"),
                "timestamp":       datetime.now(timezone.utc).isoformat(),
            },
            source="FinanceEngine"
        )
        logger.warning("AUTO RECHARGE EVENT TRIGGERED — manual action required.")
        return True

    # ==================================================================
    # Queries (read-only — safe for Dashboard / Orchestrator checks)
    # ==================================================================

    def get_state(self) -> dict:
        return dict(self._fs)

    # ==================================================================
    # Internal
    # ==================================================================

    def _emit_warning(
        self,
        event_type: str,
        days: float,
        threshold: float,
        ts: str,
        orchestrator,
    ) -> None:
        payload = {
            "days_remaining":    days,
            "buffer_threshold":  threshold,
            "timestamp":         ts,
        }
        orchestrator.emit_event(
            event_type=event_type,
            payload=payload,
            source="FinanceEngine"
        )
        logger.warning(
            f"{event_type}: {days} days remaining "
            f"(threshold={threshold}d)"
        )

    def _set_global_state(self, new_state: str, orchestrator, reason: str) -> None:
        orchestrator.set_global_state(new_state, reason=reason)

    def _save(self) -> None:
        self._state_pers.save({
            **self._fs,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        })
