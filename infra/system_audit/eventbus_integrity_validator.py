import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET_DIRS = ["engines", "infra", "core"]
EXCLUDE_DIRS = ["system_audit", "tests", "system_backup"]

class EventBusIntegrityValidator:
    """
    Validates structural codebase flow:
    Engine -> EventBus -> Orchestrator -> State Mutation
    Detects forbidden direct writes.
    """
    FORBIDDEN_PATTERNS = [
        r"\.write_state\(",
        r"\.modify_ledger\(",
        r"\.execute_state_change\("
    ]

    @staticmethod
    def validate():
        results = {
            "status": "OK",
            "violations": [],
            "files_scanned": 0
        }
        
        for search_dir in TARGET_DIRS:
            dpath = os.path.join(BASE_DIR, search_dir)
            if not os.path.exists(dpath): continue
            
            for root, dirs, files in os.walk(dpath):
                # Filter exclusions
                dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith("__")]
                
                for f in files:
                    if f.endswith(".py") and f != "orchestrator.py" and f != "state_manager.py":
                        results["files_scanned"] += 1
                        file_path = os.path.join(root, f)
                        
                        try:
                            with open(file_path, 'r', encoding='utf-8') as code_file:
                                content = code_file.read()
                                
                                for pattern in EventBusIntegrityValidator.FORBIDDEN_PATTERNS:
                                    if re.search(pattern, content):
                                        results["status"] = "ERROR"
                                        err = f"architecture_violation_detected: Forbidden direct state mutation found in {f}"
                                        results["violations"].append(err)
                        except Exception as e:
                            pass
        return results
