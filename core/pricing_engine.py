"""
core/pricing_engine.py — A7 Pricing Engine

Governs all product price changes with deterministic, event-driven rules:

  - Price changes ONLY permitted during FASE_4 of the Market Loop.
  - Offensive increase: +25%, max 3 consecutive.
  - Defensive reduction: -15%, never below base_price.
  - Automatic rollback if post-change snapshot shows margin drop > 10%
    OR ROAS drop > 15%.
  - Blocked when GlobalState == CONTENÇÃO_FINANCEIRA.
  - All mutations emit formal ledger events.
  - No direct writes.
"""
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("PricingEngine")

# Phase constant (must match MarketLoopEngine definition)
PRICING_PHASE = 4

# Default thresholds
DEFAULT_OFFENSIVE_MULT      = 1.25   # +25%
DEFAULT_DEFENSIVE_MULT      = 0.85   # -15%
DEFAULT_MAX_OFFENSIVE       = 3
DEFAULT_ROLLBACK_MARGIN_THR = 0.10   # >10 pp margin drop triggers rollback
DEFAULT_ROLLBACK_ROAS_THR   = 0.15   # >15% ROAS drop triggers rollback


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class PricingOffensiveLimitError(Exception):
    """Raised when the max number of consecutive offensive increases is exceeded."""

class PricingBelowBaseError(Exception):
    """Raised when a price change would bring the price below base_price."""

class PricingPhaseViolationError(Exception):
    """Raised when a price change is requested outside FASE_4 of the Market Loop."""

class PricingContainmentError(Exception):
    """Raised when pricing is attempted while GlobalState == CONTENÇÃO_FINANCEIRA."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class PricingEngine:
    """
    Deterministic, governed pricing engine.

    Parameters
    ----------
    persistence             : PricingPersistence (or duck-typed)
    offensive_multiplier    : Price multiplier for offensive increase (default 1.25)
    defensive_multiplier    : Price multiplier for defensive reduction (default 0.85)
    max_offensive_increases : Max consecutive offensive increases allowed (default 3)
    rollback_margin_thr     : Margin drop threshold to trigger rollback (default 0.10)
    rollback_roas_thr       : ROAS drop ratio to trigger rollback (default 0.15)
    now_fn                  : Injectable clock for deterministic tests
    """

    def __init__(
        self,
        persistence,
        offensive_multiplier:    float = DEFAULT_OFFENSIVE_MULT,
        defensive_multiplier:    float = DEFAULT_DEFENSIVE_MULT,
        max_offensive_increases: int   = DEFAULT_MAX_OFFENSIVE,
        rollback_margin_thr:     float = DEFAULT_ROLLBACK_MARGIN_THR,
        rollback_roas_thr:       float = DEFAULT_ROLLBACK_ROAS_THR,
        now_fn=None,
    ):
        self._pers                   = persistence
        self._offensive_mult         = offensive_multiplier
        self._defensive_mult         = defensive_multiplier
        self._max_offensive          = max_offensive_increases
        self._rollback_margin_thr    = rollback_margin_thr
        self._rollback_roas_thr      = rollback_roas_thr
        self._now                    = now_fn or (lambda: datetime.now(timezone.utc))

        raw = persistence.load()
        self._state: dict = raw if isinstance(raw, dict) else {}

        logger.info(
            f"PricingEngine initialized. Products tracked: {len(self._state)}. "
            f"offensive_mult={offensive_multiplier}, defensive_mult={defensive_multiplier}, "
            f"max_offensive={max_offensive_increases}"
        )

    # =======================================================================
    # Public API
    # =======================================================================

    def initialize_product(
        self,
        product_id: str,
        base_price: float,
        rpm_base_reference: float,
        orchestrator,
    ) -> dict:
        """
        Register a new product in the pricing ledger.
        Must be called once before any price manipulation.
        Emits: pricing_product_initialized
        """
        p = str(product_id)
        if p in self._state:
            logger.warning(f"PricingEngine: product '{p}' already initialized. Skipping.")
            return self._state[p]

        now    = self._now()
        record = {
            "product_id":                p,
            "base_price":                float(base_price),
            "current_price":             float(base_price),
            "rpm_base_reference":        float(rpm_base_reference),
            "offensive_increases_count": 0,
            "last_price_change_timestamp": None,
            "price_history":             [],
        }
        self._state[p] = record
        self._save()

        orchestrator.emit_event(
            event_type="pricing_product_initialized",
            payload={
                "product_id":         p,
                "base_price":         base_price,
                "rpm_base_reference": rpm_base_reference,
                "initialized_at":     now.isoformat(),
            },
            source="PricingEngine",
            product_id=p
        )
        logger.info(f"Pricing initialized for '{p}': base_price={base_price}, rpm_ref={rpm_base_reference}")
        return record

    # -----------------------------------------------------------------------

    def update_rpm_baseline(
        self,
        product_id: str,
        new_rpm:    float,
        orchestrator,
    ) -> dict:
        """
        Update rpm_base_reference via formal event.
        Emits: pricing_baseline_updated
        """
        p   = str(product_id)
        rec = self._require_record(p)
        now = self._now()

        old_rpm = rec["rpm_base_reference"]
        rec["rpm_base_reference"] = float(new_rpm)
        self._save()

        orchestrator.emit_event(
            event_type="pricing_baseline_updated",
            payload={
                "old_rpm_reference": old_rpm,
                "new_rpm_reference": new_rpm,
                "updated_at":        now.isoformat(),
            },
            source="PricingEngine",
            product_id=p
        )
        logger.info(f"Pricing baseline rpm updated for '{p}': {old_rpm} → {new_rpm}")
        return rec

    # -----------------------------------------------------------------------

    def apply_offensive_increase(
        self,
        product_id:   str,
        orchestrator,
        global_state=None,
        market_loop=None,
    ) -> dict:
        """
        Apply an offensive +25% price increase.

        Preconditions:
          - GlobalState must be NORMAL (not CONTENÇÃO_FINANCEIRA)
          - Market Loop must be in FASE_4
          - offensive_increases_count < max_offensive_increases

        Emits: pricing_offensive_applied
        Raises: PricingContainmentError, PricingPhaseViolationError, PricingOffensiveLimitError
        """
        from core.global_state import CONTENCAO_FINANCEIRA

        p   = str(product_id)
        rec = self._require_record(p)
        now = self._now()

        # --- Financial containment gate ---
        if global_state and global_state.get_state() == CONTENCAO_FINANCEIRA:
            raise PricingContainmentError(
                f"Product '{p}': offensive price increase blocked — system in CONTENÇÃO_FINANCEIRA."
            )

        # --- Phase 4 gate ---
        self._assert_phase_4(market_loop, p)

        # --- Offensive limit gate ---
        if rec["offensive_increases_count"] >= self._max_offensive:
            raise PricingOffensiveLimitError(
                f"Product '{p}': maximum {self._max_offensive} consecutive offensive increases reached. "
                f"Apply a defensive reduction to reset the counter."
            )

        old_price = rec["current_price"]
        new_price = round(old_price * self._offensive_mult, 4)

        # Verify new_price doesn't somehow fall below base (defensive scenario only, but be safe)
        if new_price < rec["base_price"]:
            raise PricingBelowBaseError(
                f"Product '{p}': calculated price {new_price} < base_price {rec['base_price']}."
            )

        self._apply_change(rec, old_price, new_price, "OFFENSIVE",
                           f"offensive_increase_x{self._offensive_mult}", now)
        rec["offensive_increases_count"] += 1
        self._save()

        orchestrator.emit_event(
            event_type="pricing_offensive_applied",
            payload={
                "old_price":         old_price,
                "new_price":         new_price,
                "multiplier":        self._offensive_mult,
                "count_after":       rec["offensive_increases_count"],
                "applied_at":        now.isoformat(),
            },
            source="PricingEngine",
            product_id=p
        )
        logger.info(
            f"Offensive increase applied for '{p}': {old_price} → {new_price} "
            f"(count={rec['offensive_increases_count']}/{self._max_offensive})"
        )
        return rec

    # -----------------------------------------------------------------------

    def apply_defensive_reduction(
        self,
        product_id:   str,
        orchestrator,
        global_state=None,
        market_loop=None,
    ) -> dict:
        """
        Apply a defensive -15% price reduction.

        Preconditions:
          - Market Loop must be in FASE_4
          - new_price must not fall below base_price

        Emits: pricing_defensive_applied
        Raises: PricingPhaseViolationError, PricingBelowBaseError
        """
        from core.global_state import CONTENCAO_FINANCEIRA

        p   = str(product_id)
        rec = self._require_record(p)
        now = self._now()

        # Financial containment also blocks defensive (spec: "Bloqueado em CONTENÇÃO_FINANCEIRA")
        if global_state and global_state.get_state() == CONTENCAO_FINANCEIRA:
            raise PricingContainmentError(
                f"Product '{p}': defensive reduction blocked — system in CONTENÇÃO_FINANCEIRA."
            )

        # --- Phase 4 gate ---
        self._assert_phase_4(market_loop, p)

        old_price = rec["current_price"]
        new_price = round(old_price * self._defensive_mult, 4)

        if new_price < rec["base_price"]:
            raise PricingBelowBaseError(
                f"Product '{p}': defensive reduction would bring price {new_price} "
                f"below base_price {rec['base_price']}. "
                f"Reduction not applied."
            )

        self._apply_change(rec, old_price, new_price, "DEFENSIVE",
                           f"defensive_reduction_x{self._defensive_mult}", now)
        rec["offensive_increases_count"] = 0   # reset counter on defensive action
        self._save()

        orchestrator.emit_event(
            event_type="pricing_defensive_applied",
            payload={
                "old_price":         old_price,
                "new_price":         new_price,
                "multiplier":        self._defensive_mult,
                "offensive_reset":   True,
                "applied_at":        now.isoformat(),
            },
            source="PricingEngine",
            product_id=p
        )
        logger.info(
            f"Defensive reduction applied for '{p}': {old_price} → {new_price}"
        )
        return rec

    # -----------------------------------------------------------------------

    def evaluate_pricing_performance(
        self,
        product_id:      str,
        pre_snapshot:    dict,
        post_snapshot:   dict,
        orchestrator,
    ) -> dict:
        """
        Compare pre/post pricing snapshots and auto-rollback if:
          - margin dropped > rollback_margin_thr (10%)
          - ROAS dropped > rollback_roas_thr (15%)

        Emits: pricing_rollback_executed (on rollback)
        """
        p   = str(product_id)
        rec = self._require_record(p)
        now = self._now()

        pre_margin  = float(pre_snapshot.get("margin", 0.0))
        post_margin = float(post_snapshot.get("margin", 0.0))
        pre_roas    = float(pre_snapshot.get("roas",   0.0))
        post_roas   = float(post_snapshot.get("roas",  0.0))

        margin_drop = pre_margin - post_margin
        roas_drop   = (pre_roas - post_roas) / pre_roas if pre_roas > 0 else 0.0

        needs_rollback = (
            margin_drop > self._rollback_margin_thr
            or roas_drop  > self._rollback_roas_thr
        )

        if needs_rollback:
            history         = rec["price_history"]
            # Restore to the price BEFORE the last change
            if len(history) >= 2:
                restored = history[-2]["new_price"]
            elif history:
                restored = history[-1]["old_price"]
            else:
                restored = rec["base_price"]

            current = rec["current_price"]
            self._apply_change(rec, current, restored, "ROLLBACK",
                               f"auto_rollback margin_drop={margin_drop:.4f} roas_drop={roas_drop:.4f}", now)
            rec["offensive_increases_count"] = 0
            self._save()

            orchestrator.emit_event(
                event_type="pricing_rollback_executed",
                payload={
                    "restored_price":  restored,
                    "previous_price":  current,
                    "margin_drop":     margin_drop,
                    "roas_drop":       roas_drop,
                    "rolled_back_at":  now.isoformat(),
                },
                source="PricingEngine",
                product_id=p
            )
            logger.warning(
                f"Pricing rollback for '{p}': {current} → {restored} "
                f"(margin_drop={margin_drop:.4f}, roas_drop={roas_drop:.4f})"
            )
            return {"rolled_back": True, "restored_price": restored}

        logger.info(
            f"Pricing performance OK for '{p}': "
            f"margin_drop={margin_drop:.4f}, roas_drop={roas_drop:.4f}"
        )
        return {"rolled_back": False}

    def rollback_price(self, product_id: str, orchestrator) -> None:
        """
        Manually trigger a rollback to the previous price in history.
        Used by Orchestrator during failed pricing tests.
        """
        p   = str(product_id)
        rec = self._require_record(p)
        now = self._now()

        history = rec["price_history"]
        if len(history) >= 2:
            restored = history[-2]["new_price"]
        elif history:
            restored = history[-1]["old_price"]
        else:
            restored = rec["base_price"]

        current = rec["current_price"]
        self._apply_change(rec, current, restored, "ROLLBACK_MANUAL", "triggered by orchestrator", now)
        rec["offensive_increases_count"] = 0
        self._save()

        orchestrator.emit_event(
            event_type="pricing_rollback_executed",
            payload={
                "restored_price":  restored,
                "previous_price":  current,
                "reason":          "manual_rollback",
                "rolled_back_at":  now.isoformat(),
            },
            source="PricingEngine",
            product_id=p
        )
        logger.warning(f"Manual pricing rollback for '{p}': {current} → {restored}")

    # -----------------------------------------------------------------------

    def get_record(self, product_id: str) -> dict | None:
        """Return the current pricing record for a product (read-only)."""
        return self._state.get(str(product_id))

    # =======================================================================
    # Internal helpers
    # =======================================================================

    def _require_record(self, p: str) -> dict:
        rec = self._state.get(p)
        if rec is None:
            raise KeyError(
                f"PricingEngine: product '{p}' not initialized. "
                f"Call initialize_product() first."
            )
        return rec

    def _assert_phase_4(self, market_loop, product_id: str) -> None:
        """Raise PricingPhaseViolationError if not in FASE_4."""
        if market_loop is None:
            return   # No loop injected → skip gate (test mode without loop)
        open_cycle = (
            market_loop._find_open_cycle(product_id)
            if hasattr(market_loop, "_find_open_cycle")
            else None
        )
        if not open_cycle:
            raise PricingPhaseViolationError(
                f"Product '{product_id}': no open Market Loop cycle. "
                f"Pricing changes require an active FASE_4 cycle."
            )
        current_phase = open_cycle.get("current_phase", 0)
        if current_phase != PRICING_PHASE:
            raise PricingPhaseViolationError(
                f"Product '{product_id}': price changes only allowed in FASE_4. "
                f"Current phase: {current_phase}."
            )

    def _apply_change(
        self,
        rec:       dict,
        old_price: float,
        new_price: float,
        kind:      str,
        reason:    str,
        now,
    ) -> None:
        """Update current_price and append to price_history. Immutable history."""
        rec["current_price"]              = new_price
        rec["last_price_change_timestamp"] = now.isoformat()
        rec["price_history"].append({
            "old_price": old_price,
            "new_price": new_price,
            "type":      kind,         # OFFENSIVE | DEFENSIVE | ROLLBACK
            "reason":    reason,
            "timestamp": now.isoformat(),
        })

    def _save(self) -> None:
        self._pers.save(self._state)
