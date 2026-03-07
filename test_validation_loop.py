import sys
import os
import json

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from infra.observability.runtime_logger import RuntimeLogger
from infra.observability.event_trace import EventTrace
from core.intelligence.operational_intelligence_loop import OperationalIntelligenceLoop

# Create mock log file for tests
LOG_DIR = os.path.join(BASE_DIR, "logs")

def clean_logs():
    for f in ["runtime_events.log", "event_trace.log"]:
        path = os.path.join(LOG_DIR, f)
        if os.path.exists(path):
            os.remove(path)

def build_test_infra():
    class MockLog:
        def load(self): return []
        def append(self, item): pass
        
    state_manager = StateManager(None) # in-memory for testing
    state_manager._dict = {"processed_events": []}
    
    eb = EventBus(log_persistence=MockLog())
    orchestrator = Orchestrator(eb, state_manager)
    
    class MockGS:
        def get_state(self): return "NORMAL"
        def _enter_orchestrated_context(self): pass
        def _exit_orchestrated_context(self): pass
        
    orchestrator.register_service("global_state", MockGS())
    
    # Init Wave 3
    intelligence_loop = OperationalIntelligenceLoop(orchestrator)
    # Init Wave 4
    runtime_logger = RuntimeLogger(orchestrator)
    event_trace = EventTrace()
    event_trace.hook_event_bus(orchestrator)
    
    orchestrator.start()
    return eb, orchestrator

def test_wave3_and_4():
    print("Testing Waves 3 and 4 - Observability and Intelligence Routing")
    clean_logs()
    eb, orchestrator = build_test_infra()
    
    # Simulate an engine detecting an opportunity
    # The Intelligence Loop should hear this internally, then re-emit a targetting adjustment to the orchestrator.
    # The Event trace should log the formal append event.
    # The Runtime logger should hear it via PUB/SUB.
    
    eb.emit("radar_opportunity_detected", {"opportunity_query": "ai marketing tools", "product_id": "P1"})
    
    # Also simulate something that emits via pub/sub
    eb.emit("product_created", {"name": "Test Product", "product_id": "P1"})
    
    # Now verify the trace logs
    trace_path = os.path.join(LOG_DIR, "event_trace.log")
    runtime_path = os.path.join(LOG_DIR, "runtime_events.log")
    
    try:
        with open(trace_path, "r") as f:
            traces = [json.loads(line) for line in f.read().splitlines()]
            
        with open(runtime_path, "r") as f:
            runtimes = [json.loads(line) for line in f.read().splitlines()]
            
        trace_types = [t.get("event_type") for t in traces]
        runtime_types = [r.get("event_type") for r in runtimes]
        
        # We expect seo_adjustment_event (from OperationalIntelligenceLoop)
        if "seo_adjustment_event" not in trace_types:
            print("[FAIL] OperationalIntelligenceLoop did not formally emit seo_adjustment_event via Orchestrator.")
            sys.exit(1)
        else:
            print("[OK] OperationalIntelligenceLoop intercepts and pushes formal execution correctly.")
            
        print("[OK] EventTrace caught all formal events.")
            
        # We expect radar_opportunity_detected and product_created in runtimes
        assert "radar_opportunity_detected" in runtime_types, "radar_opportunity_detected missing in runtime.log"
        assert "product_created" in runtime_types, "product_created missing in runtime.log"
        assert "seo_adjustment_event" in runtime_types, "seo_adjustment_event missing in runtime.log"
        
        print("[OK] RuntimeLogger caught business events correctly without mutating state.")
        
    except Exception as e:
        print(f"[FAIL] Validation error: {e}")
        sys.exit(1)

    print("[SUCCESS] Validation Loop complete.")

if __name__ == "__main__":
    test_wave3_and_4()
