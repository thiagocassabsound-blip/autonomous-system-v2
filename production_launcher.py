"""
autonomous-system-v2/production_launcher.py

Unified Production Entrypoint.
Bootstraps the V2 Core and starts the API Server (Flask).
Authoritative for Railway/Vercel deployments.
"""
import os
import sys
import threading
import time
from dotenv import load_dotenv
from system.system_runner import start_system_runner

# Load environment variables from .env
load_dotenv()

from infrastructure.logger import get_logger

# Log setup
logger = get_logger("ProductionLauncher")



def bootstrap():
    """Initializes all V2 components."""
    logger.info(">>> BOOTSTRAPPING UNIFIED V2 PRODUCTION STACK <<<")
    
    # 1. Infrastructure
    from core.event_bus import EventBus
    from core.state_manager import StateManager
    from infrastructure.db import JsonFilePersistence, EventLogPersistence, JSONLPersistence
    from core.orchestrator import Orchestrator
    
    # Use persistent ledger as requested in Phase A5
    ledger_pers = JSONLPersistence("ledger.jsonl")
    bus = EventBus(ledger_pers)
    state_pers = JsonFilePersistence("state.json")
    state_manager = StateManager(state_pers)
    
    # 2. Orchestrator
    orchestrator = Orchestrator(bus, state_manager)
    
    # 3. Register Core Engines as Services
    from core.global_state import GlobalState
    from core.finance_engine import FinanceEngine
    from core.product_life_engine import ProductLifeEngine
    
    # Use JsonFilePersistence for financial containment (matches V2 pattern)
    gs_pers = JsonFilePersistence("global_state.json")
    gs = GlobalState(orchestrator, persistence=gs_pers)
    orchestrator.register_service("global_state", gs)
    
    # Finance & Product Life
    from infrastructure.finance_persistence import FinanceStatePersistence
    fin_pers = FinanceStatePersistence("finance_state.json")
    fe = FinanceEngine(fin_pers)
    orchestrator.register_service("finance", fe)
    
    # 3.2 Commercial Engine (A10)
    from core.commercial_engine import CommercialEngine
    from infrastructure.commercial_persistence import CommercialPersistence
    comm_pers = CommercialPersistence("commercial_state.json")
    ce = CommercialEngine(orchestrator, comm_pers)
    orchestrator.register_service("commercial_engine", ce)

    # 3.3 Product Life Engine (A14) — handles product_creation_requested events
    from infrastructure.product_lifecycle_persistence import ProductLifecyclePersistence
    plc_pers = ProductLifecyclePersistence("product_lifecycle_state.json")
    ple = ProductLifeEngine(persistence=plc_pers)
    orchestrator.register_service("product_life", ple)

    # 3.4 Strategic Opportunity Engine (Radar)
    from core.strategic_opportunity_engine import StrategicOpportunityEngine
    radar_pers = JSONLPersistence("radar_evaluations.json")
    soe = StrategicOpportunityEngine(orchestrator=orchestrator, persistence=radar_pers)
    orchestrator.register_service("strategic_radar", soe)

    # 3.5 Traffic Infrastructure (Governed by TRAFFIC_MODE)
    from infra.traffic.traffic_execution_layer import TrafficExecutionLayer
    traffic_layer = TrafficExecutionLayer(orchestrator)
    traffic_layer.initialize()

    # 4. Activate autonomous system (Orchestrator + Scheduler + Radar + Landing)
    start_system_runner(orchestrator, bus)

    return orchestrator

# Initialize Global Orchestrator
orchestrator_instance = bootstrap()

# Import the Flask app (will be created in api/app.py)
from api.app import create_app
app = create_app(orchestrator_instance)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Launcher starting API on port {port}")
    app.run(host="0.0.0.0", port=port)
