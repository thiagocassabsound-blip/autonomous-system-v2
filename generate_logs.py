"""
generate_logs.py — Script to generate legacy write logs for final report.
Calls EventBus, StateMachine, and GlobalState to trigger the birdge.
"""
import sys
import os
from pathlib import Path

# Add root to sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.event_bus import EventBus
from core.state_machine import StateMachine
from core.global_state import GlobalState

def run():
    print(">>> Generating Legacy Writes...")
    bus = EventBus()
    sm = StateMachine()
    gs = GlobalState()

    # 1. Event Write
    print("- Triggering Event Write")
    bus.append_event({"event_type": "obs_report_test_event", "payload": {"status": "ok"}})

    # 2. State Write
    print("- Triggering State Write")
    sm.transition("product_abc", "Beta", "observation test", None, bus)

    # 3. Global State Write
    print("- Triggering Global State Write")
    gs.request_state_update("CONTENÇÃO_FINANCEIRA", bus, "observation test", source="simulation", orchestrated=False)

    print(">>> Generation Complete.")

if __name__ == "__main__":
    run()
