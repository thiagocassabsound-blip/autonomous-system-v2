import os
import sys
import json
import time

from pathlib import Path

# Ensure V2 root is in path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.orchestrator import Orchestrator
from core.event_bus import EventBus
from core.state_manager import StateManager
from infrastructure.db import JsonFilePersistence

def run_e2e_mocked_suite():
    print(">>> V2 STRIPE E2E MOCKED VALIDATION SUITE <<<")
    
    # 1. SETUP
    bus = EventBus()
    state_pers = JsonFilePersistence("test_state_e2e.json")
    state_manager = StateManager(state_pers)
    orchestrator = Orchestrator(bus, state_manager)
    
    class MockService:
        def __init__(self, name):
            self.name = name
            self.calls = []
        def _enter_orchestrated_context(self): pass
        def _exit_orchestrated_context(self): pass
        def get_state(self): return "NORMAL"
        def record_revenue(self, *args, **kwargs): self.calls.append(("record_revenue", args, kwargs))
        def confirm_payment(self, *args, **kwargs): self.calls.append(("confirm_payment", args, kwargs))
        def complete_refund(self, *args, **kwargs): self.calls.append(("complete_refund", args, kwargs))
        def record_refund(self, *args, **kwargs): self.calls.append(("record_refund", args, kwargs))

    ce = MockService("commercial_engine")
    tm = MockService("telemetry")
    gs = MockService("global_state")
    
    orchestrator.register_service("commercial_engine", ce)
    orchestrator.register_service("telemetry", tm)
    orchestrator.register_service("global_state", gs)

    # -----------------------------------------------------------------------
    # PHASE 3: PAYMENT CONFIRMATION
    # -----------------------------------------------------------------------
    print("\n--- PHASE 3: PAYMENT CONFIRMATION ---")
    event_id = "evt_payment_001"
    orchestrator.receive_event(
        event_type="payment_confirmed",
        payload={
            "session_id": "cs_test_1",
            "customer_email": "user@test.com",
            "amount": 10.0,
            "metadata": {"product_id": "prod_v2"},
            "event_id": event_id
        },
        product_id="prod_v2",
        source="stripe_webhook"
    )
    
    ledger = bus.get_events()
    pay_ev = [e for e in ledger if e["event_type"] == "payment_confirmed"]
    processed = state_manager.get("processed_events", [])
    
    p3_ok = len(pay_ev) > 0 and ce.calls[0][0] == "confirm_payment" and event_id in processed
    print(f"Payment Ledger OK: {len(pay_ev) > 0}")
    print(f"Commercial Engine OK: {ce.calls[0][0] == 'confirm_payment' if ce.calls else False}")
    print(f"Idempotency Index OK: {event_id in processed}")
    
    # -----------------------------------------------------------------------
    # PHASE 4: REFUND FLOW
    # -----------------------------------------------------------------------
    print("\n--- PHASE 4: REFUND FLOW ---")
    refund_event_id = "evt_refund_001"
    orchestrator.receive_event(
        event_type="refund_completed",
        payload={
            "user_id": "user@test.com",
            "amount": 10.0,
            "product_id": "prod_v2",
            "event_id": refund_event_id
        },
        product_id="prod_v2",
        source="stripe_webhook"
    )
    
    refund_ev = [e for e in bus.get_events() if e["event_type"] == "refund_completed"]
    # Should call commercial_engine.complete_refund and telemetry.record_refund
    ce_refund_called = any(c[0] == "complete_refund" for c in ce.calls)
    tm_refund_called = any(c[0] == "record_refund" for c in tm.calls)
    
    p4_ok = len(refund_ev) > 0 and ce_refund_called and tm_refund_called
    print(f"Refund Ledger OK: {len(refund_ev) > 0}")
    print(f"Commercial Engine Revoke OK: {ce_refund_called}")
    print(f"Telemetry Record OK: {tm_refund_called}")

    # -----------------------------------------------------------------------
    # PHASE 5: DUPLICATE DEFENSE
    # -----------------------------------------------------------------------
    print("\n--- PHASE 5: DUPLICATE DEFENSE ---")
    initial_ledger_count = len(bus.get_events())
    orchestrator.receive_event(
        event_type="payment_confirmed",
        payload={"event_id": event_id}, # DUPLICATE ID
        product_id="prod_v2",
        source="stripe_webhook"
    )
    
    final_ledger_count = len(bus.get_events())
    # Orchestrator appends 'event_duplicate_ignored' to ledger but DOES NOT call handlers
    dup_ev = [e for e in bus.get_events() if e["event_type"] == "event_duplicate_ignored"]
    
    # Verify hander wasn't called again (ce.calls should still have only 1 payment confirmed)
    ce_pay_calls = [c for c in ce.calls if c[0] == "confirm_payment"]
    
    p5_ok = len(dup_ev) > 0 and len(ce_pay_calls) == 1
    print(f"Duplicate Event Detected OK: {len(dup_ev) > 0}")
    print(f"Handler Idempotency OK: {len(ce_pay_calls) == 1}")

    # FINAL SUMMARY
    print("\n>>> FINAL RESULTS <<<")
    print(f"Phase 3: {'PASS' if p3_ok else 'FAIL'}")
    print(f"Phase 4: {'PASS' if p4_ok else 'FAIL'}")
    print(f"Phase 5: {'PASS' if p5_ok else 'FAIL'}")
    
    if not (p3_ok and p4_ok and p5_ok):
        sys.exit(1)

if __name__ == "__main__":
    run_e2e_mocked_suite()
