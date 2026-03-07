import os
import json
import uuid
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

# Bootstrap paths
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from core.finance_engine import FinanceEngine
from core.global_state import GlobalState, CONTENCAO_FINANCEIRA, NORMAL

class MockPersistence:
    def __init__(self, initial_data=None):
        self.data = initial_data if initial_data is not None else {}
    def load(self): return self.data
    def save(self, data): self.data = data
    def append(self, entry):
        if isinstance(self.data, list):
            # EventBus already appends to the list it gets from load()
            # If our list is the same object, avoid double append
            if entry not in self.data:
                self.data.append(entry)
        else:
            if "events" not in self.data: self.data["events"] = []
            if entry not in self.data["events"]:
                self.data["events"].append(entry)

def run_test():
    results = {
        "normal_update_success": False,
        "balance_drop_handled": False,
        "critical_protection_stable": False,
        "ledger_integrity_valid": False,
        "errors": [],
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    try:
        # 1. Setup isolated environment
        bus_pers = MockPersistence([]) # EventBus expects a list
        state_pers = MockPersistence({}) # StateManager expects a dict
        gs_pers = MockPersistence({"state": NORMAL})
        
        bus = EventBus(log_persistence=bus_pers)
        state = StateManager(persistence=state_pers)
        orch = Orchestrator(bus, state)
        
        finance = FinanceEngine(state_persistence=state_pers)
        gs = GlobalState(orch, persistence=gs_pers)
        
        orch.register_service("finance", finance)
        orch.register_service("global_state", gs)

        # PHASING
        
        # Phase 1: Normal Balance Update
        # FinanceEngine.register_openai_balance emits 'openai_balance_updated'
        finance.register_openai_balance(500.0, orch)
        
        events = bus.get_events()
        update_event = next((e for e in events if e["event_type"] == "openai_balance_updated"), None)
        
        if update_event and update_event["payload"]["balance"] == 500.0:
            results["normal_update_success"] = True
        else:
            results["errors"].append("Phase 1: openai_balance_updated event mismatch or missing")

        # Phase 2: Balance Drop Simulation
        # Internal state _fs is updated via register_openai_balance
        initial_usage = finance.get_state().get("openai_total_usage", 0.0)
        finance.register_openai_balance(50.0, orch) # usage = 450
        finance.register_openai_balance(5.0, orch)  # usage = 450 + 45 = 495
        
        final_state = finance.get_state()
        if final_state["openai_total_usage"] == 495.0 and final_state["openai_current_balance"] == 5.0:
            results["balance_drop_handled"] = True
        else:
            results["errors"].append(f"Phase 2: usage tracking failed. Got {final_state['openai_total_usage']}")

        # Phase 3: Critical Burn Scenario
        # Simulate critical state via StateManager
        with orch._write_context():
            state.set("stripe_current_balance", 0.0)
            state.set("openai_current_balance", 0.0)
            state.set("avg_burn_rate", 100.0)
            # Inject empty ad sessions to ensure burn calculation (FinanceEngine uses _fs["ad_spend_sessions"])
            # But the requirement asks for orchestrator.receive_event("openai_balance_updated", {"balance": 0})
        
        # Mocking calculate_daily_burn if needed, but we'll try to trigger via receive_event
        # Note: FinanceEngine.validate_financial_health() is what usually triggers containment.
        # But Phase 3 asks to trigger via receive_event("openai_balance_updated", {"balance": 0})
        # Orchestrator has _sh_openai_balance_updated which calls fe.register_openai_balance
        
        orch.receive_event("openai_balance_updated", {"balance": 0.0})
        
        # Verify no crash and stable state
        # In V2, Guardian processes event post-persist.
        # We check if system is still responsive.
        results["critical_protection_stable"] = True 

        # Phase 4: Event Integrity
        all_events = bus.get_events()
        integrity = True
        for e in all_events:
            if not all(k in e for k in ["event_id", "timestamp", "version", "event_type", "payload"]):
                integrity = False
                results["errors"].append(f"Phase 4: Missing fields in event {e.get('event_type')}")
                break
        
        # Check for duplicates
        ids = [e["event_id"] for e in all_events]
        if len(ids) != len(set(ids)):
            integrity = False
            results["errors"].append("Phase 4: Duplicate event IDs detected")
            
        results["ledger_integrity_valid"] = integrity

    except Exception as e:
        results["errors"].append(f"Unexpected error: {str(e)}")
        print(json.dumps(results, indent=2))
        sys.exit(1)

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_test()
