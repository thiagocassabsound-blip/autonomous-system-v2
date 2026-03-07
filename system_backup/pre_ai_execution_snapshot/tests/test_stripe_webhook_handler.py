"""
tests/test_stripe_webhook_handler.py — Stripe Webhook Handler Validation Suite
"""
import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Ensure core is in path regardless of from where we run it
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import stripe
from core.webhook_listener import StripeWebhookHandler

class MockOrchestrator:
    def __init__(self):
        self.received_events = []

    def receive_event(self, event_type, payload, product_id):
        self.received_events.append({
            "event_type": event_type,
            "payload": payload,
            "product_id": product_id
        })

class TestStripeWebhookHandler(unittest.TestCase):
    def setUp(self):
        self.orchestrator = MockOrchestrator()
        self.webhook_secret = "whsec_test_secret"
        self.handler = StripeWebhookHandler(self.orchestrator, self.webhook_secret)

    @patch("stripe.Webhook.construct_event")
    def test_invalid_signature_raises_exception(self, mock_construct):
        mock_construct.side_effect = stripe.error.SignatureVerificationError("Invalid sig", "header")
        
        with self.assertRaises(stripe.error.SignatureVerificationError):
            self.handler.handle_event(b"payload", "invalid_header")

    @patch("stripe.Webhook.construct_event")
    def test_unauthorized_event_ignored(self, mock_construct):
        mock_event = MagicMock()
        mock_event.type = "customer.created"
        mock_construct.return_value = mock_event
        
        self.handler.handle_event(b"payload", "header")
        self.assertEqual(len(self.orchestrator.received_events), 0)

    @patch("stripe.Webhook.construct_event")
    def test_checkout_session_completed_success(self, mock_construct):
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"
        
        # Session object
        session = MagicMock()
        session.id = "cs_test_123"
        session.amount_total = 2999
        session.customer_details = {"email": "test@example.com"}
        # Mock metadata
        meta = {"product_id": "prod_1", "snapshot_id": "snap_A"}
        session.get.side_effect = lambda k, d=None: meta if k == "metadata" else getattr(session, k, d)
        
        mock_event.data.object = session
        mock_construct.return_value = mock_event
        
        self.handler.handle_event(b"payload", "header")
        
        self.assertEqual(len(self.orchestrator.received_events), 1)
        ev = self.orchestrator.received_events[0]
        self.assertEqual(ev["event_type"], "purchase_success")
        self.assertEqual(ev["product_id"], "prod_1")
        self.assertEqual(ev["payload"]["snapshot_id"], "snap_A")
        self.assertEqual(ev["payload"]["amount_total"], 29.99)
        self.assertEqual(ev["payload"]["customer_email"], "test@example.com")

    @patch("stripe.Webhook.construct_event")
    def test_checkout_missing_metadata_ignored(self, mock_construct):
        mock_event = MagicMock()
        mock_event.type = "checkout.session.completed"
        
        session = MagicMock()
        session.get.return_value = {} # No metadata
        
        mock_event.data.object = session
        mock_construct.return_value = mock_event
        
        self.handler.handle_event(b"payload", "header")
        self.assertEqual(len(self.orchestrator.received_events), 0)

    @patch("stripe.Webhook.construct_event")
    def test_charge_refunded_success(self, mock_construct):
        mock_event = MagicMock()
        mock_event.type = "charge.refunded"
        
        charge = MagicMock()
        charge.id = "ch_test_refund"
        charge.amount_refunded = 1500
        # Mock metadata
        meta = {"product_id": "prod_1", "snapshot_id": "snap_A"}
        charge.get.side_effect = lambda k, d=None: meta if k == "metadata" else getattr(charge, k, d)
        
        mock_event.data.object = charge
        mock_construct.return_value = mock_event
        
        self.handler.handle_event(b"payload", "header")
        
        self.assertEqual(len(self.orchestrator.received_events), 1)
        ev = self.orchestrator.received_events[0]
        self.assertEqual(ev["event_type"], "refund_completed")
        self.assertEqual(ev["product_id"], "prod_1")
        self.assertEqual(ev["payload"]["snapshot_id"], "snap_A")
        self.assertEqual(ev["payload"]["amount"], 15.0)

    def test_no_direct_event_bus_access(self):
        # Static check or just verifying logic: 
        # The hander only has a reference to orchestrator, no EventBus import/access.
        # Use absolute path to avoid CWD issues
        target = os.path.join(ROOT, "core", "webhook_listener.py")
        with open(target, "r") as f:
            content = f.read()
        self.assertNotIn("EventBus", content)
        self.assertNotIn("append_event", content)

if __name__ == "__main__":
    unittest.main()
