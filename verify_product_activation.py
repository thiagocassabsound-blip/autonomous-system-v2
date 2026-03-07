
import os
import sys
import json
import time
import uuid
from datetime import datetime, timezone

# Add current directory to path
sys.path.append(os.getcwd())

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from core.global_state import GlobalState, NORMAL
from core.finance_engine import FinanceEngine
from core.product_life_engine import ProductLifeEngine
from core.strategic_opportunity_engine import StrategicOpportunityEngine
from radar.radar_engine import RadarEngine
from radar.providers.synthetic_audit_provider import SyntheticAuditProvider
from infrastructure.db import JsonFilePersistence, EventLogPersistence
from infrastructure.finance_persistence import FinanceStatePersistence
from infrastructure.product_lifecycle_persistence import ProductLifecyclePersistence
from infrastructure.opportunity_radar_persistence import OpportunityRadarPersistence
from infra.landing import landing_recommendation_handler

def run_audit():
    print(">>> STARTING BLOCO 3 PRODUCT PIPELINE AUDIT <<<")
    
    # 1. Setup Audit Persistence (Separate files)
    ledger_file = "audit_block3_ledger.jsonl"
    state_file = "audit_block3_state.json"
    finance_file = "audit_block3_finance.json"
    product_file = "audit_block3_products.json"
    radar_file = "audit_block3_radar.json"
    global_state_file = "audit_block3_gs.json"
    
    # Cleanup old audit files
    for f in [ledger_file, state_file, finance_file, product_file, radar_file, global_state_file]:
        if os.path.exists(f):
            os.remove(f)
            
    ledger_pers = EventLogPersistence(ledger_file)
    bus = EventBus(ledger_pers)
    state_pers = JsonFilePersistence(state_file)
    state_manager = StateManager(state_pers)
    
    # 2. Initialize Orchestrator
    orchestrator = Orchestrator(bus, state_manager)
    
    # 3. Register Services
    # Global State
    gs_pers = JsonFilePersistence(global_state_file)
    gs = GlobalState(orchestrator, gs_pers)
    orchestrator.register_service("global_state", gs)
    gs._enter_orchestrated_context()
    gs.request_state_update(NORMAL, orchestrated=True)
    gs._exit_orchestrated_context()
    
    # Finance
    fin_pers = FinanceStatePersistence(finance_file)
    # Seed some balance to avoid immediate containment
    fin_pers.save({
        "stripe_current_balance": 1000.0,
        "openai_current_balance": 500.0,
        "ad_spend_sessions": [10.0, 10.0, 10.0]
    })
    fe = FinanceEngine(fin_pers)
    orchestrator.register_service("finance", fe)
    
    # Product Life
    plc_pers = ProductLifecyclePersistence(product_file)
    ple = ProductLifeEngine(persistence=plc_pers)
    orchestrator.register_service("product_life", ple)
    
    # Strategic Radar
    radar_pers = OpportunityRadarPersistence(radar_file)
    soe = StrategicOpportunityEngine(orchestrator=orchestrator, persistence=radar_pers)
    orchestrator.register_service("strategic_radar", soe)
    
    # 4. Bootstrap Landing Engine (Crucial for recommendation -> product bridging)
    landing_recommendation_handler.bootstrap(event_bus=bus, orchestrator=orchestrator)
    print("[Audit] Landing Engine Bootstrapped.")
    
    # 5. Initialize Radar Engine with Synthetic Provider
    radar = RadarEngine(orchestrator=orchestrator, strategic_engine=soe)
    # Ensure SyntheticAuditProvider is used exclusively for the audit
    radar.providers = [SyntheticAuditProvider()]
    
    # 6. Execute Radar Cycle
    print("[Audit] Executing Radar Cycle (Synthetic Audit Provider)...")
    keyword = "meeting scheduling friction"
    category = "saas"
    
    # Injected overrides to ensure HIGH score and recommendation
    overrides = {
        "freq": 85.0,
        "intensity": 90.0,
        "recurrence": 80.0,
        "persistence": 85.0,
        "intent": 85.0,
        "solutions": 75.0,
        "cpc": 80.0,
        "validation": 90.0,
        "growth_score": 85.0,
        "occurrences": 1500,
        "growth_percent": 45.0,
        "noise_filter_score": 95.0,
        "score_global": 85.0,
        "roas": 2.5
    }
    
    radar_result = radar.run_cycle(keyword=keyword, category=category, eval_payload_overrides=overrides)
    
    print(f"[Audit] Radar Cycle Completed. Status: {radar_result.get('status')}")
    
    # 7. Wait for EventBus to process the recommendation -> creation chain
    print("[Audit] Waiting for event chain (Recommendation -> Product Creation)...")
    time.sleep(2)
    
    # 8. Verify Persistence
    print("--- Audit Results ---")
    
    # A. Check Radar Evaluations
    evals = list(radar_pers.load_all())
    print(f"Radar Evaluations stored: {len(evals)}")
    if evals:
        last_eval = evals[-1]
        print(f"  Last Eval Score: {last_eval.get('score_final')}")
        print(f"  Recommended: {last_eval.get('recommended')}")
        print(f"  ICE: {last_eval.get('ice')}")
        
    # B. Check Product Lifecycle State
    products = plc_pers.load()
    print(f"Product Drafts created: {len(products)}")
    for pid, pdata in products.items():
        print(f"  Product ID: {pid}")
        print(f"  State: {pdata.get('state')}")
        print(f"  Created At: {pdata.get('created_at')}")
        print(f"  Opportunity ID: {pdata.get('opportunity_id')}")
        
    # C. Check Financial State
    fs = fe.get_state()
    print(f"Finance State: Stripe={fs.get('stripe_current_balance')}, OpenAI={fs.get('openai_current_balance')}")
    
    # D. Trigger Health Monitor through Cycle Tick
    print("[Audit] Triggering Cycle Tick for Health Check...")
    # Health check runs every 50 ticks by default. Let's force it by mocking the tick count or setting env.
    os.environ["HEALTH_CHECK_INTERVAL"] = "1"
    orchestrator.receive_event("cycle_tick", {"tick": 1})
    
    # E. Final Log Summary
    with open(ledger_file, "r") as f:
        try:
            events = json.load(f)
        except:
            events = []
    
    print(f"Total Ledger Events: {len(events)}")
    types = [e.get("event_type") for e in events]
    print(f"Event Flow Types: {types}")
    
    # Verification Gates
    gates = {
        "Radar Recommended": any(e.get("event_type") == "expansion_recommendation_event" for e in events),
        "Product Requested": any(e.get("event_type") == "product_creation_requested" for e in events),
        "Product Drafted": any(e.get("event_type") == "product_draft_created" for e in events),
        "Finance Projected": any(e.get("event_type") == "financial_projection_updated" for e in events)
    }
    
    for gate, passed in gates.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"Gate [{gate}]: {status}")

    # Success Condition
    if all(gates.values()):
        print("\n>>> AUDIT SUCCESSFUL: Product Pipeline Operational <<<")
    else:
        print("\n>>> AUDIT FAILED: Pipeline discontinuous <<<")

if __name__ == "__main__":
    run_audit()
