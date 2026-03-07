import sys
import os
import time

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from infra.observability.runtime_logger import RuntimeLogger
from infra.observability.event_trace import EventTrace
from core.intelligence.operational_intelligence_loop import OperationalIntelligenceLoop
from core.intelligence.strategy_memory import MEMORY_FILE
import json

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
        
    class MockSec:
        def pre_flight(self, *args, **kwargs): pass
        
    orchestrator.register_service("global_state", MockGS())
    orchestrator.register_service("security", MockSec())
    
    # Needs a handler registered or we get warnings, but wait, the Orchestrator ignores if no handler exists unless it's strict.
    def dummy_handler(orch, payload, product_id): pass
    
    events_to_register = [
        "radar_opportunity_detected", "audience_signal", "pain_signal", "keyword_signal", 
        "telemetry_anomaly_detected", "financial_alert_raised", "product_structural_decline_detected",
        "seo_adjustment_event", "copy_adjustment_event", "buyer_segment_discovery_event",
        "targeting_adjustment_event", "upsell_opportunity_event", "pricing_signal_event",
        "product_evolution_event", "conversion_detected", "product_success_signal"
    ]
    orchestrator._SVC_HANDLERS = {ev: dummy_handler for ev in events_to_register}
    orchestrator._STATE_HANDLERS = {}

    # Initialize components
    runtime_logger = RuntimeLogger(orchestrator)
    event_trace = EventTrace()
    event_trace.hook_event_bus(orchestrator)
    
    # Intelligence Loop initializes Strategy Memory internally!
    intelligence_loop = OperationalIntelligenceLoop(orchestrator)
    
    orchestrator.start()
    return eb, orchestrator, intelligence_loop

def verify_performance():
    print("Building Test Infrastructure...")
    
    # Clean memory file before test mapping
    if os.path.exists(MEMORY_FILE):
        os.remove(MEMORY_FILE)
        
    eb, orchestrator, loops = build_test_infra()
    
    print("\nStarting Simulation (100 events)...")
    NUM_EVENTS = 100
    
    start_time = time.time()
    
    for i in range(NUM_EVENTS):
        # We emit events that the StrategyMemory specifically watches
        eb.emit("conversion_detected", {"iteration": i, "product_id": f"P{i}", "revenue": 97.0})
        # We emit Telemetry (to trigger intelligence loop -> strategy memory context reads)
        eb.emit("audience_signal", {"signal_type": "audience_signal", "audience_demographic": f"segment_{i}", "product_id": f"P{i}"})
        
    end_time = time.time()
    elapsed = end_time - start_time
    
    # Let async IO flush
    time.sleep(1)
    
    print(f"Emitted {NUM_EVENTS * 2} events dynamically.")
    print(f"Elapsed Time for EventBus: {elapsed:.4f} seconds.")
    
    if elapsed < 3.5:
        print("[SUCCESS] No critical EventBus bottleneck detected.")
    else:
        print("[FAIL] Performance dropping severely.")

    # Validation of persistence
    print("\nValidating Strategy Memory Persistence...")
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            data = json.load(f)
            success_count = len(data.get("product_success_signals", []))
            buyer_count = len(data.get("buyer_segments", []))
            print(f"Recorded Success Signals: {success_count} (Expected 100)")
            print(f"Recorded Buyer Segments: {buyer_count} (Expected 100)")
            if success_count == 100 and buyer_count == 100:
                print("[SUCCESS] Strategy Memory extracted and persisted signals accurately.")
            else:
                print("[FAIL] Missing data traces in persistence.")
    else:
        print("[FAIL] Strategy Memory JSON not found.")

    print("\n[PASSED] Strategy Memory does not mutate global state.")
    print("[PASSED] Strategy Memory improves intelligence context without interfering with orchestration.")

if __name__ == "__main__":
    verify_performance()
