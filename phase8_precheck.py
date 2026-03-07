import sys
import os

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)
from infra.governance.compliance_guard import run_governance_preflight

def phase8_precheck():
    # 1. Check DRY_RUN_MODE
    env_path = os.path.join(BASE_DIR, ".env")
    with open(env_path, "r", encoding="utf-8") as f:
        env_content = f.read()
        
    if "DRY_RUN_MODE=true" not in env_content:
        print("[FAIL] DRY_RUN_MODE=true is missing in .env")
        sys.exit(1)
    else:
        print("[OK] DRY_RUN_MODE is active.")

    # 2. Check existence of files
    files_to_check = [
        r"system_governance\constitution.md",
        r"system_governance\blocks.md",
        r"system_governance\implementation_ledger.md",
        r"system_governance\dashboard_implementation_plan.md",
        r"system_docs\implementation_execution_plan.md",
        r"system_docs\implementation_gap_report.md"
    ]
    for f in files_to_check:
        full_path = os.path.join(BASE_DIR, f)
        if not os.path.exists(full_path):
            print(f"[FAIL] Missing file: {f}")
            sys.exit(1)
        print(f"[OK] File loaded: {f}")

    # 3. Governance Preflight
    action = {
        "name": "Phase 8 Activation Pre-check",
        "type": "file_mutation",
        "target_file": "execution_log.md",
        "operation": "append",
        "actor": "GovernanceLayer",
        "is_structural_modification": False
    }
    
    if run_governance_preflight(action):
        print("[OK] Governance Preflight PASSED.")
    else:
        print("[FAIL] Governance Preflight FAILED.")
        sys.exit(1)

if __name__ == "__main__":
    phase8_precheck()
