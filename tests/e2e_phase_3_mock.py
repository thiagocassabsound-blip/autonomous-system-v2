import os
import sys
import json
import time
import hmac
import hashlib

from pathlib import Path

# Ensure V2 root is in path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.orchestrator import Orchestrator
from core.event_bus import EventBus
from core.state_manager import StateManager
from infrastructure.db import JsonFilePersistence

def generate_stripe_signature(payload, secret):
    timestamp = str(int(time.time()))
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={signature}"

def run_phase_3_mocked():
    print(">>> PHASE 3: PAYMENT CONFIRMATION FLOW (MOCKED) <<<")
    
    # Setup Minimal Registry
    bus = EventBus()
    state_pers = JsonFilePersistence("test_state.json")
    state_manager = StateManager(state_pers)
    orchestrator = Orchestrator(bus, state_manager)
    
    # Mock Commercial Engine to verify it's called
    class MockCommercialEngine:
        def __init__(self): self.called = False
        def confirm_payment(self, **kwargs):
            self.called = True
            print(f"MockCommercialEngine.confirm_payment called with: {kwargs}")
            return {"status": "success"}
    
    ce = MockCommercialEngine()
    orchestrator.register_service("commercial_engine", ce)
    
    # Dummy Global State (needed for containment check)
    class MockGlobalState:
        def get_state(self): return "NORMAL"
        def _enter_orchestrated_context(self): pass
        def _exit_orchestrated_context(self): pass
    orchestrator.register_service("global_state", MockGlobalState())

    # Webhook Payload
    payload_dict = {
        "id": "evt_test_123",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_999",
                "customer_details": {"email": "tester@example.com"},
                "amount_total": 5000,
                "metadata": {
                    "product_id": "v2_test_prod",
                    "snapshot_id": "snap_v2_mock"
                }
            }
        }
    }
    payload_str = json.dumps(payload_dict)
    
    # In a real Flask test, we'd use the app client. 
    # Here we test the logic in api/webhooks.py by manual invocation if possible,
    # or just simulating what the route does.
    
    print("Simulating Webhook -> Orchestrator routing...")
    # Logic from api/webhooks.py:
    # 1. Extract session
    event = payload_dict
    session = event['data']['object']
    customer_email = session.get('customer_details', {}).get('email')
    metadata = session.get('metadata', {})
    product_id = metadata.get('product_id')

    # 2. Call Orchestrator
    orchestrator.receive_event(
        event_type="payment_confirmed",
        payload={
            "session_id": session.get('id'),
            "customer_email": customer_email,
            "amount": session.get('amount_total', 0) / 100,
            "metadata": metadata,
            "event_id": event["id"] # Added for idempotency test later
        },
        product_id=product_id,
        source="stripe_webhook"
    )
    
    # 3. Validation
    # Check Ledger
    ledger = bus.get_event_log()
    payment_events = [e for e in ledger if e["event_type"] == "payment_confirmed"]
    
    print(f"Ledger Events: {len(payment_events)}")
    print(f"Commercial Engine Called: {ce.called}")
    
    # Check StateManager (idempotency index)
    processed = state_manager.get("processed_events", [])
    print(f"Processed Events in State: {processed}")
    
    success = len(payment_events) > 0 and ce.called and (event["id"] in processed)
    print(f"Phase 3 Result: {'SUCCESS' if success else 'FAILED'}")
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    run_phase_3_mocked()
