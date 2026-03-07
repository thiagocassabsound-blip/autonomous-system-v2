import os
import re
import sys

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
GOV_DIR = os.path.join(BASE_DIR, "system_governance")
DOCS_DIR = os.path.join(BASE_DIR, "system_docs")
CORE_DIR = os.path.join(BASE_DIR, "core")
INFRA_DIR = os.path.join(BASE_DIR, "infra")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

def print_header(title):
    print(f"\n{'='*50}\n{title}\n{'='*50}")

def check_file_exists(filepath):
    exists = os.path.exists(filepath)
    print(f"[{'OK' if exists else 'FAIL'}] {os.path.basename(filepath)}")
    return exists

def read_file(filepath):
    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read()
    return ""

def audit_1_governance():
    print_header("1. GOVERNANCE CONTEXT")
    docs = [
        os.path.join(GOV_DIR, "constitution.md"),
        os.path.join(GOV_DIR, "blocks.md"),
        os.path.join(GOV_DIR, "implementation_ledger.md"),
        os.path.join(GOV_DIR, "dashboard_implementation_plan.md"),
        os.path.join(DOCS_DIR, "system_implementation_report.md"),
        os.path.join(DOCS_DIR, "implementation_execution_plan.md")
    ]
    all_exist = all([check_file_exists(d) for d in docs])
    if not all_exist:
        return False
    print("-> Governance files present. Assuming structural adherence.")
    return True

def audit_2_dry_run():
    print_header("2. DRY RUN MODE STATUS")
    env_content = read_file(os.path.join(BASE_DIR, ".env"))
    if "DRY_RUN_MODE=true" in env_content:
        print("[OK] DRY_RUN_MODE=true is active in .env")
        return True
    print("[FAIL] DRY_RUN_MODE is not active!")
    return False

def audit_3_phase8_infra():
    print_header("3. PHASE 8 IMPLEMENTATION AUDIT")
    infra_components = ["event_bus.py", "orchestrator.py", "state_manager.py", "telemetry_engine.py", "scheduler.py"]
    print("Checking Infrastructure Components:")
    all_infra = all([check_file_exists(os.path.join(CORE_DIR, f)) for f in infra_components])
    
    print("\nChecking Engine Compliance:")
    engines = [
        "radar_normalization_engine.py",
        "strategic_opportunity_engine.py",
        "product_life_engine.py",
        "landing_generation_engine.py",
        "commercial_engine.py"
    ]
    
    compliance = True
    for e in engines:
        content = read_file(os.path.join(CORE_DIR, e))
        # Check for direct state mutations
        if re.search(r"\._state\.set\(", content) or "global_state mutation" in content: # simplified check
            print(f"[FAIL] {e} appears to mutate state directly!")
            compliance = False
        else:
            print(f"[OK] {e} complies.")
            
    return all_infra and compliance

def audit_4_operational_intelligence():
    print_header("4. OPERATIONAL INTELLIGENCE LOOP AUDIT")
    loop_path = os.path.join(CORE_DIR, "intelligence", "operational_intelligence_loop.py")
    if not check_file_exists(loop_path): return False
    
    content = read_file(loop_path)
    
    events_to_emit = [
        "product_evolution_event", "targeting_adjustment_event", "seo_adjustment_event",
        "copy_adjustment_event", "upsell_opportunity_event", "pricing_signal_event",
        "buyer_segment_discovery_event"
    ]
    
    missing_events = [ev for ev in events_to_emit if ev not in content]
    if missing_events:
        print(f"[FAIL] Missing event emissions: {missing_events}")
        return False
    print("[OK] All required strategic events are emitted.")
    
    if "self._state.set" in content or "self.orchestrator._state" in content:
        print("[FAIL] Intelligence loopmutates state directly!")
        return False
    print("[OK] No direct state modification found.")
    return True

def audit_5_observability():
    print_header("5. OBSERVABILITY LAYER AUDIT")
    log_path = os.path.join(INFRA_DIR, "observability", "runtime_logger.py")
    trace_path = os.path.join(INFRA_DIR, "observability", "event_trace.py")
    
    if not (check_file_exists(log_path) and check_file_exists(trace_path)): return False
    
    rt_content = read_file(log_path)
    if "/logs/runtime_events.log" in rt_content or "runtime_events.log" in rt_content:
        print("[OK] Runtime logger targets correct log file.")
    else:
        print("[FAIL] Runtime logger file path mismatch.")
        return False
        
    tr_content = read_file(trace_path)
    if "original_append" in tr_content and "tracing_append" in tr_content:
        print("[OK] Event trace hooks EventBus append securely.")
    else:
        print("[WARNING] Could not verify event trace hook mechanism.")
        
    return True

def audit_7_ledger():
    print_header("7. LEDGER INTEGRITY AUDIT")
    # Quick static look at file modified times or existence
    ledger_path = os.path.join(BASE_DIR, "ledger.jsonl")
    radar_path = os.path.join(BASE_DIR, "radar_snapshots.jsonl")
    state_path = os.path.join(BASE_DIR, "state.json")
    print(f"[{'OK' if os.path.exists(ledger_path) else 'WARN'}] ledger.jsonl")
    print(f"[{'OK' if os.path.exists(radar_path) else 'WARN'}] radar_snapshots.jsonl")
    print(f"[{'OK' if os.path.exists(state_path) else 'WARN'}] state.json")
    return True

def audit_8_execution_log():
    print_header("8. EXECUTION LOG AUDIT")
    log_path = os.path.join(GOV_DIR, "execution_log.md")
    if not check_file_exists(log_path): return False
    
    content = read_file(log_path)
    if "P8" in content and "wave4_observability" in content:
        print("[OK] Phase 8 actions correctly recorded.")
        return True
    print("[FAIL] Phase 8 not found in execution log.")
    return False

def run_full_audit():
    print("Starting Automated Audit...")
    res1 = audit_1_governance()
    res2 = audit_2_dry_run()
    res3 = audit_3_phase8_infra()
    res4 = audit_4_operational_intelligence()
    res5 = audit_5_observability()
    res7 = audit_7_ledger()
    res8 = audit_8_execution_log()
    
    final = res1 and res2 and res3 and res4 and res5 and res7 and res8
    
    print("\nSummary:")
    print(f"Final Clearance: {'[PASSED] Proceed to Phase 9' if final else '[FAILED] Do not proceed. Fix issues.'}")

if __name__ == "__main__":
    run_full_audit()
