import sys
import os

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from infra.governance.compliance_guard import run_governance_preflight

def main():
    action = {
        "name": "Upgrade Dashboard Operational Layers",
        "is_structural_modification": True,
        "ledger_task_id": "DASHBOARD_OPERATIONAL_LAYERS"
    }
    
    try:
        success = run_governance_preflight(action)
        if success:
            print("[SUCCESS] Preflight Check Passed!")
        else:
            print("[FAIL] Preflight Failed (check output).")
    except Exception as e:
        print(f"[ERROR] Preflight Exception: {e}")

if __name__ == "__main__":
    main()
