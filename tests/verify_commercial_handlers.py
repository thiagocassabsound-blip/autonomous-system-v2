import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# Add core to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.orchestrator import Orchestrator

class TestCommercialHandlersRouting(unittest.TestCase):
    def setUp(self):
        self.eb = MagicMock()
        self.sm = MagicMock()
        self.orchestrator = Orchestrator(self.eb, self.sm)
        
        # Mock services
        self.tm = MagicMock()
        self.ce = MagicMock()
        self.fie = MagicMock()
        
        self.orchestrator.register_service("telemetry", self.tm)
        self.orchestrator.register_service("commercial_engine", self.ce)
        self.orchestrator.register_service("feedback_incentive_engine", self.fie)
        
        # Bypass pre-flight and other guards for simple routing test
        self.orchestrator._assert_financial_clearance = MagicMock()
        self.sm.get.return_value = [] # processed_events

    def test_purchase_success_routing(self):
        payload = {
            "product_id": "prod_123",
            "amount_total": 49.99,
            "stripe_session_id": "session_abc",
            "customer_email": "user@test.com"
        }
        
        self.orchestrator.receive_event("purchase_success", payload, product_id="prod_123")
        
        # Verify Telemetry
        self.tm.record_revenue.assert_called_once_with("prod_123", 49.99)
        
        # Verify Commercial
        self.ce.confirm_payment.assert_called_once_with(
            user_id="user@test.com",
            product_id="prod_123",
            payment_id="session_abc",
            source="system"
        )

    def test_refund_completed_routing(self):
        payload = {
            "user_id": "user@test.com",
            "product_id": "prod_123",
            "amount": 49.99,
            "refund_id": "ref_xyz"
        }
        
        self.orchestrator.receive_event("refund_completed", payload, product_id="prod_123")
        
        # Verify Commercial
        self.ce.complete_refund.assert_called_once_with(user_id="user@test.com")
        
        # Verify Telemetry
        self.tm.record_refund.assert_called_once_with("prod_123", 49.99)
        
        # Verify Feedback
        self.fie.revoke_lifetime_upgrade.assert_called_once_with(
            user_id="user@test.com",
            product_id="prod_123",
            reason="refund_completed",
            event_bus=self.eb
        )

if __name__ == "__main__":
    unittest.main()
