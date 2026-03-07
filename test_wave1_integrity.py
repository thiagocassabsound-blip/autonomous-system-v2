import sys
import os

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator

def build_test_infra():
    # In-memory persistence mock
    class MockLog:
        def load(self): return []
        def append(self, item): pass
        
    state_manager = StateManager(None) # in-memory for testing
    state_manager._dict = {"processed_events": []}
    
    eb = EventBus(log_persistence=MockLog())
    orchestrator = Orchestrator(eb, state_manager)
    # Register core service mocks
    class MockGS:
        def get_state(self): return "NORMAL"
        def _enter_orchestrated_context(self): pass
        def _exit_orchestrated_context(self): pass
    
    orchestrator.register_service("global_state", MockGS())
    orchestrator.start()
    
    return eb, orchestrator

def test_wave1():
    print("Testing Wave 1 - EventBus to Orchestrator Integrity")
    eb, orchestrator = build_test_infra()
    
    # Simple pub sub test
    received = []
    
    def on_tick(payload):
        received.append("tick")
        
    eb.subscribe("cycle_tick", on_tick)
    eb.emit("cycle_tick", {"tick": 1})
    
    if "tick" not in received:
        print("[FAIL] EventBus Pub/Sub is not working.")
        sys.exit(1)
    else:
        print("[OK] EventBus internal emit works.")
        
    # Test orchestrator receive_event
    try:
        # We need to simulate a formal dispatch from Engine -> Orchestrator
        res = orchestrator.receive_event(
            event_type="test_event",
            payload={"action": "ping"},
            source="wave1_test"
        )
        if res and res["event_type"] == "test_event":
            print("[OK] Engine -> Orchestrator routing is intact.")
        else:
            print("[FAIL] Orchestrator receive_event failed.")
            sys.exit(1)
            
    except Exception as e:
        print(f"[FAIL] Orchestrator exception: {e}")
        sys.exit(1)
        
    print("[SUCCESS] Wave 1 Integrity Validate passed.")

if __name__ == "__main__":
    test_wave1()
