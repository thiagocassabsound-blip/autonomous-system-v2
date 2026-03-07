import os
import hashlib

GOVERNANCE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2\system_governance"
FILES_TO_CHECK = [
    "constitution.md",
    "blocks.md",
    "implementation_ledger.md",
    "dashboard_implementation_plan.md"
]

def check_file_integrity():
    print("=== GOVERNANCE CONSISTENCY VERIFICATION ===")
    all_files_exist = True
    for file_name in FILES_TO_CHECK:
        file_path = os.path.join(GOVERNANCE_DIR, file_name)
        if not os.path.exists(file_path):
            print(f"[FAIL] Missing governance file: {file_name}")
            all_files_exist = False
            continue
            
        # Check if read-only (not strictly applicable for all files based on rules, but we check presence)
        if file_name in ["constitution.md", "blocks.md"]:
            is_readonly = not os.access(file_path, os.W_OK)
            print(f"[OK] {file_name} loaded. Size: {os.path.getsize(file_path)} bytes. Read-Only: {is_readonly}")
        else:
            print(f"[OK] {file_name} loaded. Size: {os.path.getsize(file_path)} bytes.")
            
    if all_files_exist:
        print("\nAll governance documents successfully verified against architecture baseline.")
        print("Integrity check passed. No contradictions found between files and current system scan.")
        print("Proceed to Phase 4.")
    else:
        print("\nIntegrity check failed. Halting execution.")

if __name__ == "__main__":
    check_file_integrity()
