import os
import sys
import json

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
sys.path.append(PROJECT_ROOT)

from core.dashboard_state_manager import DashboardStateManager, PERSISTENCE_DIR

def test_anchored_paths():
    print(f"Project Root: {PROJECT_ROOT}")
    print(f"Persistence Dir: {PERSISTENCE_DIR}")
    
    assert PERSISTENCE_DIR == PROJECT_ROOT, f"PERSISTENCE_DIR mismatch: {PERSISTENCE_DIR} != {PROJECT_ROOT}"
    
    # Initialize manager
    # Note: refresh_cache is called in __init__, which will try to load files
    manager = DashboardStateManager()
    
    print(f"History file path: {manager.paths['history_log']}")
    assert manager.paths['history_log'] == os.path.join(PERSISTENCE_DIR, "dashboard_metrics_history.jsonl")
    
    # Verify that it attempts to load from PERSISTENCE_DIR
    # We can check the logs if we had a way to intercept them, but here we'll just check if the logic holds
    # By running this from a different directory
    
    print("Verification successful: Paths are anchored to the project root.")

if __name__ == "__main__":
    try:
        test_anchored_paths()
    except Exception as e:
        print(f"Verification failed: {e}")
        sys.exit(1)
