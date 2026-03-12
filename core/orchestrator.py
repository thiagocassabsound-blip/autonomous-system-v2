"""
core/orchestrator.py — Write-Protected Orchestrator (A4 Updated)
All state writes MUST route through receive_event().
Telemetry events → TelemetryEngine / CycleManager services.
Finance events    → FinanceEngine service.
Sensitive events  → blocked if GlobalState == CONTENÇÃO_FINANCEIRA.
"""
import threading
from contextlib import contextmanager
from infrastructure.logger import get_logger
from core.global_state import CONTENCAO_FINANCEIRA
from core.substitution_service import SubstitutionService
from core.guardian_engine import GuardianEngine
import uuid
import copy
from datetime import datetime, timezone

logger = get_logger("Orchestrator")


class FinancialContainmentError(Exception):
    """
    Raised when a sensitive operation is attempted while the system
    is in CONTENÇÃO_FINANCEIRA state.
    """


# Events that REQUIRE product_id
_EVENTS_NEED_PRODUCT = frozenset({
    "state_transition_requested",
    "price_update_requested",
    "version_candidate_created",
    "version_promotion_requested",
    "snapshot_requested",
    "rollback_requested",
    "cycle_open_requested",
    "cycle_close_requested",
    # Market Loop (A6)
    "market_cycle_start_requested",
    "market_phase_execution_requested",
    "market_phase_evaluation_requested",
    "market_cycle_close_requested",
    # Pricing (A7)
    "pricing_offensive_requested",
    "pricing_defensive_requested",
    "pricing_evaluation_requested",
    # Version Manager (A8)
    "candidate_version_requested",
    "version_promotion_requested",
    "version_rollback_requested",
    "pricing_offensive_test_requested",
    "pricing_defensive_test_requested",
    "pricing_rollback_requested",
    # Maintenance (P9.4)
    "human_patch_event",
})

# Events that REQUIRE month_id
_EVENTS_NEED_MONTH = frozenset({
    "monthly_metric_recorded",
})

# Sensitive events blocked in CONTENÇÃO_FINANCEIRA
_EVENTS_BLOCKED_IN_CONTAINMENT = frozenset({
    "price_update_requested",
    "version_promotion_requested",
    "version_candidate_created",
    "ad_spend_registered",
    # Market Loop (A6)
    "market_cycle_start_requested",
    "market_phase_execution_requested",
    # Pricing (A7)
    "pricing_offensive_requested",
    "pricing_defensive_requested",
    # Version Manager (A8)
    "candidate_version_requested",
    "version_rollback_requested",
    "pricing_offensive_test_requested",
    "pricing_defensive_test_requested",
    # Commercial (A10)
    "payment_confirmed",
    # Product Creation (A14) — Draft creation blocked in CONTENÇÃO
    "product_creation_requested",
    "beta_approved_requested",
})


class Orchestrator:
    """
    Central write gatekeeper for autonomous-system-v2.

    - State writes:    guarded by _write_context() → StateManager
    - Telemetry/Finance writes: routed to service handlers (no state lock needed)
    - Financial containment:    blocks sensitive events in CONTENÇÃO_FINANCEIRA
    - Security pre-flight:      rate limit + source validation via SecurityLayer (A9)
    """

    def __init__(self, event_bus, state_manager):
        self._bus      = event_bus
        self._state    = state_manager
        self._lock     = threading.RLock() # Re-entrant lock for atomic transactions
        self._services: dict = {}
        self.guardian = GuardianEngine(self)
        logger.info("Orchestrator initialized with Guardian 2.0.")

    # ------------------------------------------------------------------
    # Service Registration
    # ------------------------------------------------------------------

    def register_service(self, name: str, service) -> None:
        """Register a named domain service (TelemetryEngine, CycleManager, FinanceEngine, …)."""
        self._services[name] = service
        logger.info(f"Service registered: '{name}'")

    def get_service(self, name: str):
        """Public accessor for registered services."""
        return self._services.get(name)

    # ------------------------------------------------------------------
    # Read-only state access
    # ------------------------------------------------------------------

    @property
    def state(self):
        return self._state

    # ------------------------------------------------------------------
    # Financial Containment Check
    # ------------------------------------------------------------------

    def _assert_financial_clearance(self, event_type: str) -> None:
        """Raise FinancialContainmentError if system is in CONTENÇÃO_FINANCEIRA."""
        if event_type not in _EVENTS_BLOCKED_IN_CONTAINMENT:
            return
        gs = self._services.get("global_state")
        if gs and gs.get_state() == CONTENCAO_FINANCEIRA:
            raise FinancialContainmentError(
                f"Event '{event_type}' blocked: system is in CONTENÇÃO_FINANCEIRA. "
                f"Resolve financial situation before proceeding."
            )

    def get_traffic_mode(self) -> str:
        """
        Returns the current TRAFFIC_MODE governance policy.
        manual | ads | disabled
        """
        # Try to get from global_state service if registered
        gs = self._services.get("global_state")
        if gs and hasattr(gs, 'get_traffic_mode'):
            return gs.get_traffic_mode()
        
        # Fallback to environment variable
        import os
        return os.getenv("TRAFFIC_MODE", "manual").lower()

    def get_ads_system_mode(self) -> str:
        """
        Returns the current ADS_SYSTEM_MODE governance policy.
        enabled | disabled
        """
        gs = self._services.get("global_state")
        if gs and hasattr(gs, 'get_ads_system_mode'):
            return gs.get_ads_system_mode()
        
        import os
        return os.getenv("ADS_SYSTEM_MODE", "enabled").lower()

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def receive_event(
        self,
        event_type: str,
        payload:    dict,
        product_id: str  | None = None,
        month_id:   str  | None = None,
        source:     str  = "system",
        ip:         str  | None = None,
        user_role:  str  | None = None,
        event_id:   str  | None = None, # C5.3 Idempotency
    ) -> dict:
        """
        Validate, ledger-record, and dispatch a write event.
        Atomic & Idempotent implementation (C5.3).
        """
        # 1. Acquire global transactional lock
        with self._lock:
            if not isinstance(payload, dict):
                raise ValueError(f"payload must be dict, got {type(payload)}.")
                
            # Enforce or generate unique event_id
            eid = event_id or payload.get("event_id") or payload.get("id") or self._bus.generate_event_id()
            
            # 2. Check Idempotency (Persistent via state_manager)
            processed = self._state.get("processed_events", [])
            if eid in processed:
                logger.warning(f"Idempotency: Event {eid} already processed. Ignoring.")
                self.persist_event({
                    "event_type": "event_duplicate_ignored",
                    "product_id": product_id,
                    "payload": {"duplicate_id": eid, "event_type": event_type}
                })
                return {"status": "ignored", "event_id": eid, "event_type": event_type}

            if event_type in _EVENTS_NEED_PRODUCT and not product_id:
                raise ValueError(f"Event '{event_type}' requires product_id.")
            if event_type in _EVENTS_NEED_MONTH and not month_id:
                raise ValueError(f"Event '{event_type}' requires month_id.")

            # Pre-flight guards
            security = self._services.get("security")
            if security:
                security.pre_flight(event_type, source, ip, event_type, user_role)
            self._assert_financial_clearance(event_type)

            # 3. Execute Handlers (Logic before persistence)
            state_handler = self._STATE_HANDLERS.get(event_type)
            svc_handler   = self._SVC_HANDLERS.get(event_type)
            
            sm = self._services.get("state_machine")
            gs = self._services.get("global_state")

            try:
                if sm: sm._enter_orchestrated_context()
                if gs: gs._enter_orchestrated_context()

                # Execution Phase
                if state_handler:
                    # _write_context uses self._lock (RLock)
                    with self._write_context():
                        state_handler(self, self._state, payload)

                if svc_handler:
                    svc_handler(self, payload, product_id)

                # 4. Success -> Commit state (including idempotency index)
                with self._write_context():
                    # We create a new list to ensure the underlying dict change is detected
                    new_processed = list(processed)
                    new_processed.append(eid)
                    self._state.set("processed_events", new_processed)

                # 5. Persist Ledger (Final step of atomic success)
                try:
                    self._bus._enter_orchestrated_context()
                    formal = self._bus.append_event({
                        "event_id":   eid,
                        "event_type": event_type,
                        "product_id": product_id,
                        "month_id":   month_id,
                        "payload":    payload,
                        "source":     source,
                    })
                finally:
                    self._bus._exit_orchestrated_context()

                # Guardian scan (post-persist, as it doesn't alter state)
                self.guardian.process_event({**formal, "origin": "orchestrator" if source != "LEGACY" else "direct_write_attempt"})
                
                return formal

            except Exception as e:
                logger.error(f"Atomic Failure mid-execution [{event_type}]: {e}", exc_info=True)
                # Fail-safe: log failure without affecting state
                self.persist_event({
                    "event_type": "event_processing_failed",
                    "product_id": product_id,
                    "payload": {"event_id": eid, "error": str(e), "event_type": event_type}
                })
                raise
            finally:
                if sm: sm._exit_orchestrated_context()
                if gs: gs._exit_orchestrated_context()

    def persist_event(self, event: dict) -> None:
        """
        Internal gateway for GuardianEngine persistence.
        Appends directly to ledger without triggering handlers.
        """
        # Ensure event complies with EventBus requirements (must have payload)
        ledger_entry = {
            "event_type": event.get("event_type", "guardian_alert_emitted"),
            "product_id": event.get("product_id"),
            "payload":    event, # the full alert is stored as the formal payload
            "source":     "Guardian"
        }
        try:
            self._bus._enter_orchestrated_context()
            self._bus.append_event(ledger_entry) 
        finally:
            self._bus._exit_orchestrated_context()

    def set_global_state(self, new_value: str, reason: str = "Orchestrator authority"):
        """
        Authorized entry point for changing global system state.
        Bypasses legacy warnings and enforces formal transition.
        """
        gs = self._services.get("global_state")
        if not gs:
            logger.error("set_global_state: 'global_state' service not registered.")
            return
        
        try:
            gs._enter_orchestrated_context()
            gs.request_state_update(
                new_value,
                reason=reason,
                source="orchestrator",
                orchestrated=True
            )
        finally:
            gs._exit_orchestrated_context()

    def emit_event(self, event_type: str, payload: dict, source: str = None,
                   product_id: str = None, month_id: str = None) -> dict:
        """
        Official ledger emission gateway.
        All engines must route formal events through this method.
        """
        event = {
            "event_type": event_type,
            "payload": payload,
            "source": source or "orchestrator",
            "product_id": product_id,
            "month_id": month_id
        }

        try:
            self._bus._enter_orchestrated_context()
            return self._bus.append_event(event)
        finally:
            self._bus._exit_orchestrated_context()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._bus.subscribe("cycle_tick", self._on_cycle_tick)
        logger.info("Orchestrator started.")

    def _on_cycle_tick(self, payload: dict) -> None:
        logger.debug(f"Orchestrator: cycle_tick #{payload.get('tick', '?')}")
        # ── Etapa 2.6: Periodic system health checks ──────────────────────
        import os as _os
        self._tick_count = getattr(self, "_tick_count", 0) + 1

        health_interval = int(_os.getenv("HEALTH_CHECK_INTERVAL", "50"))
        gc_interval     = int(_os.getenv("PRODUCT_GC_INTERVAL",   "500"))

        if self._tick_count % health_interval == 0:
            try:
                from infra.system import health_monitor
                health_monitor.run_health_check(self)
                logger.debug("[Orchestrator] Health check ran at tick %d", self._tick_count)
            except Exception as _exc:
                logger.warning("[Orchestrator] Health check failed (non-fatal): %s", _exc)

        if self._tick_count % gc_interval == 0:
            try:
                from infra.system import product_gc
                product_gc.run_product_gc(self)
                logger.debug("[Orchestrator] Product GC ran at tick %d", self._tick_count)
            except Exception as _exc:
                logger.warning("[Orchestrator] Product GC failed (non-fatal): %s", _exc)

    def execute_structured_cycle(self, product_id: str) -> None:
        """
        Constitutional C4 Structured Market Loop: Exclusive Authority.
        Phase A: Guards
        Phase B: Initialization
        """
        p = str(product_id)
        
        # --- PHASE A: Execution Guards ---
        
        # 1. Product State check
        sm = self._services.get("state_machine")
        current_state = sm.get_state(p) if sm else "Unknown"
        if current_state != "Ativo":
            self.emit_event("market_cycle_blocked", {
                "reason": f"Product state is '{current_state}', expected 'Ativo'",
                "product_id": p
            }, product_id=p)
            return

        # 2. Financial alert / Global State check
        gs = self._services.get("global_state")
        g_state = gs.get_state() if gs else "NORMAL"
        if g_state == CONTENCAO_FINANCEIRA:
            self.emit_event("market_cycle_blocked", {
                "reason": "System is in CONTENÇÃO_FINANCEIRA",
                "product_id": p
            }, product_id=p)
            return

        # 3. Manual Pause check
        is_paused = self._state.get(f"product:{p}:paused", False)
        if is_paused:
            self.emit_event("market_cycle_blocked", {
                "reason": "Product is manually paused",
                "product_id": p
            }, product_id=p)
            return

        # 4. Cycle Already Running check
        active_cycles = self._state.get("active_cycles", {})
        if p in active_cycles:
            self.emit_event("market_cycle_blocked", {
                "reason": "A cycle is already running for this product",
                "product_id": p
            }, product_id=p)
            return

        # 5. Macro Exposure Pre-flight
        macro     = self._services.get("macro_exposure_governance_engine")
        finance   = self._services.get("finance")
        telemetry = self._services.get("telemetry")
        
        if macro and finance and telemetry:
            # Fetch current metrics for macro validation
            metrics = telemetry.get_latest_snapshot(p) or {}
            fin_status = finance.get_product_status(p) if hasattr(finance, "get_product_status") else {}
            
            # Simple pre-flight validation with 0 requested allocation
            # (Ensures base limits/state allow execution)
            total_cap = finance.get_total_capital() if hasattr(finance, "get_total_capital") else 1000000
            
            verdict = macro.validate_macro_exposure(
                product_id=p,
                channel_id="main",
                requested_allocation=0,
                current_product_allocation=fin_status.get("allocation", 0),
                current_channel_allocation=fin_status.get("allocation", 0), # Simplified
                current_global_allocation=finance.get_total_allocation() if hasattr(finance, "get_total_allocation") else 0,
                total_capital=total_cap,
                roas_avg=metrics.get("roas", 0),
                score_global=self._state.get("last_score", 0),
                refund_ratio_avg=metrics.get("refund_ratio", 0),
                global_state=g_state,
                financial_alert_active=(g_state == CONTENCAO_FINANCEIRA)
            )
            
            if not verdict.get("allowed"):
                self.emit_event("market_cycle_blocked", {
                    "reason": f"Macro exposure validation failed: {verdict.get('violations')}",
                    "product_id": p
                }, product_id=p)
                return

        # --- PHASE B: Initialization ---
        cycle_id = str(uuid.uuid4())
        now_iso = datetime.now(timezone.utc).isoformat()
        
        baseline_metrics = telemetry.get_latest_snapshot(p) if telemetry else {}
        
        # Snapshots for ledger
        global_snapshot = {"state": g_state}
        financial_snapshot = {
            "total_capital": finance.get_total_capital() if finance and hasattr(finance, "get_total_capital") else 0,
            "total_allocation": finance.get_total_allocation() if finance and hasattr(finance, "get_total_allocation") else 0
        }

        # Emit cycle_started
        self.emit_event("cycle_started", {
            "cycle_id": cycle_id,
            "product_id": p,
            "start_timestamp": now_iso,
            "baseline_metrics": baseline_metrics,
            "global_state_snapshot": global_snapshot,
            "financial_state_snapshot": financial_snapshot,
            "current_phase": 1
        }, product_id=p)

        # Persist to StateManager
        with self._write_context():
            active_cycles = self._state.get("active_cycles", {})
            active_cycles[p] = {
                "cycle_id": cycle_id,
                "product_id": p,
                "current_phase": 1,
                "start_timestamp": now_iso,
                "original_baseline_metrics": copy.deepcopy(baseline_metrics), # immutable base
                "baseline_metrics": copy.deepcopy(baseline_metrics),          # evolving optimization base
                "phase_history": []
            }
            self._state.set("active_cycles", active_cycles)
            
        logger.info(f"C4 Cycle started: product={p} id={cycle_id}")

        # --- PHASE C: Phases 1–3 Loop ---
        for ph in [1, 2, 3]:
            # 1. Start Phase
            self.emit_event("market_phase_started", {
                "cycle_id": cycle_id,
                "phase": ph,
                "product_id": p
            }, product_id=p)

            # 2. Request Candidate Version via formal event
            self.receive_event("candidate_version_requested", {
                "product_id": p,
                "cycle_id": cycle_id,
                "phase_id": ph
            }, product_id=p)

            # 3. Simulate Phase Duration & Metrics Generation
            # In a real system, this would be an external trigger.
            # Here we simulate the end of the phase and snapshot creation.
            if telemetry:
                telemetry.close_cycle_snapshot(p, cycle_id, self, phase_id=ph)

            # 4. Fetch Metrics
            candidate_metrics = telemetry.get_official_cycle_metrics(p, cycle_id, ph) if telemetry else {}
            
            # 5. Evaluate Substitution
            res = SubstitutionService.evaluate(
                candidate=candidate_metrics,
                baseline=active_cycles[p]["baseline_metrics"]
            )

            if res["approved"]:
                # 6. Promote Candidate via formal event
                self.receive_event("version_promotion_requested", {
                    "product_id": p,
                    "snapshot_id": candidate_metrics.get("snapshot_id")
                }, product_id=p)
                
                # Update loop baseline for next phase
                active_cycles[p]["baseline_metrics"] = candidate_metrics
                
                self.emit_event("version_promoted", {
                    "product_id": p,
                    "phase": ph,
                    "reason": res["reason"],
                    "metrics": candidate_metrics
                }, product_id=p)
            else:
                # 7. Trigger Rollback via formal event
                self.receive_event("version_rollback_requested", {
                    "product_id": p
                }, product_id=p)
                
                self.emit_event("version_rejected", {
                    "product_id": p,
                    "phase": ph,
                    "reason": res["reason"],
                    "metrics": candidate_metrics
                }, product_id=p)

            # 8. Complete Phase
            active_cycles[p]["phase_history"].append({
                "phase": ph,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": "promoted" if res["approved"] else "rejected",
                "metrics": candidate_metrics
            })
            
            self.emit_event("market_phase_completed", {
                "cycle_id": cycle_id,
                "phase": ph,
                "product_id": p
            }, product_id=p)

        # --- PHASE D: Phase 4 Pricing ---
        # A. Pre-conditions
        self.emit_event("market_phase_started", {"cycle_id": cycle_id, "phase": 4, "product_id": p}, product_id=p)
        cycle_data = active_cycles.get(p, {})
        logger.info(f"[C4] Cycle {cycle_id} entering Phase 4 Pricing for {p}")
        consecutive_increases = cycle_data.get("consecutive_price_increases", 0)
        
        # Check if first structured cycle
        # We assume history search or a flag. Let's use history.
        cycle_history = self._state.get("cycle_history", [])
        p_cycles = [c for c in cycle_history if c.get("product_id") == p]
        is_first_cycle = len(p_cycles) == 0

        # Financial Alert
        fe = self._services.get("finance")
        financial_alert = False
        if fe and hasattr(fe, "get_state"):
            fs = fe.get_state()
            stripe = float(fs.get("stripe_current_balance", 0.0))
            openai = float(fs.get("openai_current_balance", 0.0))
            burn_val = fe.calculate_daily_burn() if hasattr(fe, "calculate_daily_burn") else 0.0
            burn = float(burn_val) if burn_val is not None else 0.0
            days = (stripe + openai) / burn if burn > 0 else 999_999
            min_buf = float(getattr(fe, "min_buffer_days", 30))
            financial_alert = (days < min_buf)

        # Macro Validation
        macro_v = self._services.get("macro_exposure_governance_engine")
        macro_ok = True
        if macro_v:
            res_m = macro_v.validate_macro_exposure(p)
            macro_ok = res_m.get("allowed", False)

        gs_svc = self._services.get("global_state")
        gs_val = gs_svc.get_state() if gs_svc else "NORMAL"
        in_containment = gs_val in ["CONTENÇÃO", "CONTENÇÃO_FINANCEIRA"]

        # Cooldown check: prevent pricing test if previous cycle triggered fail-safe
        last_cycle = p_cycles[-1] if p_cycles else {}
        fail_safe_cooldown = last_cycle.get("fail_safe_triggered", False)

        block_pricing = (
            is_first_cycle or 
            consecutive_increases >= 3 or 
            financial_alert or 
            in_containment or 
            not macro_ok or
            fail_safe_cooldown
        )

        if block_pricing:
            reason = "First cycle" if is_first_cycle else \
                     "Max increases reached" if consecutive_increases >= 3 else \
                     "Financial alert" if financial_alert else \
                     "System containment" if in_containment else \
                     "Fail-safe cooldown active" if fail_safe_cooldown else \
                     "Macro exposure block"
            self.emit_event("pricing_test_blocked", {
                "product_id": p,
                "cycle_id": cycle_id,
                "reason": reason
            }, product_id=p)
        else:
            # Determine Offensive vs Defensive
            # Defensive (-15%) only allowed if at least one offensive increase validated previously
            prior_success = cycle_data.get("offensive_increases_validated", 0) > 0
            
            # Logic: If RPM/ROAS is strong from Phase 1-3, go Offensive.
            # For simplicity in this structure, we'll try Offensive if possible, 
            # or Defensive if we are protecting a high base.
            # Real decision logic would be more complex.
            
            # Use current baseline from Phase 3 completion
            baseline_metrics = cycle_data.get("baseline_metrics", {})
            rpm_base = baseline_metrics.get("rpm", 0.0)
            logger.info(f"[C4] Phase 4 Pricing: rpm_base={rpm_base:.4f} for {p}")

            if not prior_success or consecutive_increases < 2:
                # --- OFFENSIVE TEST (+25%) ---
                self.receive_event("pricing_offensive_test_requested", {"product_id": p}, product_id=p)
                
                # Fetch new metrics after applying (simulated delay/duration)
                if telemetry:
                    telemetry.close_cycle_snapshot(p, cycle_id, self, phase_id=4)
                
                metrics_test = telemetry.get_official_cycle_metrics(p, cycle_id, 4) if telemetry else {}
                rpm_test = metrics_test.get("rpm", 0.0)

                if rpm_test >= rpm_base * 0.95:
                    consecutive_increases += 1
                    cycle_data["offensive_increases_validated"] = cycle_data.get("offensive_increases_validated", 0) + 1
                    self.emit_event("price_increase_validated", {
                        "product_id": p,
                        "rpm_test": rpm_test,
                        "rpm_base": rpm_base,
                        "consecutive": consecutive_increases
                    }, product_id=p)
                else:
                    logger.warning(f"[C4] Phase 4 Offensive Test failed for {p}: rpm_test={rpm_test:.4f} < rpm_base={rpm_base:.4f} * 0.95")
                    self.receive_event("pricing_rollback_requested", {"product_id": p}, product_id=p)
                    self.emit_event("price_increase_reverted", {
                        "product_id": p,
                        "rpm_test": rpm_test,
                        "rpm_base": rpm_base
                    }, product_id=p)
                    consecutive_increases = 0
            else:
                # --- DEFENSIVE MODE (-15%) ---
                self.receive_event("pricing_defensive_test_requested", {"product_id": p}, product_id=p)
                
                if telemetry:
                    telemetry.close_cycle_snapshot(p, cycle_id, self, phase_id=4)
                
                metrics_test = telemetry.get_official_cycle_metrics(p, cycle_id, 4) if telemetry else {}
                rpm_test = metrics_test.get("rpm", 0.0)

                if rpm_test >= rpm_base * 1.05:
                    self.emit_event("price_defense_validated", {
                        "product_id": p,
                        "rpm_test": rpm_test,
                        "rpm_base": rpm_base
                    }, product_id=p)
                else:
                    self.receive_event("pricing_rollback_requested", {"product_id": p}, product_id=p)
                    self.emit_event("price_defense_reverted", {
                        "product_id": p,
                        "rpm_test": rpm_test,
                        "rpm_base": rpm_base
                    }, product_id=p)

        # Update cycle data
        active_cycles[p] = cycle_data
        self.emit_event("market_phase_completed", {"cycle_id": cycle_id, "phase": 4, "product_id": p}, product_id=p)
        
        # --- PHASE E: Phase 5 Macro Governance ---
        self.emit_event("market_phase_started", {"cycle_id": cycle_id, "phase": 5, "product_id": p}, product_id=p)
        
        # Fetch current metrics post-pricing
        if telemetry:
            telemetry.close_cycle_snapshot(p, cycle_id, self, phase_id=5)
        metrics_p5 = telemetry.get_official_cycle_metrics(p, cycle_id, 5) if telemetry else {}
        
        # Formal Macro Validation
        self.receive_event("macro_exposure_validation_requested", {
            "product_id": p,
            "cycle_id": cycle_id,
            "roas_avg": metrics_p5.get("roas", 0.0),
            "refund_ratio_avg": metrics_p5.get("refund_ratio", 0.0),
            "global_state": gs_val,
            "financial_alert_active": financial_alert
        }, product_id=p)
        
        self.emit_event("market_phase_completed", {"cycle_id": cycle_id, "phase": 5, "product_id": p}, product_id=p)

        # --- PHASE F: Phase 6 Fail-safe Monitor ---
        self.emit_event("market_phase_started", {"cycle_id": cycle_id, "phase": 6, "product_id": p}, product_id=p)
        
        # Monitor for structural decline (Hard Floor: RPM < 50% of original baseline)
        rpm_current = metrics_p5.get("rpm", 0.0)
        rpm_initial = cycle_data.get("original_baseline_metrics", {}).get("rpm", 0.0)
        
        if rpm_initial > 0 and rpm_current < rpm_initial * 0.5:
            # anti-oscillation: only trigger once per cycle
            if cycle_data.get("fail_safe_triggered_cycle_id") == cycle_id:
                logger.info(f"[C4] Fail-safe already triggered for cycle {cycle_id}. Skipping repeat.")
            else:
                cycle_data["fail_safe_triggered_cycle_id"] = cycle_id
                cycle_data["fail_safe_triggered"] = True
                
                logger.error(f"[C4] Structural Decline Detected for {p}: current={rpm_current:.4f} < initial={rpm_initial:.4f}*0.5")
                drop_pct = (1.0 - (rpm_current / rpm_initial)) * 100.0 if rpm_initial > 0 else 0.0
                
                self.emit_event("product_structural_decline_detected", {
                    "product_id": p,
                    "cycle_id": cycle_id,
                    "baseline_rpm": float(rpm_initial),
                    "current_rpm": float(rpm_current),
                    "percentage_drop": float(drop_pct),
                    "snapshot_id": metrics_p5.get("snapshot_id", ""),
                    "timestamp": int(datetime.now(timezone.utc).timestamp())
                }, product_id=p)

                self.emit_event("fail_safe_lock_applied", {
                    "product_id": p,
                    "cycle_id": cycle_id,
                    "reason": "structural_decline_cooldown_active"
                }, product_id=p)

                # Automatic Rollback if critical
                self.receive_event("version_rollback_requested", {"product_id": p}, product_id=p)
                self.receive_event("pricing_rollback_requested", {"product_id": p}, product_id=p)
        
        self.emit_event("market_phase_completed", {"cycle_id": cycle_id, "phase": 6, "product_id": p}, product_id=p)

        # --- PHASE G: Phase 7 Finalization ---
        self.emit_event("market_phase_started", {"cycle_id": cycle_id, "phase": 7, "product_id": p}, product_id=p)
        
        # Final snapshot and history persistence
        final_metrics = metrics_p5 # Use P5/P6 metrics as final
        
        cycle_summary = {
            "id": cycle_id,
            "product_id": p,
            "started_at": cycle_data.get("started_at"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "final_metrics": final_metrics,
            "consecutive_increases": consecutive_increases,
            "offensive_validated": cycle_data.get("offensive_increases_validated", 0),
            "fail_safe_triggered": cycle_data.get("fail_safe_triggered", False),
            "phase_history": cycle_data.get("phase_history", [])
        }
        
        with self._write_context():
            history = self._state.get("cycle_history", [])
            history.append(cycle_summary)
            self._state.set("cycle_history", history)
            
            # Clear active cycle
            current_active = self._state.get("active_cycles", {})
            if p in current_active:
                del current_active[p]
            self._state.set("active_cycles", current_active)

        self.emit_event("market_phase_completed", {"cycle_id": cycle_id, "phase": 7, "product_id": p}, product_id=p)
        self.emit_event("market_cycle_completed", {"cycle_id": cycle_id, "product_id": p}, product_id=p)
        logger.info(f"[C4] Market Cycle Completed: product={p} cycle_id={cycle_id}")

    # ------------------------------------------------------------------
    # Write context — PRIVATE
    # ------------------------------------------------------------------

    @contextmanager
    def _write_context(self):
        with self._lock:
            self._state._locked = False
            try:
                yield self._state
            finally:
                self._state._locked = True

    # ==================================================================
    # STATE HANDLERS — called inside _write_context
    # ==================================================================

    def _h_active_cycles_updated(self, state, payload: dict) -> None:
        state.set("active_cycles", payload["active_cycles"])

    def _h_cycle_completed_recorded(self, state, payload: dict) -> None:
        state.set("cycle_history", payload["cycle_history"])
        state.set("active_cycles", payload["active_cycles"])
        state.set("metrics",       payload["metrics"])

    def _h_opportunity_counted(self, state, payload: dict) -> None:
        metrics = state.get("metrics", {})
        metrics["total_opportunities"] = metrics.get("total_opportunities", 0) + 1
        state.set("metrics", metrics)

    def _h_score_recorded(self, state, payload: dict) -> None:
        state.set("last_score", payload.get("score"))

    def _h_economic_evaluation_recorded(self, state, payload: dict) -> None:
        state.set("last_economic_evaluation", payload)

    def _h_metric_update(self, state, payload: dict) -> None:
        metrics = state.get("metrics", {})
        metrics.update(payload.get("updates", {}))
        state.set("metrics", metrics)

    def _h_price_update(self, state, payload: dict) -> None:
        state.set("product_price", payload.get("price"))

    _STATE_HANDLERS: dict = {
        "active_cycles_updated":        _h_active_cycles_updated,
        "cycle_completed_recorded":     _h_cycle_completed_recorded,
        "opportunity_counted":          _h_opportunity_counted,
        "score_recorded":               _h_score_recorded,
        "economic_evaluation_recorded": _h_economic_evaluation_recorded,
        "metric_update_requested":      _h_metric_update,
        "price_update_requested":       _h_price_update,
    }

    # ==================================================================
    # SERVICE HANDLERS — Telemetry
    # ==================================================================

    def _sh_visit_recorded(self, payload: dict, product_id: str | None) -> None:
        tm  = self._services.get("telemetry")
        pid = payload.get("product_id") or product_id
        if tm and pid:
            tm.record_visit(pid)

    def _sh_revenue_recorded(self, payload: dict, product_id: str | None) -> None:
        tm  = self._services.get("telemetry")
        pid = payload.get("product_id") or product_id
        amt = float(payload.get("amount", 0))
        if tm and pid:
            tm.record_revenue(pid, amt)

    def _sh_ad_spend_recorded(self, payload: dict, product_id: str | None) -> None:
        tm  = self._services.get("telemetry")
        pid = payload.get("product_id") or product_id
        amt = float(payload.get("amount", 0))
        if tm and pid:
            tm.record_ad_spend(pid, amt)

    def _sh_refund_recorded(self, payload: dict, product_id: str | None) -> None:
        tm  = self._services.get("telemetry")
        pid = payload.get("product_id") or product_id
        amt = float(payload.get("amount", 0))
        if tm and pid:
            tm.record_refund(pid, amt)

    def _sh_cycle_open_requested(self, payload: dict, product_id: str | None) -> None:
        cm  = self._services.get("cycle_manager")
        pid = payload.get("product_id") or product_id
        if cm and pid:
            cm.open_cycle(pid, orchestrator=self)

    def _sh_cycle_close_requested(self, payload: dict, product_id: str | None) -> None:
        cm  = self._services.get("cycle_manager")
        tm  = self._services.get("telemetry")
        pid = payload.get("product_id") or product_id
        if not (cm and tm and pid):
            logger.warning("cycle_close_requested: missing services or product_id.")
            return
        try:
            closed   = cm.close_cycle(pid, orchestrator=self)
            snapshot = tm.close_cycle_snapshot(pid, closed["cycle_id"], orchestrator=self)
            self._bus.emit("cycle_snapshot_created", snapshot)
        except Exception as e:
            logger.error(f"cycle_close_requested failed for '{pid}': {e}")
            raise

    # ==================================================================
    # SERVICE HANDLERS — Finance (A4)
    # ==================================================================

    def _sh_stripe_balance_updated(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        amt = float(payload.get("amount", payload.get("balance", 0)))
        if fe:
            fe.register_stripe_balance(amt, orchestrator=self)

    def _sh_stripe_revenue_recorded(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        amt = float(payload.get("amount", 0))
        if fe:
            fe.register_stripe_revenue(amt, orchestrator=self)

    def _sh_stripe_refund_recorded(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        amt = float(payload.get("amount", 0))
        if fe:
            fe.register_stripe_refund(amt, orchestrator=self)

    def _sh_openai_balance_updated(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        amt = float(payload.get("amount", payload.get("balance", 0)))
        if fe:
            fe.register_openai_balance(amt, orchestrator=self)

    def _sh_ad_spend_registered(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        amt = float(payload.get("amount", 0))
        if fe:
            fe.register_ad_spend(amt, orchestrator=self)

    def _sh_financial_health_check(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        if fe:
            fe.validate_financial_health(orchestrator=self)

    def _sh_financial_projection_requested(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        if fe:
            fe.project_days_remaining(orchestrator=self)

    # ==================================================================
    # SERVICE HANDLERS — Acquisition Engines (Ads, SEO, Outreach)
    # ==================================================================

    def _sh_ads_cost_reported(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        amt = float(payload.get("amount", payload.get("ad_spend", 0)))
        if fe:
            fe.register_ad_spend(amt, orchestrator=self)

    def _sh_ads_budget_limit_reached(self, payload: dict, _pid) -> None:
        fe  = self._services.get("finance")
        if fe:
            fe.validate_financial_health(orchestrator=self)

    def _sh_campaign_performance_event(self, payload: dict, product_id: str | None) -> None:
        tm = self._services.get("telemetry")
        fe = self._services.get("finance")
        pid = payload.get("product_id") or product_id
        spend = float(payload.get("ad_spend", 0))
        revenue = float(payload.get("revenue_generated", 0))

        if fe and spend > 0:
            fe.register_ad_spend(spend, orchestrator=self)
        if tm and pid:
            if spend > 0:
                tm.record_ad_spend(pid, spend)
            if revenue > 0:
                tm.record_revenue(pid, revenue)

    def _sh_ads_campaign_created(self, payload: dict, product_id: str | None) -> None:
        ple = self._services.get("product_life")
        pid = payload.get("product_id") or product_id
        if ple and pid:
            ple.update_metadata(pid, {
                "campaign_id": payload.get("campaign_id"),
                "campaign_status": payload.get("status"),
                "account_id": payload.get("account_id")
            })

    # ==================================================================
    # SERVICE HANDLERS — Product Life (A5 + A14)
    # ==================================================================

    def _sh_product_creation_requested(self, payload: dict, product_id: str | None) -> None:
        """
        A14: Handle product_creation_requested → ProductLifeEngine.create_draft().

        Required payload fields:
            opportunity_id, emotional_score, monetization_score,
            growth_percent, competitive_gap_flag, justification_snapshot,
            version_id, timestamp

        Only callable via Orchestrator.receive_event().
        Blocked in CONTENÇÃO_FINANCEIRA.
        """
        ple = self._services.get("product_life")
        if not ple:
            logger.error("product_creation_requested: 'product_life' service not registered.")
            return

        # Validate payload completeness
        required = ["opportunity_id", "emotional_score", "monetization_score",
                    "growth_percent", "justification_snapshot", "version_id"]
        missing = [f for f in required if f not in payload]
        if missing:
            logger.error(
                f"product_creation_requested: missing required payload fields: {missing}"
            )
            raise ValueError(
                f"product_creation_requested: missing fields {missing}. "
                f"Required: {required}"
            )

        logger.info(
            f"[A14] Orchestrator routing product_creation_requested "
            f"(opportunity_id={payload.get('opportunity_id')}) → create_draft()"
        )
        try:
            result = ple.create_draft(
                orchestrator=self,
                opportunity_id=payload["opportunity_id"],
                emotional_score=float(payload.get("emotional_score", 0)),
                monetization_score=float(payload.get("monetization_score", 0)),
                growth_percent=float(payload.get("growth_percent", 0)),
                competitive_gap_flag=bool(payload.get("competitive_gap_flag", False)),
                justification_snapshot=payload.get("justification_snapshot", {}),
                version_id=payload.get("version_id", ""),
                orchestrated=True,
            )
            logger.info(
                f"[A14] Draft created: product_id='{result['product_id']}'"
            )
        except Exception as e:
            logger.error(f"[A14] product_creation_requested failed: {e}")
            raise

    def _sh_beta_approved_requested(self, payload: dict, product_id: str | None) -> None:
        """
        A14: Handle beta_approved_requested → ProductLifeEngine.start_beta().

        Flow: Draft → beta_approved_requested (human) → Orchestrator → start_beta()

        Passes orchestrated=True, global_state, and financial_alert_active.
        Guards in start_beta() enforce:
          - CONTENÇÃO_FINANCEIRA
          - active_beta_count < 2
          - financial_alert_active == False
        """
        ple = self._services.get("product_life")
        pid = payload.get("product_id") or product_id
        if not (ple and pid):
            logger.error("beta_approved_requested: missing 'product_life' service or product_id.")
            return

        gs  = self._services.get("global_state")
        financial_alert = bool(payload.get("financial_alert_active", False))

        logger.info(
            f"[A14] Orchestrator routing beta_approved_requested '{pid}' → start_beta()"
        )
        try:
            ple.start_beta(
                product_id=pid,
                orchestrator=self,
                orchestrated=True,
                global_state=gs,
                financial_alert_active=financial_alert,
            )
        except Exception as e:
            logger.error(f"[A14] beta_approved_requested failed for '{pid}': {e}")
            raise

    def _sh_beta_start_requested(self, payload: dict, product_id: str | None) -> None:
        ple = self._services.get("product_life")
        pid = payload.get("product_id") or product_id
        gs  = self._services.get("global_state")
        if ple and pid:
            ple.start_beta(
                pid,
                self,
                orchestrated=True,
                global_state=gs,
            )

    def _sh_beta_close_requested(self, payload: dict, product_id: str | None) -> None:
        ple = self._services.get("product_life")
        pid = payload.get("product_id") or product_id
        if ple and pid:
            ple.close_beta(pid, orchestrator=self)

    def _sh_beta_expiration_check(self, payload: dict, product_id: str | None) -> None:
        ple = self._services.get("product_life")
        pid = payload.get("product_id") or product_id
        if ple and pid:
            ple.check_beta_expiration(pid, orchestrator=self)

    def _sh_post_beta_consolidation_requested(self, payload: dict, product_id: str | None) -> None:
        ple = self._services.get("product_life")
        pid = payload.get("product_id") or product_id
        if not (ple and pid):
            logger.warning("post_beta_consolidation_requested: missing service or product_id.")
            return

        telemetry    = self._services.get("telemetry")
        state_machine = self._services.get("state_machine")
        global_state  = self._services.get("global_state")

        if not (telemetry and state_machine):
            logger.error("post_beta_consolidation_requested: telemetry or state_machine not registered.")
            return

        try:
            ple.consolidate_post_beta(
                product_id=pid,
                orchestrator=self,
                telemetry_engine=telemetry,
                state_machine=state_machine,
                global_state=global_state,
            )
        except Exception as e:
            logger.error(f"post_beta_consolidation_requested failed for '{pid}': {e}")
            raise

    # ==================================================================
    # SERVICE HANDLERS — Market Loop (A6)
    # ==================================================================

    def _sh_market_cycle_start(self, payload: dict, product_id: str | None) -> None:
        mle = self._services.get("market_loop")
        pid = payload.get("product_id") or product_id
        if not (mle and pid):
            return
        sm  = self._services.get("state_manager_ref")
        gs  = self._services.get("global_state")
        mle.start_new_cycle(pid, orchestrator=self, state_manager=sm, global_state=gs)

    def _sh_market_phase_execute(self, payload: dict, product_id: str | None) -> None:
        mle   = self._services.get("market_loop")
        pid   = payload.get("product_id") or product_id
        phase = int(payload.get("phase", 0))
        gs    = self._services.get("global_state")
        if mle and pid and phase:
            mle.execute_phase(pid, phase, orchestrator=self, global_state=gs)

    def _sh_market_phase_evaluate(self, payload: dict, product_id: str | None) -> None:
        mle   = self._services.get("market_loop")
        pid   = payload.get("product_id") or product_id
        phase = int(payload.get("phase", 0))
        tm    = self._services.get("telemetry")
        if mle and pid and phase and tm:
            mle.evaluate_phase(pid, phase, orchestrator=self, telemetry_engine=tm)

    def _sh_market_cycle_close(self, payload: dict, product_id: str | None) -> None:
        mle = self._services.get("market_loop")
        pid = payload.get("product_id") or product_id
        if mle and pid:
            mle.close_cycle(pid, orchestrator=self)

    # ==================================================================
    # SERVICE HANDLERS — Pricing (A7)
    # ==================================================================

    def _sh_pricing_offensive(self, payload: dict, product_id: str | None) -> None:
        pe  = self._services.get("pricing")
        pid = payload.get("product_id") or product_id
        gs  = self._services.get("global_state")
        mle = self._services.get("market_loop")
        if pe and pid:
            pe.apply_offensive_increase(pid, orchestrator=self, global_state=gs, market_loop=mle)

    def _sh_pricing_evaluation(self, payload: dict, product_id: str | None) -> None:
        pe  = self._services.get("pricing")
        pid = payload.get("product_id") or product_id
        if not (pe and pid):
            return
        pre_snap  = payload.get("pre_snapshot", {})
        post_snap = payload.get("post_snapshot", {})
        pe.evaluate_pricing_performance(pid, pre_snap, post_snap, orchestrator=self)

    def _sh_pricing_defensive(self, payload: dict, product_id: str | None) -> None:
        pe  = self._services.get("pricing")
        pid = payload.get("product_id") or product_id
        gs  = self._services.get("global_state")
        mle = self._services.get("market_loop")
        if pe and pid:
            pe.apply_defensive_reduction(pid, orchestrator=self, global_state=gs, market_loop=mle)

    def _sh_pricing_offensive_test(self, payload: dict, product_id: str | None) -> None:
        pe = self._services.get("pricing")
        pid = payload.get("product_id") or product_id
        if pe and pid:
            pe.apply_offensive_increase(pid, orchestrator=self)

    def _sh_pricing_defensive_test(self, payload: dict, product_id: str | None) -> None:
        pe = self._services.get("pricing")
        pid = payload.get("product_id") or product_id
        if pe and pid:
            pe.apply_defensive_reduction(pid, orchestrator=self)

    def _sh_pricing_rollback(self, payload: dict, product_id: str | None) -> None:
        pe = self._services.get("pricing")
        pid = payload.get("product_id") or product_id
        if pe and pid:
            pe.rollback_price(pid, orchestrator=self)

    # ==================================================================
    # SERVICE HANDLERS — Version Manager (A8)
    # ==================================================================

    def _sh_version_candidate(self, payload: dict, product_id: str | None) -> None:
        vm   = self._services.get("version_manager")
        pid  = payload.get("product_id") or product_id
        if vm and pid:
            vm.create_candidate(
                pid,
                version_id=payload.get("version_id"),
                snapshot_id=payload.get("snapshot_id"),
                linked_price=payload.get("linked_price"),
                orchestrator=self,
            )

    def _sh_version_promote(self, payload: dict, product_id: str | None) -> None:
        vm  = self._services.get("version_manager")
        pid = payload.get("product_id") or product_id
        gs  = self._services.get("global_state")
        if vm and pid:
            # Determine financial alert state from FinanceEngine or payload
            fe = self._services.get("finance")
            financial_alert_active = bool(payload.get("financial_alert_active", False))
            if fe and not payload.get("financial_alert_active"):
                # Derive from current projection if not explicitly provided
                fs = fe.get_state() if hasattr(fe, "get_state") else {}
                stripe  = fs.get("stripe_current_balance", 0.0)
                openai  = fs.get("openai_current_balance", 0.0)
                burn    = fe.calculate_daily_burn() if hasattr(fe, "calculate_daily_burn") else 0.0
                days    = round((stripe + openai) / burn, 2) if burn > 0 else 999_999
                financial_alert_active = (days < fe.min_buffer_days) if hasattr(fe, "min_buffer_days") else False
            vm.promote_candidate(
                pid,
                snapshot_id=payload.get("snapshot_id", ""),
                linked_price=payload.get("linked_price"),
                orchestrator=self,
                global_state=gs,
                financial_alert_active=financial_alert_active,
                orchestrated=True,   # constitutional gate
            )

    def _sh_version_rollback(self, payload: dict, product_id: str | None) -> None:
        vm  = self._services.get("version_manager")
        pid = payload.get("product_id") or product_id
        if vm and pid:
            vm.rollback_to_previous_baseline(pid, orchestrator=self, orchestrated=True)

    # ==================================================================
    # SERVICE HANDLERS — Commercial Flow (A10)
    # ==================================================================

    def _sh_payment_confirmed(self, payload: dict, product_id: str | None) -> None:
        ce = self._services.get("commercial_engine")
        if ce:
            ce.confirm_payment(
                user_id=payload.get("user_id", ""),
                product_id=payload.get("product_id") or product_id or "",
                payment_id=payload.get("payment_id", ""),
                source=payload.get("source", "system"),
            )

    def _sh_refund_requested(self, payload: dict, product_id: str | None) -> None:
        ce = self._services.get("commercial_engine")
        if ce:
            ce.request_refund(
                user_id=payload.get("user_id", ""),
                reason=payload.get("reason", ""),
                user_role=payload.get("user_role", "SYSTEM"),
            )

    def _sh_refund_completed(self, payload: dict, product_id: str | None) -> None:
        # 1. Commercial Engine (Revoke Access)
        ce = self._services.get("commercial_engine")
        if ce:
            ce.complete_refund(
                user_id=payload.get("user_id", ""),
            )
        
        # 2. Telemetry Engine (Record Economic Impact)
        tm = self._services.get("telemetry")
        pid = payload.get("product_id") or product_id
        amt = float(payload.get("amount", 0))
        if tm and pid:
            tm.record_refund(pid, amt)

        # 3. Feedback Engine (Revoke B3 Incentives)
        fie = self._services.get("feedback_incentive_engine")
        uid = payload.get("user_id", "")
        if fie and pid and uid:
            fie.revoke_lifetime_upgrade(
                user_id=uid,
                product_id=pid,
                reason="refund_completed",
            )

    def _sh_purchase_success(self, payload: dict, product_id: str | None) -> None:
        """
        Routes purchase_success to both Commercial and Telemetry engines.
        Ensures revenue is recorded and user license is issued.
        """
        # 1. Telemetry Engine
        tm  = self._services.get("telemetry")
        pid = payload.get("product_id") or product_id
        amt = float(payload.get("amount_total", 0))
        if tm and pid:
            tm.record_revenue(pid, amt)
            
        # 2. Commercial Engine
        ce = self._services.get("commercial_engine")
        if ce:
            # We use customer_email as user_id if not present
            uid = payload.get("user_id") or payload.get("customer_email", "")
            ce.confirm_payment(
                user_id=uid,
                product_id=pid or "",
                payment_id=payload.get("stripe_session_id", ""),
                source="system"
            )

    def _sh_login_requested(self, payload: dict, product_id: str | None) -> None:
        ce = self._services.get("commercial_engine")
        if ce:
            ce.validate_login(
                token=payload.get("token", ""),
            )

    # ==================================================================
    # SERVICE HANDLERS — Uptime Engine (A11)
    # ==================================================================

    def _sh_product_created(self, payload: dict, product_id: str | None) -> None:
        ue  = self._services.get("uptime_engine")
        pid = payload.get("product_id") or product_id
        if ue and pid:
            ue.register_product(pid, orchestrator=self)

    def _sh_product_resume(self, payload: dict, product_id: str | None) -> None:
        ue  = self._services.get("uptime_engine")
        pid = payload.get("product_id") or product_id
        if ue and pid:
            ue.resume_product(pid, orchestrator=self)

    def _sh_product_pause(self, payload: dict, product_id: str | None) -> None:
        ue  = self._services.get("uptime_engine")
        pid = payload.get("product_id") or product_id
        if ue and pid:
            ue.pause_product(pid, orchestrator=self)

    # ==================================================================
    # SERVICE HANDLERS — Strategic Memory (A12)
    # ==================================================================

    def _sh_monthly_consolidation(self, payload: dict, product_id: str | None) -> None:
        sme = self._services.get("strategic_memory_engine")
        pid = payload.get("product_id") or product_id
        mid = payload.get("month_id", "")
        if sme and pid and mid:
            sme.consolidate_month(
                product_id=pid,
                month_id=mid,
                baseline_version=payload.get("baseline_version", ""),
                baseline_price=float(payload.get("baseline_price", 0)),
                rpm_final=float(payload.get("rpm_final", 0)),
                roas_final=float(payload.get("roas_final", 0)),
                cac_final=float(payload.get("cac_final", 0)),
                margin_final=float(payload.get("margin_final", 0)),
                total_active_seconds=int(payload.get("total_active_seconds", 0)),
                total_revenue=float(payload.get("total_revenue", 0)),
                total_ad_spend=float(payload.get("total_ad_spend", 0)),
                snapshot_reference=payload.get("snapshot_reference", ""),
                event_bus=self._bus,
            )

    # ==================================================================
    # SERVICE HANDLERS — Feedback Incentivado (B3 / Bloco 27)
    # ==================================================================

    def _sh_feedback_evaluate(self, payload: dict, product_id: str | None) -> None:
        """Handle engagement evaluation. Calls evaluate_engagement on FeedbackIncentiveEngine."""
        fie = self._services.get("feedback_incentive_engine")
        pid = payload.get("product_id") or product_id
        uid = payload.get("user_id", "")
        if fie and pid and uid:
            from core.feedback_incentive_engine import FeedbackProductConfig, FeedbackConfigurationError
            try:
                cfg = FeedbackProductConfig(
                    product_id=pid,
                    engagement_metric_type=payload.get("engagement_metric_type", "custom"),
                    engagement_metric_total=float(payload.get("engagement_metric_total", 1)),
                    engagement_threshold=float(payload.get("engagement_threshold", 0.30)),
                )
                fie.evaluate_engagement(
                    config=cfg,
                    user_id=uid,
                    engagement_value=float(payload.get("engagement_value", 0)),
                    tempo_real=float(payload.get("tempo_real", 0)),
                    event_bus=self._bus,
                )
            except FeedbackConfigurationError as e:
                try:
                    self._bus._enter_orchestrated_context()
                    self._bus.append_event({
                        "event_type": "feedback_configuration_error",
                        "product_id": pid,
                        "payload": {"error": str(e)},
                        "source": "system",
                    })
                finally:
                    self._bus._exit_orchestrated_context()

    def _sh_feedback_submit(self, payload: dict, product_id: str | None) -> None:
        """Handle feedback text submission."""
        fie = self._services.get("feedback_incentive_engine")
        pid = payload.get("product_id") or product_id
        uid = payload.get("user_id", "")
        if fie and pid and uid:
            result = fie.submit_feedback(
                user_id=uid,
                product_id=pid,
                feedback_text=payload.get("feedback_text", ""),
                event_bus=self._bus,
            )
            # After validated, auto-grant lifetime upgrade
            if result.get("valid"):
                fie.grant_lifetime_upgrade(
                    user_id=uid,
                    product_id=pid,
                    metadata={"source": "feedback_validated"},
                    event_bus=self._bus,
                )

    def _sh_feedback_revoke_on_refund(self, payload: dict, product_id: str | None) -> None:
        """Legacy placeholder — logic consolidated into _sh_refund_completed."""
        pass

    # ==================================================================
    # SERVICE HANDLERS — User Enrichment (B4 / Bloco 28)
    # ==================================================================

    def _sh_user_enrichment_update(self, payload: dict, product_id: str | None) -> None:
        """Consolidate user intelligence snapshot."""
        uee = self._services.get("user_enrichment_engine")
        uid = payload.get("user_id", "")
        if uee and uid:
            uee.update_user_profile(
                user_id=uid,
                payment_amounts=[float(x) for x in payload.get("payment_amounts", [])],
                refund_amounts=[float(x) for x in payload.get("refund_amounts", [])],
                total_refunds=int(payload.get("total_refunds", 0)),
                channel_counts=dict(payload.get("channel_counts", {})),
                device_counts=dict(payload.get("device_counts", {})),
                last_purchase_ts=payload.get("last_purchase_ts"),
                avg_ltv_product=float(payload.get("avg_ltv_product", 0)),
                event_bus=self._bus,
            )

    # ==================================================================
    # SERVICE HANDLERS — Macro Exposure Governance (Bloco 29)
    # ==================================================================

    def _sh_macro_exposure_validate(self, payload: dict, product_id: str | None) -> None:
        """Validate requested allocation against macro exposure limits."""
        mege = self._services.get("macro_exposure_governance_engine")
        pid  = payload.get("product_id") or product_id
        if mege and pid:
            mege.validate_macro_exposure(
                product_id=pid,
                channel_id=payload.get("channel_id", ""),
                requested_allocation=float(payload.get("requested_allocation", 0)),
                current_product_allocation=float(payload.get("current_product_allocation", 0)),
                current_channel_allocation=float(payload.get("current_channel_allocation", 0)),
                current_global_allocation=float(payload.get("current_global_allocation", 0)),
                total_capital=float(payload.get("total_capital", 1)),
                roas_avg=float(payload.get("roas_avg", 0)),
                score_global=float(payload.get("score_global", 0)),
                refund_ratio_avg=float(payload.get("refund_ratio_avg", 0)),
                global_state=payload.get("global_state", "NORMAL"),
                financial_alert_active=bool(payload.get("financial_alert_active", False)),
                event_bus=self._bus,
            )

    def _sh_opportunity_evaluate(self, payload: dict, product_id: str | None) -> None:
        soe = self._services.get("strategic_opportunity_engine")
        pid = payload.get("product_id") or product_id
        if soe and pid:
            soe.evaluate_opportunity(
                product_id=pid,
                emotional_score=float(payload.get("emotional_score", 0)),
                monetization_score=float(payload.get("monetization_score", 0)),
                products_in_cluster=int(payload.get("products_in_cluster", 0)),
                total_active_products=int(payload.get("total_active_products", 1)),
                score_global=float(payload.get("score_global", 0)),
                roas_avg=float(payload.get("roas_avg", 0)),
                global_state=payload.get("global_state", "NORMAL"),
                active_betas=int(payload.get("active_betas", 0)),
                macro_block=bool(payload.get("macro_block", False)),
                positive_trend=bool(payload.get("positive_trend", False)),
                event_bus=self._bus,
            )

    # ==================================================================
    # SERVICE HANDLER — Landing Engine (Bloco 30)
    # ==================================================================

    def _sh_landing_recommendation(self, payload: dict, product_id: str | None) -> None:
        """
        Entry point for expansion_recommendation_event — delegated to Bloco 30.

        Delegates to:
            infra/landing/landing_recommendation_handler.handle()

        Constitutional guarantees (enforced by infra/landing/):
          - Nunca instancia ProductLifeEngine diretamente
          - Nunca chama StateMachine.transition()
          - Nunca altera state.json
          - Nunca chama GuardianEngine
          - Usa receive_event(), nunca emit_event() para eventos governados
          - Contenção financeira respeitada (Orchestrator bloqueia automaticamente)
        """
        try:
            from infra.landing import landing_recommendation_handler
            landing_recommendation_handler.handle(
                orchestrator = self,
                payload      = payload,
                product_id   = product_id,
            )
        except Exception as exc:
            logger.error(
                "[Bloco30] _sh_landing_recommendation failed for cluster_id=%s: %s",
                payload.get("cluster_id", "?"),
                exc,
            )

    # ==================================================================
    # SERVICE HANDLERS — Maintenance System (P9.4)
    # ==================================================================

    def _sh_dashboard_maintenance_requested(self, payload: dict, product_id: str | None) -> None:
        """
        Triggered when Dashboard 'Maintenance' button is clicked.
        Emits system-level diagnostic info for Anti-Gravity contextualization.
        Does NOT alter state.
        """
        maintenance_type = payload.get("maintenance_type", "system")
        if maintenance_type == "product":
            pid = payload.get("product_id") or product_id
            product_state = self._state.get("products", {}).get(pid, {})
            # Emitting the contextualizing event for Anti-Gravity
            # using emit() so it hits the internal pub/sub or logs
            self.persist_event({
                "event_type": "product_maintenance_context_ready",
                "product_id": pid,
                "payload": {
                    "context_type": "product_maintenance",
                    "product_id": pid,
                    "landing_url": payload.get("landing_url"),
                    "system_state_snapshot": {
                        "lifecycle_state": product_state.get("lifecycle_state"),
                        "generated_copy": product_state.get("generated_copy"),
                        "price": product_state.get("pricing", {}).get("current_price")
                    }
                }
            })
            logger.info(f"[Maintenance] Prepared read-only context wrapper for Product: {pid}")

        elif maintenance_type == "system":
            self.persist_event({
                "event_type": "system_maintenance_context_ready",
                "payload": {
                    "context_type": "system_maintenance",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            })
            logger.info("[Maintenance] Prepared read-only system-level context wrapper.")


    def _sh_human_patch_event(self, orchestrator, state: dict, payload: dict) -> None:
        """
        Executes the formal human patch mutation.
        Strictly applies the patch over the specified targets to avoid lifecycle interruption.
        """
        pid = payload.get("product_id")
        patch_type = payload.get("patch_type")
        target = payload.get("target")
        context = payload.get("context", "")

        products = state.get("products", {})
        if pid not in products:
            logger.warning(f"human_patch_event: product {pid} not found")
            return

        prod = products[pid]
        
        # A human patch simulates version sub-incrementing instead of full phase changes.
        current_version = prod.get("version", "1.0")
        if "." in current_version:
            v_major, v_minor = current_version.split(".", 1)
            new_version = f"{v_major}.{int(v_minor)+1}"
        else:
            new_version = f"{current_version}.1"
            
        prod["version"] = new_version
        
        # We record the intervention in an explicit patch history without disrupting state fields mapping active execution.
        if "patch_history" not in prod:
            prod["patch_history"] = []
            
        prod["patch_history"].append({
            "patch_type": patch_type,
            "target": target,
            "context": context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "origin": "human"
        })
        
        logger.info(f"Applied HUMAN PATCH to {pid} -> {new_version} ({patch_type})")

    def _sh_rss_signal_collection_requested(self, payload: dict, product_id: str | None) -> None:
        """
        P10.3 Handler: Requests RSS Engine collection cycle.
        Executes without mutating system state.
        """
        rss_engine = self._services.get("rss_signal_engine")
        if rss_engine:
            rss_engine.run_collection_cycle()
        else:
            logger.error("RSSSignalEngine not mapped in Orchestrator services.")

        
    # ── Radar Configuration (P11.2) ──────────────────────────────────
    _RADAR_KEYWORDS = [
        ("produtividade",     "saas"),
        ("educação online",   "course"),
        ("finanças pessoais", "saas"),
        ("saúde mental",      "info_product"),
        ("automação",         "saas"),
        ("marketing digital", "info_product"),
        ("e-commerce",        "e_commerce"),
        ("idiomas",           "course"),
    ]

    def _next_radar_keyword(self) -> tuple:
        """Rotates through predefined radar keywords."""
        with self._lock:
            # We persist index in state to survive reboots (Constitutional)
            idx = self._state.get("radar_keyword_index", 0)
            pair = self._RADAR_KEYWORDS[idx % len(self._RADAR_KEYWORDS)]
            
            # Atomic update
            with self._write_context():
                self._state.set("radar_keyword_index", idx + 1)
                
            return pair

    def _sh_radar_scan_requested(self, payload: dict, product_id: str | None) -> None:
        """
        Official entry point for Human-Started Radar scans (Etapa 15 Alignment).
        Enforces constitutional gates before delegating to RadarEngine.
        """
        logger.info("[Orchestrator] Human start event detected. Validating Radar execution...")

        # 1. Governance data extraction
        gs_svc    = self._services.get("global_state")
        fe_svc    = self._services.get("finance")
        macro_v   = self._services.get("macro_exposure_governance_engine")
        
        g_state       = gs_svc.get_state() if gs_svc else "NORMAL"
        fin_alert_gs  = (g_state == CONTENCAO_FINANCEIRA)
        
        # Calculate active betas from product lifecycle state
        from infrastructure.product_lifecycle_persistence import ProductLifecyclePersistence
        pl_pers = ProductLifecyclePersistence("product_lifecycle_state.json")
        try:
            pl_data = pl_pers.load()
            active_betas_count = len([p for p in pl_data.values() if p.get("state") in ["BETA", "VALIDATION"]])
        except Exception:
            active_betas_count = 0

        # Macro governance check
        macro_blocked = False
        if macro_v:
             # Basic check — generic radar check
             res_m = macro_v.validate_macro_exposure(
                 product_id="RADAR_SCAN",
                 channel_id="scan",
                 requested_allocation=0,
                 current_product_allocation=0,
                 current_channel_allocation=0,
                 current_global_allocation=0,
                 total_capital=1000000,
                 roas_avg=2.0,
                 score_global=self._state.get("last_score", 0),
                 refund_ratio_avg=0,
                 global_state=g_state,
                 financial_alert_active=fin_alert_gs
             )
             macro_blocked = not res_m.get("allowed", False)

        gov_context = {
            "global_state":           g_state,
            "financial_alert_active": fin_alert_gs,
            "max_active_betas":       active_betas_count,
            "macro_exposure_blocked": macro_blocked,
        }

        # 2. Constitutional Pre-flight (Phase 0)
        from radar.radar_engine import RadarEngine, validate_radar_execution
        precheck = validate_radar_execution(gov_context, orchestrator=self)
        
        if not precheck.get("allowed"):
            logger.warning(f"[Orchestrator] Radar execution BLOCKED: {precheck.get('reason')}")
            # Event is emitted inside validate_radar_execution
            return

        # 3. Execution (Post-Governance approval)
        keyword, category = self._next_radar_keyword()
        logger.info(f"[Orchestrator] Governance APPROVED. Starting Radar cycle: '{keyword}' ({category})")
        
        try:
            from core.strategic_opportunity_engine import StrategicOpportunityEngine
            from infrastructure.opportunity_radar_persistence import OpportunityRadarPersistence
            from infra.bootstrap.bootstrap_mode import get_bootstrap_overrides
            
            eval_payload_overrides = get_bootstrap_overrides()
            
            radar_pers       = OpportunityRadarPersistence("radar_evaluations.json")
            strategic_engine = StrategicOpportunityEngine(
                orchestrator=self,
                persistence=radar_pers,
            )
            radar = RadarEngine(
                orchestrator=self,
                strategic_engine=strategic_engine,
            )
            
            # Dispatch cycle
            result = radar.run_cycle(
                keyword=keyword,
                category=category,
                eval_payload_overrides=eval_payload_overrides,
                governance_context=gov_context,
            )
            
            status = result.get("status", "complete")
            logger.info(f"[Orchestrator] Radar cycle finished. status={status}")
            
        except Exception as exc:
            logger.error(f"[Orchestrator] Fatal error during Radar cycle: {exc}", exc_info=True)
            self.emit_event("radar_execution_failed", {"error": str(exc)})

    _SVC_HANDLERS: dict = {
        # Telemetry (A3)
        "visit_recorded":                    _sh_visit_recorded,
        "revenue_recorded":                  _sh_revenue_recorded,
        "ad_spend_recorded":                 _sh_ad_spend_recorded,
        "refund_recorded":                   _sh_refund_recorded,
        "cycle_open_requested":              _sh_cycle_open_requested,
        "cycle_close_requested":             _sh_cycle_close_requested,
        # Finance (A4)
        "stripe_balance_updated":            _sh_stripe_balance_updated,
        "stripe_revenue_recorded":           _sh_stripe_revenue_recorded,
        "stripe_refund_recorded":            _sh_stripe_refund_recorded,
        "openai_balance_updated":            _sh_openai_balance_updated,
        "ad_spend_registered":               _sh_ad_spend_registered,
        "financial_health_check_requested":  _sh_financial_health_check,
        "financial_projection_requested":    _sh_financial_projection_requested,
        
        # Acquisition Events
        "ads_cost_reported":                 _sh_ads_cost_reported,
        "ads_budget_limit_reached":          _sh_ads_budget_limit_reached,
        "ads_campaign_created":              _sh_ads_campaign_created,
        "campaign_performance_event":        _sh_campaign_performance_event,
        # Product Life (A5)
        "beta_start_requested":              _sh_beta_start_requested,
        "beta_close_requested":              _sh_beta_close_requested,
        "beta_expiration_check":             _sh_beta_expiration_check,
        "post_beta_consolidation_requested": _sh_post_beta_consolidation_requested,
        # Product Creation (A14)
        "product_creation_requested":        _sh_product_creation_requested,
        "beta_approved_requested":           _sh_beta_approved_requested,
        # Market Loop (A6)
        "market_cycle_start_requested":      _sh_market_cycle_start,
        "market_phase_execution_requested":  _sh_market_phase_execute,
        "market_phase_evaluation_requested": _sh_market_phase_evaluate,
        "market_cycle_close_requested":      _sh_market_cycle_close,
        # Pricing (A7)
        "pricing_offensive_requested":       _sh_pricing_offensive,
        "pricing_defensive_requested":       _sh_pricing_defensive,
        "pricing_evaluation_requested":      _sh_pricing_evaluation,
        "pricing_offensive_test_requested":  _sh_pricing_offensive_test,
        "pricing_defensive_test_requested":  _sh_pricing_defensive_test,
        "pricing_rollback_requested":       _sh_pricing_rollback,
        # Version Manager (A8)
        "candidate_version_requested":       _sh_version_candidate,
        "version_promotion_requested":       _sh_version_promote,
        "version_rollback_requested":        _sh_version_rollback,
        # Commercial (A10)
        "purchase_success":                  _sh_purchase_success,
        "payment_confirmed":                 _sh_payment_confirmed,
        "refund_requested":                  _sh_refund_requested,
        "refund_completed":                  _sh_refund_completed,
        "login_requested":                   _sh_login_requested,
        # Uptime Engine (A11)
        "product_created":                   _sh_product_created,
        "product_resume_requested":          _sh_product_resume,
        "product_pause_requested":           _sh_product_pause,
        # Strategic Memory (A12)
        "monthly_consolidation_requested":   _sh_monthly_consolidation,
        # Strategic Opportunity (Bloco 26)
        "opportunity_evaluation_requested":  _sh_opportunity_evaluate,
        # Feedback Incentivado (B3 / Bloco 27)
        "feedback_evaluation_requested":     _sh_feedback_evaluate,
        "feedback_submit_requested":         _sh_feedback_submit,
        # User Enrichment (B4 / Bloco 28)
        "user_enrichment_update_requested":      _sh_user_enrichment_update,
        # Macro Exposure Governance (Bloco 29)
        "macro_exposure_validation_requested":   _sh_macro_exposure_validate,
        # Landing Engine (Bloco 30) — structural entry point
        "expansion_recommendation_event":        _sh_landing_recommendation,
        # RSS Layer (Bloco 10)
        "rss_signal_collection_requested":       _sh_rss_signal_collection_requested,
        "radar_scan_requested":                  _sh_radar_scan_requested,
        "scheduler_radar_scan_tick":             _sh_radar_scan_requested,
    }

