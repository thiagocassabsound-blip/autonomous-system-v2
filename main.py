


import os
import sys
import time
import threading
from flask import Flask, jsonify

from api.app import create_app
from orchestrator import start_system, run_audit_phase8, run_audit_phase8_dynamic, run_audit_phase9_dashboard
from runtime_engine import runtime_engine

from infrastructure.logger import get_logger
from infrastructure.db import (
    FilePersistence, EventLogPersistence,
    SnapshotPersistence, JsonFilePersistence,
)
from infrastructure.finance_persistence import (
    FinanceStatePersistence, FinanceProjectionsPersistence, GlobalStatePersistence,
)
from infrastructure.product_lifecycle_persistence import ProductLifecyclePersistence
from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from core.scheduler import Scheduler
from core.state_machine import StateMachine
from core.snapshot_manager import SnapshotManager
from core.version_manager import VersionManager
from core.cycle_manager import CycleManager
from core.telemetry_engine import TelemetryEngine
from core.global_state import GlobalState
from core.finance_engine import FinanceEngine
from core.product_life_engine import ProductLifeEngine
from core.strategic_opportunity_engine import StrategicOpportunityEngine
from engines.cycle_engine import CycleEngine
from engines.beta_engine import BetaEngine
from engines.economic_engine import EconomicEngine
from core.security_layer import SecurityLayer
from core.feedback_incentive_engine import FeedbackIncentiveEngine

logger = get_logger("MainApp")

# Global pointers
core_thread = None
system_active = False

# Initialize base DB layers and Orchestrator globally so webhooks don't crash before boot
state_persistence    = FilePersistence("state.json")
event_log            = EventLogPersistence("events.json")
snapshot_persistence = SnapshotPersistence("snapshots.json")
sm_persistence       = JsonFilePersistence("state_machine.json")
vm_persistence       = JsonFilePersistence("versions.json")

event_bus     = EventBus(event_log)
state_manager = StateManager(state_persistence)
global_orchestrator  = Orchestrator(event_bus, state_manager)

def _run_core_system(orchestrator, mode="normal", interval=2.0):
    global system_active
    if system_active:
        return
    system_active = True
    
    logger.info(f">>> STARTING CORE SYSTEM [{mode.upper()} MODE] <<<")

    orchestrator.start()

    state_machine    = StateMachine(sm_persistence)
    snapshot_manager = SnapshotManager(orchestrator, snapshot_persistence)
    version_manager  = VersionManager(vm_persistence)

    cm_persistence     = JsonFilePersistence("cycles.json")
    telemetry_snaps    = EventLogPersistence("telemetry_snapshots.json")
    telemetry_accums   = JsonFilePersistence("telemetry_accumulators.json")
    cycle_manager      = CycleManager(cm_persistence)
    telemetry_engine   = TelemetryEngine(telemetry_snaps, telemetry_accums)

    orchestrator.register_service("cycle_manager", cycle_manager)
    orchestrator.register_service("telemetry",     telemetry_engine)

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

    sec_persistence     = EventLogPersistence("security_logs.json")
    security_layer      = SecurityLayer(orchestrator, sec_persistence)
    orchestrator.register_service("security", security_layer)

    fb_persistence      = EventLogPersistence("feedback_records.json")
    feedback_engine     = FeedbackIncentiveEngine(orchestrator, fb_persistence)
    orchestrator.register_service("feedback", feedback_engine)

    radar_persistence = EventLogPersistence("radar_evaluations.json")
    radar_engine_v2   = StrategicOpportunityEngine(
        orchestrator=orchestrator,
        persistence=radar_persistence,
    )
    orchestrator.register_service("strategic_radar", radar_engine_v2)

    cycle_engine    = CycleEngine(event_bus, orchestrator)
    beta_engine     = BetaEngine(event_bus, orchestrator)
    economic_engine = EconomicEngine(event_bus, orchestrator)

    scheduler = Scheduler(event_bus, interval=interval)
    scheduler.start()
    logger.info("System Engine online internally via API.")
    
    try:
        while system_active:
            time.sleep(1)
    except KeyboardInterrupt:
        scheduler.stop()

# We supply the global orchestrator to Flask on start
app = create_app(orchestrator=global_orchestrator)

@app.route('/boot', methods=['GET', 'POST'])
def api_boot():
    """/boot -> inicia o sistema e as pipelines de orquestração"""
    global core_thread
    pipe_results = start_system() # Runs the system simulation scripts requested
    
    if not system_active:
        core_thread = threading.Thread(target=_run_core_system, args=(global_orchestrator,), daemon=True)
        core_thread.start()
        
    return jsonify({
        "status": "BOOTED", 
        "pipeline_results": pipe_results,
        "engine_active": system_active
    })

@app.route('/run-audit', methods=['GET', 'POST'])
def api_run_audit():
    """/run-audit -> executa auditoria"""
    results = {
        "audit_phase8": run_audit_phase8(),
        "audit_phase8_dynamic": run_audit_phase8_dynamic(),
        "audit_phase9_dashboard": run_audit_phase9_dashboard()
    }
    return jsonify({"status": "AUDIT_COMPLETED", "details": results})

@app.route('/logs', methods=['GET'])
def api_logs():
    """/logs -> retorna logs recentes"""
    logs_data = []
    log_file = "logs/runtime_events.log"
    if os.path.exists(log_file):
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            # Return last 50 lines
            logs_data = [line.strip() for line in lines[-50:]]
            
    return jsonify({
        "status": "OK",
        "recent_logs": logs_data,
        "log_path": log_file
    })

@app.route('/runtime-status', methods=['GET'])
def api_runtime_status():
    """/runtime-status -> Returns the continuous engine telemetry loop state."""
    return jsonify(runtime_engine.get_status)

@app.route('/start-runtime', methods=['GET', 'POST'])
def api_start_runtime():
    """/start-runtime -> starts the autonomous loop."""
    interval = request.args.get("interval", 60, type=int) if 'request' in globals() else 60
    # To use request.args nicely, let's actually import request from flask
    from flask import request
    interval = request.args.get("interval", 60, type=int)
    runtime_engine.set_interval(interval)
    started = runtime_engine.start()
    return jsonify({
        "status": "STARTED" if started else "ALREADY_ACTIVE",
        "interval_seconds": interval,
        "is_active": runtime_engine.is_active
    })

@app.route('/stop-runtime', methods=['GET', 'POST'])
def api_stop_runtime():
    """/stop-runtime -> safely stops the runtime loop."""
    stopped = runtime_engine.stop()
    return jsonify({
        "status": "STOP_SIGNAL_SENT" if stopped else "ALREADY_INACTIVE",
        "is_active": runtime_engine.is_active
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
