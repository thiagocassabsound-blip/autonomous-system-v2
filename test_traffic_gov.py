import os
import sys
from unittest.mock import MagicMock

# Absolute base path
BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from core.global_state import GlobalState, TRAFFIC_MANUAL
from core.orchestrator import Orchestrator

def test_governance():
    print("Testing Governance Policy...")
    
    # Mock persistence
    mock_pers = MagicMock()
    mock_pers.load.return_value = {"state": "NORMAL", "traffic_mode": "manual"}
    
    bus = MagicMock()
    state_man = MagicMock()
    
    orchestrator = Orchestrator(bus, state_man)
    gs = GlobalState(orchestrator, persistence=mock_pers)
    orchestrator.register_service("global_state", gs)
    
    mode = orchestrator.get_traffic_mode()
    print(f"Current Traffic Mode: {mode}")
    
    if mode == "manual":
        print("[OK] Traffic mode correctly retrieved as 'manual'.")
    else:
        print("[FAIL] Unexpected traffic mode.")

if __name__ == "__main__":
    test_governance()
