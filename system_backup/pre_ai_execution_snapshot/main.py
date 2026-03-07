"""
autonomous-system-v2 — Foundation Core Lock
All state writes go through Orchestrator.receive_event().
Flags: --fast (0.2s interval) | --stress (0.01s, auto-stop at 100 cycles)
"""
import sys
import time
from infrastructure.logger       import get_logger
from infrastructure.db           import (
    FilePersistence, EventLogPersistence,
    SnapshotPersistence, JsonFilePersistence,
)
from infrastructure.finance_persistence import (
    FinanceStatePersistence, FinanceProjectionsPersistence, GlobalStatePersistence,
)
from infrastructure.product_lifecycle_persistence import ProductLifecyclePersistence
from core.event_bus              import EventBus
from core.state_manager          import StateManager
from core.orchestrator           import Orchestrator
from core.scheduler              import Scheduler
from core.state_machine          import StateMachine
from core.snapshot_manager       import SnapshotManager
from core.version_manager        import VersionManager
from core.cycle_manager          import CycleManager
from core.telemetry_engine       import TelemetryEngine
from core.global_state           import GlobalState
from core.finance_engine         import FinanceEngine
from core.product_life_engine    import ProductLifeEngine
from core.strategic_opportunity_engine import StrategicOpportunityEngine
from engines.cycle_engine        import CycleEngine
from engines.beta_engine         import BetaEngine
from engines.economic_engine     import EconomicEngine
from core.security_layer         import SecurityLayer
from core.feedback_incentive_engine import FeedbackIncentiveEngine




logger = get_logger("Main")

STRESS_TARGET = 100


def _detect_mode():
    args = sys.argv
    if "--stress" in args:
        return "stress", 0.01
    if "--fast" in args:
        return "fast", 0.2
    return "normal", 2.0


def _print_stress_summary(orchestrator: Orchestrator) -> None:
    state   = orchestrator.state
    metrics = state.get("metrics", {})
    history = state.get("cycle_history", [])
    active  = state.get("active_cycles", {})
    ids     = [c.get("cycle_id") for c in history if isinstance(c, dict)]
    dupes   = len(ids) != len(set(ids))

    print("\n" + "=" * 54)
    print("  STRESS TEST SUMMARY")
    print("=" * 54)
    print(f"  total_cycles_completed : {metrics.get('total_cycles', 0)}")
    print(f"  total_opportunities    : {metrics.get('total_opportunities', 0)}")
    print(f"  avg_score              : {metrics.get('avg_score', 0)}")
    print(f"  beta_success_rate      : {metrics.get('beta_success_rate', 0)}%")
    print(f"  cycle_history entries  : {len(history)}")
    print(f"  still active_cycles    : {len(active)}")
    print(f"  duplicate cycle_ids    : {'YES ⚠️' if dupes else 'NO ✅'}")
    print(f"  integrity              : {'FAIL ❌' if dupes else 'OK ✅'}")
    print("=" * 54 + "\n")


def main() -> None:
    mode, interval = _detect_mode()
    logger.info(f">>> AUTONOMOUS SYSTEM V2 — STARTING [{mode.upper()} MODE] <<<")

    # ------------------------------------------------------------------
    # 1. Infrastructure — persistence backends
    # ------------------------------------------------------------------
    state_persistence    = FilePersistence("state.json")
    event_log            = EventLogPersistence("events.json")
    snapshot_persistence = SnapshotPersistence("snapshots.json")
    sm_persistence       = JsonFilePersistence("state_machine.json")
    vm_persistence       = JsonFilePersistence("versions.json")

    # ------------------------------------------------------------------
    # 2. Core — event bus + state + orchestrator
    # ------------------------------------------------------------------
    event_bus     = EventBus(event_log)
    state_manager = StateManager(state_persistence)    # locked after init
    orchestrator  = Orchestrator(event_bus, state_manager)
    orchestrator.start()

    # ------------------------------------------------------------------
    # 3. Governance services
    # ------------------------------------------------------------------
    state_machine    = StateMachine(sm_persistence)
    snapshot_manager = SnapshotManager(orchestrator, snapshot_persistence)
    version_manager  = VersionManager(vm_persistence)

    # Telemetry A3
    cm_persistence     = JsonFilePersistence("cycles.json")
    telemetry_snaps    = EventLogPersistence("telemetry_snapshots.json")
    telemetry_accums   = JsonFilePersistence("telemetry_accumulators.json")
    cycle_manager      = CycleManager(cm_persistence)
    telemetry_engine   = TelemetryEngine(telemetry_snaps, telemetry_accums)

    orchestrator.register_service("cycle_manager", cycle_manager)
    orchestrator.register_service("telemetry",     telemetry_engine)

    # Finance A4
    gs_persistence      = GlobalStatePersistence("global_state.json")
    fin_state_pers      = FinanceStatePersistence("finance_state.json")
    fin_proj_pers       = FinanceProjectionsPersistence("financial_projections.json")
    global_state        = GlobalState(orchestrator, gs_persistence)
    finance_engine      = FinanceEngine(
        state_persistence=fin_state_pers,
        projection_persistence=fin_proj_pers,
        global_state=global_state,
        min_buffer_days=14,
        auto_recharge_enabled=False,
        moving_avg_days=7,
    )

    orchestrator.register_service("global_state", global_state)
    orchestrator.register_service("finance",      finance_engine)

    # Security A9
    sec_persistence     = EventLogPersistence("security_logs.json")
    security_layer      = SecurityLayer(orchestrator, sec_persistence)
    orchestrator.register_service("security", security_layer)

    # Feedback B3
    fb_persistence      = EventLogPersistence("feedback_records.json")
    feedback_engine     = FeedbackIncentiveEngine(orchestrator, fb_persistence)
    orchestrator.register_service("feedback", feedback_engine)


    # ------------------------------------------------------------------
    # 4. Engines — all receive orchestrator, not state_manager directly
    # ------------------------------------------------------------------
    # Bloco 26 V2 — Strategic Opportunity Engine (constitutional authority)
    radar_persistence = EventLogPersistence("radar_evaluations.json")
    radar_engine_v2   = StrategicOpportunityEngine(
        orchestrator=orchestrator,
        persistence=radar_persistence,
    )
    orchestrator.register_service("strategic_radar", radar_engine_v2)

    cycle_engine    = CycleEngine(event_bus, orchestrator)
    beta_engine     = BetaEngine(event_bus, orchestrator)
    economic_engine = EconomicEngine(event_bus, orchestrator)

    # ------------------------------------------------------------------
    # 5. Scheduler
    # ------------------------------------------------------------------
    scheduler = Scheduler(event_bus, interval=interval)
    logger.info(f"Scheduler interval={interval}s.")

    # ------------------------------------------------------------------
    # 6. Run loop
    # ------------------------------------------------------------------
    scheduler.start()
    logger.info("System online. Press CTRL+C to stop.")

    try:
        while True:
            time.sleep(0.05)

            if mode == "stress":
                history = state_manager.get("cycle_history", [])
                if len(history) >= STRESS_TARGET:
                    logger.info(
                        f"STRESS TARGET REACHED: {STRESS_TARGET} cycles completed."
                    )
                    scheduler.stop()
                    _print_stress_summary(orchestrator)
                    sys.exit(0)

    except KeyboardInterrupt:
        logger.info(">>> SHUTDOWN REQUESTED <<<")
        scheduler.stop()
        logger.info(">>> SYSTEM STOPPED. GOODBYE. <<<")
        sys.exit(0)


if __name__ == "__main__":
    main()
