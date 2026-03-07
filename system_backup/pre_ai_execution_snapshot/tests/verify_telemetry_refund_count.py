import sys
import os
import unittest
from unittest.mock import MagicMock

# Add core to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.telemetry_engine import TelemetryEngine

class TestTelemetryRefundCount(unittest.TestCase):
    def setUp(self):
        # Mock persistence
        self.snap_store = MagicMock()
        self.snap_store.load.return_value = []
        self.accum_pers = MagicMock()
        self.accum_pers.load.return_value = {}
        
        self.engine = TelemetryEngine(self.snap_store, self.accum_pers)
        self.orchestrator = MagicMock()

    def test_refund_count_logic(self):
        pid = "prod_test_refund"
        
        # 1. Record 2 Purchases ($100 each)
        self.engine.record_revenue(pid, 100.0)
        self.engine.record_revenue(pid, 100.0)
        
        # 2. Record 1 Refund ($50)
        self.engine.record_refund(pid, 50.0)
        
        # 3. Simulate cycle close
        snapshot = self.engine.close_cycle_snapshot(pid, "cycle_123", self.orchestrator)
        
        # 4. Verifications
        print(f"\nVerifying Snapshot for {pid}:")
        print(f"  Conversions:  {snapshot['conversions']} (Expected: 2)")
        print(f"  Refund Count: {snapshot['refund_count']} (Expected: 1)")
        print(f"  Gross Revenue: {snapshot['revenue_bruta']} (Expected: 200.0)")
        print(f"  Net Revenue:   {snapshot['revenue_liquida']} (Expected: 150.0)")
        print(f"  Refunds Total: {snapshot['refunds']} (Expected: 50.0)")
        
        self.assertEqual(snapshot['conversions'], 2)
        self.assertEqual(snapshot['refund_count'], 1)
        self.assertEqual(snapshot['revenue_bruta'], 200.0)
        self.assertEqual(snapshot['revenue_liquida'], 150.0)
        self.assertEqual(snapshot['refunds'], 50.0)
        
        # 5. Confirm KPI calculation (RPM)
        # We need visitors to calculate RPM
        # But even with 0 visitors, RPM should be 0.0 (safe division)
        print(f"  RPM: {snapshot['rpm']} (Expected: 0.0 with 0 visitors)")
        self.assertEqual(snapshot['rpm'], 0.0)

    def test_backward_compatibility(self):
        # Manually inject an old accumulator without refund_count
        self.engine._accumulators["old_prod"] = {
            "visitors": 10,
            "conversions": 1,
            "revenue_bruta": 50.0,
            "refunds": 0.0,
            "ad_spend": 5.0
        }
        
        # record_refund should initialize refund_count for this product
        self.engine.record_refund("old_prod", 10.0)
        
        acc = self.engine._acc("old_prod")
        self.assertEqual(acc["refund_count"], 1)
        self.assertEqual(acc["refunds"], 10.0)

if __name__ == "__main__":
    unittest.main()
