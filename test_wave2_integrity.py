import os
import re

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
CORE_DIR = os.path.join(BASE_DIR, "core")

# Files corresponding to Wave 2
ENGINES_TO_CHECK = [
    "radar_normalization_engine.py",
    "strategic_opportunity_engine.py",
    "product_life_engine.py",
    "landing_generation_engine.py",
    "commercial_engine.py"
]

def verify_engines():
    print("Wave 2 Engine Verification:")
    failed = False
    
    for engine_file in ENGINES_TO_CHECK:
        file_path = os.path.join(CORE_DIR, engine_file)
        if not os.path.exists(file_path):
            print(f"[MISSING] {engine_file}")
            continue
            
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # Check for direct state mutation
        # e.g. state_manager.set(
        if re.search(r"\bstate_manager\.set\(", content) or re.search(r"self\._state\.set\(", content):
            print(f"[FAIL] {engine_file} contains direct state mutation!")
            failed = True
        else:
            print(f"[OK] {engine_file} has no direct state mutations.")
            
        # Check if it utilizes Orchestrator / EventBus
        if "self.orchestrator.emit_event" in content or "self.orchestrator.receive_event" in content:
            print(f"  -> Properly routes to Orchestrator.")
        else:
            if "EventBus" not in content and "orchestrator" not in content:
                print(f"  -> [WARNING] Engine might not route through orchestrator.")

    if failed:
        print("\n[RESULT] Integrity violations found!")
        import sys
        sys.exit(1)
    else:
        print("\n[SUCCESS] Wave 2 Engines pass architectural constraints.")

if __name__ == "__main__":
    verify_engines()
