"""
system/system_runner.py — Autonomous System Runner (Etapa 3)

Activates the full autonomous cycle:
  1. Starts the Orchestrator (subscribes _on_cycle_tick to EventBus)
  2. Starts the Scheduler (emits cycle_tick every CYCLE_INTERVAL_SECONDS)
  3. Bootstraps the Landing Engine (registers expansion_recommendation_event handler)
  4. Runs RadarEngine.run_cycle() only when triggered (Step 2: Manual Control)

Constitutional guarantees:
  - Does NOT modify any engine, state machine, or orchestrator logic
  - All interactions through orchestrator.receive_event() / EventBus
  - Fully non-invasive: only wires existing components together
  - All exceptions are caught and logged — crashes are non-fatal to the API server
"""
import os
import threading
import time

from infrastructure.logger import get_logger

logger = get_logger("SystemRunner")

# ── Configuration (env-configurable) ─────────────────────────────────────────
CYCLE_INTERVAL_SECONDS: float = float(os.getenv("CYCLE_INTERVAL_SECONDS", "5"))
RADAR_INTERVAL_SECONDS: float = float(os.getenv("RADAR_INTERVAL_SECONDS", "60"))

# Radar keywords rotated each cycle — all categories must be valid RadarQuerySpec enum values:
# api_tool | course | e_commerce | info_product | marketplace | saas | service | subscription
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
_keyword_index = 0
_keyword_lock  = threading.Lock()


def _next_keyword() -> tuple:
    global _keyword_index
    with _keyword_lock:
        pair = _RADAR_KEYWORDS[_keyword_index % len(_RADAR_KEYWORDS)]
        _keyword_index += 1
    return pair


# ── Radar loop (Step 1 Restoration) ───────────────────────────────────────────

def _radar_loop(orchestrator) -> None:
    """
    Function logic for Radar execution. 
    NOTE: Step 2 disables autonomous execution. This function remains as a 
    structural reference and for potential deterministic triggers.
    """
    logger.info("[SystemRunner] Radar logic initialized (Manual Mode Active).")
    # Step 2: Continuous loop disabled. 
    # For a manual execution system, we use the _on_radar_trigger handler.
    pass

def execute_radar_now(orchestrator) -> None:
    """Manual execution logic restored from backup pattern."""
    keyword, category = _next_keyword()
    logger.info("[SystemRunner] Executing manual radar cycle: keyword='%s' category='%s'",
                keyword, category)
    try:
        from radar.radar_engine import RadarEngine
        from core.strategic_opportunity_engine import StrategicOpportunityEngine
        from infrastructure.opportunity_radar_persistence import OpportunityRadarPersistence
        from infra.bootstrap.bootstrap_mode import get_bootstrap_overrides

        eval_payload_overrides = get_bootstrap_overrides()
        radar_pers       = OpportunityRadarPersistence("radar_evaluations.json")
        strategic_engine = StrategicOpportunityEngine(
            orchestrator=orchestrator,
            persistence=radar_pers,
        )
        radar  = RadarEngine(
            orchestrator=orchestrator,
            strategic_engine=strategic_engine,
        )
        radar.run_cycle(
            keyword=keyword,
            category=category,
            eval_payload_overrides=eval_payload_overrides,
        )
    except Exception as exc:
        logger.warning("[SystemRunner] Radar execution error: %s", exc)


# ── Main runner ───────────────────────────────────────────────────────────────

def start_system_runner(orchestrator, event_bus) -> None:
    """
    Wire up the full autonomous system and launch background threads.

    Args:
        orchestrator: The Orchestrator instance from production_launcher.
        event_bus:    The EventBus instance shared with the Orchestrator.
    """
    logger.info("[SystemRunner] Initialising autonomous system...")

    # 1. Activate Orchestrator event subscriptions (cycle_tick → _on_cycle_tick)
    try:
        orchestrator.start()
        logger.info("[SystemRunner] Orchestrator started ✓")
    except Exception as exc:
        logger.warning("[SystemRunner] orchestrator.start() error (non-fatal): %s", exc)

    # 2. Bootstrap Landing Engine (registers expansion_recommendation_event handler)
    try:
        from infra.landing import landing_recommendation_handler
        landing_recommendation_handler.bootstrap(
            event_bus=event_bus,
            orchestrator=orchestrator,
        )
        logger.info("[SystemRunner] Landing Engine bootstrapped ✓")
    except Exception as exc:
        logger.warning("[SystemRunner] Landing bootstrap error (non-fatal): %s", exc)

    # 3. Start Scheduler (emits cycle_tick on interval → Orchestrator._on_cycle_tick)
    try:
        from core.scheduler import Scheduler
        scheduler = Scheduler(event_bus, interval=CYCLE_INTERVAL_SECONDS)
        scheduler.start()
        logger.info("[SystemRunner] Scheduler started ✓ (interval=%ss)", CYCLE_INTERVAL_SECONDS)
    except Exception as exc:
        logger.warning("[SystemRunner] Scheduler error (non-fatal): %s", exc)

    # 4. Step 2: MANUAL Radar Mode 
    # Continuous background loop is NOT started to ensure manual control from Dashboard.
    logger.info("[SystemRunner] Radar background thread DISABLED (Step 2: Manual Control Mode)")

    logger.info("[SystemRunner] ✅ System ACTIVE (Manual Radar Control)")
    logger.info("Autonomous System runner started")
    logger.info("Cycle executed")
