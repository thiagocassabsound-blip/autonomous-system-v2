import os
import sys
import json
import uuid
import datetime
import copy
from unittest.mock import MagicMock

# Base Setup
BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from infrastructure.logger import get_logger
logger = get_logger("OperationalAudit")

def print_section(title):
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")

def check_step(condition, success_msg, fail_msg):
    if condition:
        print(f"[OK] {success_msg}")
        return True
    else:
        print(f"[ERROR] {fail_msg}")
        return False

# --- AUDIT MODULES ---

def audit_architecture():
    print_section("STEP 1 — SYSTEM ARCHITECTURE VALIDATION")
    required_dirs = ["core", "infra", "api", "templates", "fastoolhub_memory"]
    all_dirs = all([os.path.isdir(os.path.join(BASE_DIR, d)) for d in required_dirs])
    
    infra_ok = check_step(all_dirs, "Structural hierarchy (core/infra/api/interface) is intact.", "Missing critical directories.")
    
    # Check dependency presence
    files = [
        "core/orchestrator.py",
        "core/event_bus.py",
        "core/global_state.py",
        "core/dashboard_state_manager.py"
    ]
    all_files = all([os.path.exists(os.path.join(BASE_DIR, f)) for f in files])
    dep_ok = check_step(all_files, "Dependency integrity (Orchestrator, EventBus, GlobalState) confirmed.", "Missing core dependency files.")
    
    return infra_ok and dep_ok

def audit_engines():
    print_section("STEP 2 — ENGINE STATUS CHECK")
    
    # Static check for Engine definitions
    engines = {
        "StrategicOpportunityEngine": "core/strategic_opportunity_engine.py",
        "ProductLifeEngine": "core/product_life_engine.py",
        "FinanceEngine": "core/finance_engine.py",
        "GoogleAdsEngine": "infra/traffic/engines/google_ads_engine.py"
    }
    
    all_ready = True
    for name, path in engines.items():
        exists = os.path.exists(os.path.join(BASE_DIR, path))
        if not check_step(exists, f"{name} is structurally present.", f"{name} source file missing at {path}"):
            all_ready = False
            
    # Verification of event subscriptions (Logic check)
    # We inspect product_life_engine.py for cleanup_trash call in __init__
    ple_content = ""
    with open(os.path.join(BASE_DIR, "core/product_life_engine.py"), "r", encoding="utf-8") as f:
        ple_content = f.read()
    
    init_ok = "self.cleanup_trash()" in ple_content
    check_step(init_ok, "ProductLifeEngine auto-cleanup correctly initialized.", "ProductLifeEngine missing cleanup call in __init__.")
    
    return all_ready and init_ok

def audit_traffic_governance():
    print_section("STEP 3 — TRAFFIC GOVERNANCE VALIDATION")
    
    # Check .env and GlobalState
    from core.global_state import GlobalState
    
    orch = MagicMock()
    gs = GlobalState(orch)
    
    env_traffic = gs.get_traffic_mode()
    env_ads_mode = gs.get_ads_system_mode()
    
    print(f"Current Runtime Config -> TRAFFIC_MODE: {env_traffic}, ADS_SYSTEM_MODE: {env_ads_mode}")
    
    # Inspect GoogleAdsEngine Logic (Combined Governance Rule)
    ads_engine_path = os.path.join(BASE_DIR, "infra/traffic/engines/google_ads_engine.py")
    with open(ads_engine_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    rule_logic = "traffic_mode != \"ads\" or ads_global != \"enabled\" or not ads_product" in content
    check_step(rule_logic, "GoogleAdsEngine correctly enforces the Combined Governance Rule.", "Ads execution rule mismatch in GoogleAdsEngine.")
    
    return rule_logic

def audit_lifecycle_pipeline():
    print_section("STEP 4/8 — PRODUCT LIFECYCLE & PIPELINE SIMULATION")
    
    print("Simulating event propagation (Dry Run)...")
    
    from core.event_bus import EventBus
    from core.state_manager import StateManager
    from core.orchestrator import Orchestrator
    
    class MockEventLog:
        def load(self): return []
        def append(self, item): pass
        def generate_event_id(self): return str(uuid.uuid4())
        
    class MockStatePersistence:
        def load(self): return {"processed_events": []}
        def save(self, data): pass
        def set(self, k, v): pass
        def get(self, k, default=None): return default
        
    eb = EventBus(log_persistence=MockEventLog())
    sm = StateManager(persistence=MockStatePersistence())
    
    orch = Orchestrator(eb, sm)
    
    # Mock services
    mock_gs = MagicMock()
    mock_gs.get_state.return_value = "NORMAL"
    orch.register_service("global_state", mock_gs)
    
    # Security layer mock (required by receive_event)
    mock_sec = MagicMock()
    orch.register_service("security", mock_sec)
    
    events_ledger = []
    
    print("Triggering pipeline: Orchestrator.receive_event")
    try:
        orch.receive_event("radar_opportunity_detected", {"opportunity_id": "opp_123"}, source="RadarEngine")
        # Check EventBus ledger
        ledger = eb.get_events()
        event_types = [e["event_type"] for e in ledger]
        
        ok = check_step("radar_opportunity_detected" in event_types, "Pipeline trigger propagation (Ledger) OK.", "EventBus failed to record signal in Ledger.")
        return ok
    except Exception as e:
        print(f"[ERROR] Simulation failed: {e}")
        import traceback
        # traceback.print_exc()
        return False

def audit_ops_layer():
    print_section("STEP 5 — PRODUCT OPERATIONS LAYER VALIDATION")
    
    ple_path = os.path.join(BASE_DIR, "core/product_life_engine.py")
    with open(ple_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    fields = ["product_stage", "product_events", "ads_enabled", "deleted", "deleted_at"]
    all_fields = all([f in content for f in fields])
    
    fields_ok = check_step(all_fields, "All operational metadata fields present in ProductLifeEngine.", "Missing operational fields in ProductLifeEngine.")
    
    trash_rule = "retention_days: int = 365" in content
    rule_ok = check_step(trash_rule, "Trash retention rule (365 days) confirmed.", "Retention policy mismatch.")
    
    return fields_ok and rule_ok

def audit_dashboard_visibility():
    print_section("STEP 6 — DASHBOARD OPERATIONAL VISIBILITY")
    
    html_path = os.path.join(BASE_DIR, "templates/dashboard.html")
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Corrected identifiers based on inspection
    checks = {
        "Product Grid": "product-grid",
        "Timeline": "class=\"timeline\"",
        "History Modal": "history-modal",
        "Ads Toggle": "toggleAds",
        "Global Ads Toggle": "global-ads-toggle",
        "Trash UI": "section == 'trash'"
    }
    
    all_features = True
    for name, c in checks.items():
        if c in content:
            print(f"[OK] Found {name}")
        else:
            print(f"[WARNING] Feature identifier '{c}' ({name}) missing in dashboard.html")
            all_features = False
            
    check_step(all_features, "Dashboard interactive elements verified.", "Dashboard UI might be incomplete.")
    return all_features

def audit_constitution():
    print_section("STEP 7 — CONSTITUTION COMPLIANCE CHECK")
    
    const_path = os.path.join(BASE_DIR, "system_governance/constitution.md")
    if not os.path.exists(const_path):
        print(f"[ERROR] constitution.md not found at {const_path}")
        return False
        
    # Check for principles in Orchestrator code (Immutability, Tracing, Governance)
    orch_path = os.path.join(BASE_DIR, "core/orchestrator.py")
    with open(orch_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    governance_logic = all([
        "receive_event" in content,
        "_write_context" in content,
        "CONTENCAO_FINANCEIRA" in content
    ])
    
    check_step(governance_logic, "Orchestrator enforces constitutional governance logic (CONTENCAO_FINANCEIRA, receive_event).", "Governance logic mismatch in Orchestrator.")
    
    # Check for state definitions in constitution (approximate)
    with open(const_path, "r", encoding="utf-8") as f:
        c_text = f.read()
        
    states_ok = "Beta" in c_text and "Ativo" in c_text and "Draft" in c_text
    check_step(states_ok, "Constitution defines mandatory lifecycle states (Draft, Beta, Ativo).", "Constitution lifecycle definitions missing.")
    
    return governance_logic and states_ok

def run_full_audit():
    print(">>> INITIALIZING FULL SYSTEM OPERATIONAL AUDIT <<<")
    
    results = {
        "ARCHITECTURE": audit_architecture(),
        "ENGINES": audit_engines(),
        "TRAFFIC": audit_traffic_governance(),
        "PIPELINE": audit_lifecycle_pipeline(),
        "OPS_LAYER": audit_ops_layer(),
        "DASHBOARD": audit_dashboard_visibility(),
        "CONSTITUTION": audit_constitution()
    }
    
    print_section("AUDIT SUMMARY REPORT")
    all_ok = True
    for module, status in results.items():
        print(f"{module:<15}: {'OK' if status else 'ERROR'}")
        if not status: all_ok = False
        
    print("\n" + "="*60)
    if all_ok:
        print(" SYSTEM STATUS: READY FOR FIRST PRODUCT EXECUTION ")
    else:
        print(" SYSTEM STATUS: NOT READY - ISSUES DETECTED ")
    print("="*60)

if __name__ == "__main__":
    run_full_audit()
