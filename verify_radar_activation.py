"""
verify_radar_activation.py — FastoolHub V2 Activation Audit Script

Manual trigger for Radar cycle with SyntheticAuditProvider.
"""

import os
import sys
import logging

# Add current directory to path
sys.path.append(os.getcwd())

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from core.strategic_opportunity_engine import StrategicOpportunityEngine
from radar.radar_engine import RadarEngine
from radar import input_layer
from infrastructure.db import JsonFilePersistence, EventLogPersistence
from infrastructure.opportunity_radar_persistence import OpportunityRadarPersistence
from infrastructure.logger import get_logger

# Configure logging
root_logger = logging.getLogger()
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter('[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s')
handler.setFormatter(formatter)
root_logger.addHandler(handler)
root_logger.setLevel(logging.INFO)

logger = get_logger("RadarAudit")

def run_audit():
    logger.info(">>> STARTING RADAR ACTIVATION AUDIT <<<")
    
    # Use absolute paths for audit files
    root = os.getcwd()
    ledger_path = os.path.join(root, "audit_ledger.jsonl")
    state_path = os.path.join(root, "audit_state.json")
    radar_path = os.path.join(root, "audit_radar_evaluations.json")
    
    # 1. Infrastructure Setup
    ledger_pers = EventLogPersistence(ledger_path)
    bus = EventBus(ledger_pers)
    state_pers = JsonFilePersistence(state_path)
    state_manager = StateManager(state_pers)
    
    # 2. Initialize Orchestrator
    orchestrator = Orchestrator(bus, state_manager)
    logger.info("Orchestrator initialized with audit persistence.")
    
    # 3. Register StrategicOpportunityEngine (Authority)
    # SOE requires OpportunityRadarPersistence (JSON-Lines)
    radar_pers = OpportunityRadarPersistence(radar_path)
    strategic_engine = StrategicOpportunityEngine(orchestrator=orchestrator, persistence=radar_pers)
    orchestrator.register_service("strategic_radar", strategic_engine)
    logger.info("StrategicOpportunityEngine registered.")
    
    # 4. Initialize RadarEngine
    radar = RadarEngine(orchestrator, strategic_engine)
    logger.info("RadarEngine initialized")
    
    # 5. Parameters
    keyword = "meeting scheduling friction"
    category = "saas"
    
    # 6. Run Cycle
    gov_context = {
        "global_state": "NORMAL",
        "financial_alert_active": False,
        "max_active_betas": 0,
        "macro_exposure_blocked": False
    }
    
    logger.info(f"Executing Radar cycle for keyword='{keyword}'...")
    # NOTE: run_cycle handles create_query_spec internally
    result = radar.run_cycle(
        keyword=keyword,
        category=category,
        governance_context=gov_context,
        tags=["audit", "block-2"]
    )
    
    # 7. Audit Results
    logger.info(">>> AUDIT RESULTS <<<")
    if result.get("success"):
        eval_data = result.get("evaluation", {})
        logger.info(f"SUCCESS: Radar cycle completed.")
        logger.info(f"Snapshot ID: {result.get('snapshot_id')}")
        logger.info(f"Final Score: {eval_data.get('score_final')}")
        logger.info(f"ICE Status: {eval_data.get('ice')}")
        logger.info(f"Recommended: {eval_data.get('recommended')}")
    else:
        logger.error(f"FAILED: Radar cycle status: {result.get('status')} reason: {result.get('reason')}")

if __name__ == "__main__":
    run_audit()
