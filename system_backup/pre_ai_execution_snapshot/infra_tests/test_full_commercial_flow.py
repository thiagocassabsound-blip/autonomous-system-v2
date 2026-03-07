import os
import sys
import json
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Ensure project root is in path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.event_bus import EventBus
from core.state_manager import StateManager
from core.orchestrator import Orchestrator
from core.commercial_engine import CommercialEngine
from core.webhook_listener import StripeWebhookHandler
from infrastructure.db import JsonFilePersistence, EventLogPersistence
from infrastructure.commercial_persistence import CommercialPersistence

class MockResendAdapter:
    def __init__(self):
        self.sent_emails = []

    def on_event(self, payload):
        self.sent_emails.append(payload)
        print(f"[MOCK RESEND] Email trigger detected for user: {payload.get('user_id')}")

def run_integration_test():
    # 1. Setup Scratch Persistence
    ledger_file = "ledger_test.jsonl"
    state_file = "state_test.json"
    comm_file = "comm_test.json"
    
    for f in [ledger_file, state_file, comm_file]:
        if os.path.exists(f): os.remove(f)

    try:
        # 2. Instantiate Components
        bus = EventBus(EventLogPersistence(ledger_file))
        state = StateManager(JsonFilePersistence(state_file))
        orc = Orchestrator(bus, state)
        
        # Bridge Ledger to Pub/Sub for the simulation
        original_append = bus.append_event
        def patched_append(event_dict):
            formal = original_append(event_dict)
            # Use bus.emit to bridge the Ledger event to Pub/Sub subscribers
            bus.emit(formal["event_type"], formal["payload"])
            return formal
        bus.append_event = patched_append

        ce = CommercialEngine(orc, CommercialPersistence(comm_file))
        orc.register_service("commercial_engine", ce)
        
        # 3. Setup Mock Resend Subscriber
        resend_mock = MockResendAdapter()
        bus.subscribe("access_token_issued", resend_mock.on_event)

        # 4. Prepare Webhook Handler
        handler = StripeWebhookHandler(orc, "whsec_test")

        # 5. Simulated Stripe Payload
        event_payload = {
            "id": "evt_test_integration_001",
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_001",
                    "amount_total": 10000, # 100.00
                    "customer_details": {"email": "thiagocassabsound@gmail.com"},
                    "metadata": {
                        "product_id": "audit_test_product_001",
                        "snapshot_id": "snap_test_001"
                    }
                }
            }
        }

        # 6. Bypass Signature & Execute
        print(">>> Starting Simulation: Stripe Webhook -> Orchestrator -> Resend")
        with patch("stripe.Webhook.construct_event") as mock_construct:
            # We wrap the payload in a mock event object that has .type and .data.object
            mock_event = MagicMock()
            mock_event.type = event_payload["type"]
            mock_event.data.object = MagicMock()
            # Manually map the simple dict to the MagicMock object attributes
            obj = event_payload["data"]["object"]
            mock_event.data.object.id = obj["id"]
            mock_event.data.object.amount_total = obj["amount_total"]
            mock_event.data.object.customer_details = obj["customer_details"]
            mock_event.data.object.get.side_effect = lambda k, d=None: obj["metadata"] if k == "metadata" else getattr(mock_event.data.object, k, d)
            
            mock_construct.return_value = mock_event
            
            handler.handle_event(b"raw_payload", "fake_sig")

        # 7. Validation
        ledger_updated = os.path.exists(ledger_file)
        # Check if events exist in ledger
        events = bus.get_events()
        event_types = [e["event_type"] for e in events]
        
        # CommercialEngine logic: purchase_success -> confirm_payment -> access_token_issued
        # Note: StripeWebhookHandler emits 'purchase_success'
        # Orchestrator calls _sh_purchase_success which calls ce.confirm_payment
        # confirm_payment emits 'payment_confirmed', 'license_created', 'access_token_issued'
        
        report = {
            "webhook_processed": "purchase_success" in event_types,
            "ledger_updated": ledger_updated,
            "state_updated": os.path.exists(comm_file),
            "email_triggered": len(resend_mock.sent_emails) > 0,
            "captured_events": event_types,
            "errors": [],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        print("\n" + json.dumps(report, indent=2))

    except Exception as e:
        print(json.dumps({
            "webhook_processed": False,
            "errors": [str(e)],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }, indent=2))
    finally:
        # Cleanup
        for f in [ledger_file, state_file, comm_file]:
            if os.path.exists(f): os.remove(f)

if __name__ == "__main__":
    run_integration_test()
