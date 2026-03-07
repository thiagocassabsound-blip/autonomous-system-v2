import sys
import os

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from infra.governance.compliance_guard import run_governance_preflight

def main():
    action = {
        "name": "Install Dashboard System",
        "is_structural_modification": True,
        "ledger_task_id": "DASHBOARD_IMPLEMENTATION"
    }
    
    try:
        success = run_governance_preflight(action)
        if success:
            print("Preflight Check Passed!")
        else:
            print("Preflight Failed (check output).")
    except Exception as e:
        print(f"Preflight Exception: {e}")

if __name__ == "__main__":
    main()
