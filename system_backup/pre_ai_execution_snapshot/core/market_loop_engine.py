"""
core/market_loop_engine.py — A6 Market Loop Engine

Governs the deterministic 4-phase optimization cycle for Active products:

    FASE_1: Abordagem  (approach / copy)
    FASE_2: Página     (landing page)
    FASE_3: Produto    (product offer)
    FASE_4: Preço      (pricing)

Rules:
  - Only Ativo products may enter the loop.
  - Phase order is immutable — no skipping, repeating, or out-of-order execution.
  - One open cycle per product (no microcycle).
  - Statistical substitution only if RPM↑ or ROAS↑ without margin deterioration.
  - Automatic rollback if post-substitution snapshot regresses.
  - All mutations emit formal ledger events.
  - No direct writes.
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("MarketLoopEngine")

# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------
PHASES = {1: "Abordagem", 2: "Página", 3: "Produto", 4: "Preço"}
PHASE_NUMBERS = list(PHASES.keys())   # [1, 2, 3, 4]
MAX_PHASE = max(PHASE_NUMBERS)


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class MarketLoopPhaseOrderError(Exception):
    """Raised when a phase is executed out of the fixed order."""

class MarketLoopMicrocycleError(Exception):
    """Raised when a new cycle is started before the previous one is closed."""

class MarketLoopProductStateError(Exception):
    """Raised when a non-Ativo product tries to enter the loop."""

class MarketLoopNoCycleError(Exception):
    """Raised when an operation requires an open cycle but none exists."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MarketLoopEngine:
    """
    Deterministic 4-phase market optimization loop.

    Constructor parameters
    ----------------------
    persistence             : MarketLoopPersistence (or duck-typed equivalent)
    min_rpm_improvement     : Minimum RPM delta to accept substitution (default 0.0, i.e. any positive improvement)
    min_roas_improvement    : Minimum ROAS delta to accept substitution (default 0.0)
    max_margin_degradation  : Max allowed margin drop on substitution (default 0.05 = 5 pp)
    rollback_loss_threshold : Margin drop that triggers automatic rollback (default 0.10 = 10 pp)
    now_fn                  : Injectable clock for deterministic tests
    """

    def __init__(
        self,
        persistence,
        min_rpm_improvement:    float = 0.0,
        min_roas_improvement:   float = 0.0,
        max_margin_degradation: float = 0.05,
        rollback_loss_threshold: float = 0.10,
        now_fn=None,
    ):
        self._pers                   = persistence
        self.min_rpm_improvement     = min_rpm_improvement
        self.min_roas_improvement    = min_roas_improvement
        self.max_margin_degradation  = max_margin_degradation
        self.rollback_loss_threshold = rollback_loss_threshold
        self._now                    = now_fn or (lambda: datetime.now(timezone.utc))

        raw = persistence.load()
        # Internal state: { product_id: { cycle records list } }
        # Active cycle keyed separately for fast lookup
        self._cycles: dict = raw if isinstance(raw, dict) else {}

        logger.info(
            f"MarketLoopEngine initialized. "
            f"Products with cycle history: {len(self._cycles)}. "
            f"rpm_min_delta={min_rpm_improvement}, roas_min_delta={min_roas_improvement}, "
            f"max_margin_deg={max_margin_degradation}, rollback_thr={rollback_loss_threshold}"
        )

    # =======================================================================
    # Public API
    # =======================================================================

    def start_new_cycle(
        self,
        product_id:        str,
        orchestrator,
        state_manager=None,
        global_state=None,
    ) -> dict:
        """
        Start a new optimization cycle for an Active product.

        Preconditions:
          - Product must be in 'Ativo' state (checked via state_manager).
          - No open cycle must exist (no-microcycle rule).
          - GlobalState must NOT be CONTENÇÃO_FINANCEIRA.

        Emits: market_cycle_started
        """
        from core.global_state import CONTENCAO_FINANCEIRA

        p = str(product_id)

        # --- Financial containment check ---
        if global_state and global_state.get_state() == CONTENCAO_FINANCEIRA:
            raise MarketLoopProductStateError(
                f"Product '{p}': MarketLoop blocked — system in CONTENÇÃO_FINANCEIRA."
            )

        # --- Product state check ---
        if state_manager:
            product_state = self._get_product_state(state_manager, p)
            if product_state != "Ativo":
                raise MarketLoopProductStateError(
                    f"Product '{p}': only Ativo products can enter the Market Loop. "
                    f"Current state: '{product_state}'."
                )

        # --- No-microcycle: reject if a cycle is already open ---
        open_cycle = self._find_open_cycle(p)
        if open_cycle:
            raise MarketLoopMicrocycleError(
                f"Product '{p}': a cycle (id={open_cycle['cycle_id']}) is already open. "
                f"Close it before starting a new one."
            )

        # --- Create new cycle ---
        now      = self._now()
        cycle_id = str(uuid.uuid4())
        cycle    = {
            "cycle_id":                  cycle_id,
            "product_id":                p,
            "current_phase":             0,          # 0 = not started yet
            "phases_completed":          [],
            "baseline_snapshot_version": None,
            "candidate_version":         None,
            "last_substitution_at":      None,
            "started_at":                now.isoformat(),
            "closed_at":                 None,
            "status":                    "open",
        }

        if p not in self._cycles:
            self._cycles[p] = []
        self._cycles[p].append(cycle)
        self._save()

        orchestrator.emit_event(
            event_type="market_cycle_started",
            payload={
                "cycle_id":   cycle_id,
                "product_id": p,
                "started_at": now.isoformat(),
            },
            source="MarketLoopEngine",
            product_id=p
        )
        logger.info(f"Market cycle started for '{p}': cycle_id={cycle_id}")
        return cycle

    # -----------------------------------------------------------------------

    def execute_phase(
        self,
        product_id:       str,
        phase:            int,
        orchestrator,
        global_state=None,
    ) -> dict:
        """
        Mark phase as 'in execution'.
        Validates immutable order — raises MarketLoopPhaseOrderError on violation.
        Emits: market_phase_started
        """
        from core.global_state import CONTENCAO_FINANCEIRA

        p = str(product_id)
        self._require_valid_phase(phase)

        if global_state and global_state.get_state() == CONTENCAO_FINANCEIRA:
            raise MarketLoopProductStateError(
                f"Product '{p}': phase execution blocked — system in CONTENÇÃO_FINANCEIRA."
            )

        cycle = self._require_open_cycle(p)
        self._validate_phase_order(cycle, phase, action="execute")

        now = self._now()
        cycle["current_phase"] = phase
        self._save()

        orchestrator.emit_event(
            event_type="market_phase_started",
            payload={
                "cycle_id":   cycle["cycle_id"],
                "phase":      phase,
                "phase_name": PHASES[phase],
                "started_at": now.isoformat(),
            },
            source="MarketLoopEngine",
            product_id=p
        )
        logger.info(f"Market phase {phase} ({PHASES[phase]}) started for '{p}'.")
        return cycle

    # -----------------------------------------------------------------------

    def evaluate_phase(
        self,
        product_id:       str,
        phase:            int,
        orchestrator,
        telemetry_engine,
    ) -> dict:
        """
        Evaluate the current phase using the official Telemetry snapshot.
        Marks phase as completed.
        Emits: market_phase_evaluated
        """
        p = str(product_id)
        self._require_valid_phase(phase)

        cycle    = self._require_open_cycle(p)
        snapshot = telemetry_engine.get_latest_snapshot(p)

        if not snapshot:
            logger.warning(f"evaluate_phase: no snapshot yet for '{p}'. Proceeding without metrics.")

        now = self._now()
        if phase not in cycle["phases_completed"]:
            cycle["phases_completed"].append(phase)

        # Set baseline snapshot version on first evaluation
        if cycle["baseline_snapshot_version"] is None and snapshot:
            cycle["baseline_snapshot_version"] = snapshot.get("version_number")

        self._save()

        orchestrator.emit_event(
            event_type="market_phase_evaluated",
            payload={
                "cycle_id":          cycle["cycle_id"],
                "phase":             phase,
                "phase_name":        PHASES[phase],
                "evaluated_at":      now.isoformat(),
                "snapshot_version":  snapshot.get("version_number") if snapshot else None,
                "rpm":               snapshot.get("rpm", 0) if snapshot else 0,
                "roas":              snapshot.get("roas", 0) if snapshot else 0,
                "margin":            snapshot.get("margin", 0) if snapshot else 0,
            },
            source="MarketLoopEngine",
            product_id=p
        )
        logger.info(
            f"Market phase {phase} ({PHASES[phase]}) evaluated for '{p}'. "
            f"Snapshot: {snapshot.get('version_number') if snapshot else 'N/A'}"
        )
        return {"cycle": cycle, "snapshot": snapshot}

    # -----------------------------------------------------------------------

    def apply_substitution_if_valid(
        self,
        product_id:        str,
        orchestrator,
        telemetry_engine,
        baseline_snapshot,
    ) -> dict:
        """
        Compare current Telemetry snapshot against baseline.
        If RPM↑ or ROAS↑ (without exceeding margin degradation limit):
            → Route promotion through Orchestrator.receive_event('version_promotion_requested')
            → Emit baseline_replaced
        Otherwise:
            → No substitution

        NOTE: version_manager is no longer called directly.
        All promotions must go through Orchestrator governance layer.
        """
        p               = str(product_id)
        current_snap    = telemetry_engine.get_latest_snapshot(p)
        improved, reason = self._improved(baseline_snapshot, current_snap)
        now             = self._now()
        cycle           = self._require_open_cycle(p)

        if improved:
            if not current_snap or not current_snap.get("snapshot_id"):
                logger.warning(
                    f"[MarketLoop] apply_substitution_if_valid: product '{p}' shows improvement "
                    f"but telemetry snapshot has no snapshot_id — substitution aborted. "
                    f"A valid telemetry snapshot is required for constitutional promotion."
                )
                return {"substituted": False, "reason": "missing-snapshot-id"}

            # Route through Orchestrator — snapshot_id is mandatory for constitutional promotion
            orchestrator.receive_event(
                event_type="version_promotion_requested",
                payload={
                    "product_id":  p,
                    "snapshot_id": current_snap["snapshot_id"],
                },
            )

            cycle["last_substitution_at"] = now.isoformat()
            self._save()

            orchestrator.emit_event(
                event_type="baseline_replaced",
                payload={
                    "cycle_id":        cycle["cycle_id"],
                    "reason":          reason,
                    "snapshot_id":     current_snap["snapshot_id"],
                    "baseline_rpm":    baseline_snapshot.get("rpm", 0),
                    "current_rpm":     current_snap.get("rpm", 0) if current_snap else 0,
                    "baseline_roas":   baseline_snapshot.get("roas", 0),
                    "current_roas":    current_snap.get("roas", 0) if current_snap else 0,
                    "substituted_at":  now.isoformat(),
                },
                source="MarketLoopEngine",
                product_id=p
            )
            logger.info(f"Baseline substitution routed via Orchestrator for '{p}': {reason}")
            return {"substituted": True, "reason": reason, "snapshot_id": current_snap["snapshot_id"]}

        logger.info(f"No substitution for '{p}': {reason}")
        return {"substituted": False, "reason": reason}

    # -----------------------------------------------------------------------

    def rollback_if_loss(
        self,
        product_id:              str,
        orchestrator,
        telemetry_engine,
        pre_substitution_snapshot,
    ) -> dict:
        """
        If post-substitution snapshot is worse by more than rollback_loss_threshold:
            → Route rollback through Orchestrator.receive_event('version_rollback_requested')
            → Emit market_rollback_executed

        NOTE: version_manager is no longer called directly.
        All rollbacks must go through Orchestrator governance layer.
        """
        p          = str(product_id)
        post_snap  = telemetry_engine.get_latest_snapshot(p)
        regressed  = self._regressed(pre_substitution_snapshot, post_snap)
        now        = self._now()

        if regressed:
            # Route through Orchestrator — governance layer handles rollback
            orchestrator.receive_event(
                event_type="version_rollback_requested",
                payload={"product_id": p},
            )
            orchestrator.emit_event(
                event_type="market_rollback_executed",
                payload={
                    "cycle_id":         self._find_open_cycle(p, allow_none=True) and self._find_open_cycle(p)["cycle_id"],
                    "reason":           "post-substitution regression",
                    "pre_rpm":          pre_substitution_snapshot.get("rpm", 0),
                    "post_rpm":         post_snap.get("rpm", 0) if post_snap else 0,
                    "pre_margin":       pre_substitution_snapshot.get("margin", 0),
                    "post_margin":      post_snap.get("margin", 0) if post_snap else 0,
                    "rolled_back_at":   now.isoformat(),
                },
                source="MarketLoopEngine",
                product_id=p
            )
            logger.warning(f"Rollback routed via Orchestrator for '{p}'.")
            return {"rolled_back": True}

        return {"rolled_back": False}

    # -----------------------------------------------------------------------

    def close_cycle(
        self,
        product_id: str,
        orchestrator,
    ) -> dict:
        """
        Close the open cycle for a product.
        Emits: market_cycle_closed
        """
        p     = str(product_id)
        cycle = self._require_open_cycle(p)
        now   = self._now()

        cycle["closed_at"] = now.isoformat()
        cycle["status"]    = "closed"
        self._save()

        orchestrator.emit_event(
            event_type="market_cycle_closed",
            payload={
                "cycle_id":         cycle["cycle_id"],
                "product_id":       p,
                "phases_completed": cycle["phases_completed"],
                "closed_at":        now.isoformat(),
            },
            source="MarketLoopEngine",
            product_id=p
        )
        logger.info(f"Market cycle closed for '{p}': cycle_id={cycle['cycle_id']}")
        return cycle

    # =======================================================================
    # Internal helpers
    # =======================================================================

    def _find_open_cycle(self, p: str, allow_none: bool = False):
        history = self._cycles.get(p, [])
        for c in reversed(history):
            if c.get("status") == "open":
                return c
        return None

    def _require_open_cycle(self, p: str) -> dict:
        c = self._find_open_cycle(p)
        if not c:
            raise MarketLoopNoCycleError(
                f"Product '{p}': no open market cycle. Call start_new_cycle() first."
            )
        return c

    def _require_valid_phase(self, phase: int) -> None:
        if phase not in PHASES:
            raise MarketLoopPhaseOrderError(
                f"Phase {phase} is not valid. Valid phases: {list(PHASES.keys())}."
            )

    def _validate_phase_order(self, cycle: dict, requested_phase: int, action: str) -> None:
        completed = cycle["phases_completed"]
        last_completed = max(completed) if completed else 0

        # Cannot skip a phase
        expected_next = last_completed + 1
        if requested_phase != expected_next:
            raise MarketLoopPhaseOrderError(
                f"Cannot {action} phase {requested_phase} ({PHASES.get(requested_phase, '?')}). "
                f"Next expected phase is {expected_next} ({PHASES.get(expected_next, '?')}). "
                f"Completed phases: {completed}."
            )

        # Cannot repeat a phase
        if requested_phase in completed:
            raise MarketLoopPhaseOrderError(
                f"Phase {requested_phase} ({PHASES[requested_phase]}) already completed in this cycle."
            )

    def _get_product_state(self, state_manager, product_id: str) -> str:
        """Read product state from StateMachine states. Fallback: read from state_manager."""
        try:
            # Try to read from last_state_transition or product_states dict
            states = state_manager.get("product_states") or {}
            return states.get(product_id, "Desconhecido")
        except Exception:
            return "Desconhecido"

    def _improved(self, baseline: dict | None, current: dict | None) -> tuple[bool, str]:
        """
        Returns (True, reason) if current metrics show real improvement over baseline.
        Improvement condition:
            (rpm↑ by min_rpm_improvement OR roas↑ by min_roas_improvement)
            AND margin drop ≤ max_margin_degradation
        """
        if not baseline or not current:
            return False, "missing-snapshot"

        b_rpm  = baseline.get("rpm",    0.0)
        b_roas = baseline.get("roas",   0.0)
        b_mrg  = baseline.get("margin", 0.0)

        c_rpm  = current.get("rpm",    0.0)
        c_roas = current.get("roas",   0.0)
        c_mrg  = current.get("margin", 0.0)

        margin_drop = b_mrg - c_mrg
        if margin_drop > self.max_margin_degradation:
            return False, f"margin-degraded-by-{margin_drop:.4f}"

        rpm_gain  = c_rpm  - b_rpm  > self.min_rpm_improvement
        roas_gain = c_roas - b_roas > self.min_roas_improvement

        if rpm_gain and roas_gain:
            return True, f"rpm+{c_rpm - b_rpm:.4f},roas+{c_roas - b_roas:.4f}"
        if rpm_gain:
            return True, f"rpm+{c_rpm - b_rpm:.4f}"
        if roas_gain:
            return True, f"roas+{c_roas - b_roas:.4f}"
        return False, "no-improvement"

    def _regressed(self, pre: dict | None, post: dict | None) -> bool:
        """
        Returns True if post-substitution snapshot shows margin degradation
        beyond rollback_loss_threshold compared to pre-substitution.
        """
        if not pre or not post:
            return False
        margin_drop = pre.get("margin", 0.0) - post.get("margin", 0.0)
        return margin_drop > self.rollback_loss_threshold

    def _save(self) -> None:
        self._pers.save(self._cycles)
