import sys
import os
import unittest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

# Add core to path
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.orchestrator import Orchestrator
from core.product_life_engine import ProductLifeEngine
from core.telemetry_engine import TelemetryEngine
from core.commercial_engine import CommercialEngine
from core.version_manager import VersionManager
from core.state_manager import StateManager
from core.global_state import GlobalState
from core.event_bus import EventBus
from core.finance_engine import FinanceEngine
from core.feedback_incentive_engine import FeedbackIncentiveEngine

class FullStructuralSimulation(unittest.TestCase):
    def setUp(self):
        # 1. Mock Persistence (Memory-only)
        self.mock_pers = MagicMock()
        self.mock_pers.load.return_value = {}
        
        # 2. Infrastructure & Orchestrator First
        self.bus = EventBus(MagicMock()) 
        self.sm  = StateManager(MagicMock())
        self.orchestrator = Orchestrator(self.bus, self.sm)
        
        # 3. Engines with correct signatures
        self.te = TelemetryEngine(snapshot_persistence=MagicMock(), accumulator_persistence=MagicMock())
        self.le = ProductLifeEngine(persistence=MagicMock(), state_machine=self.sm)
        self.ce = CommercialEngine(orchestrator=self.orchestrator, persistence=MagicMock())
        self.vm = VersionManager(persistence=MagicMock(), snapshot_store=MagicMock())
        self.fe = FinanceEngine(state_persistence=MagicMock(), projection_persistence=MagicMock())
        self.gs = GlobalState(orchestrator=self.orchestrator, persistence=MagicMock())
        self.fie = FeedbackIncentiveEngine(orchestrator=self.orchestrator, persistence=MagicMock())
        
        # 4. Register Services
        self.orchestrator.register_service("telemetry", self.te)
        self.orchestrator.register_service("product_life_engine", self.le)
        self.orchestrator.register_service("commercial_engine", self.ce)
        self.orchestrator.register_service("version_manager", self.vm)
        self.orchestrator.register_service("finance_engine", self.fe)
        self.orchestrator.register_service("global_state", self.gs)
        self.orchestrator.register_service("feedback_incentive_engine", self.fie)
        
        # 5. Global State Setup (Orchestrated)
        with patch("core.legacy_write_bridge.LegacyWriteBridge.intercept_global_state_write"):
            self.gs._enter_orchestrated_context()
            self.gs.request_state_update("NORMAL", orchestrated=True)
            self.gs._exit_orchestrated_context()
        
        # Patching Orchestrator methods to avoid real ledger file access if needed
        # but for simulation we want to see events.
        self.events = []
        def mock_emit(event_type, payload, product_id=None, source="system"):
            self.events.append({"type": event_type, "pid": product_id, "payload": payload})
            # Original functionality
            formal = {
                "event_id": "sim_" + str(len(self.events)),
                "event_type": event_type,
                "payload": payload,
                "product_id": product_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            return formal
        
        self.orchestrator.emit_event = MagicMock(side_effect=mock_emit)
        
        # Mock StateMachine transition for SM
        self.sm.transition = MagicMock(return_value={"success": True})

    def test_scenario_a_validated_sale_activation(self):
        """Draft -> Beta -> 1 Sale -> Ativo"""
        print("\n--- [SCENARIO A: Validated Sale] ---")
        pid = "prod_scenario_a"
        
        # 1. Setup Draft
        self.le.create_draft(
            self.orchestrator, "opp_a", 0.8, 0.7, 5.0, False, {"just": "ok"}, "v1", orchestrated=True
        )
        self.assertEqual(self.le._state[pid]["state"], "Draft")
        
        # 2. Start Beta
        self.orchestrator.receive_event("beta_approved_requested", {"product_id": pid}, product_id=pid)
        self.assertEqual(self.le._state[pid]["state"], "Beta")
        
        # 3. Simulate purchase_success
        self.orchestrator.receive_event("purchase_success", {
            "product_id": pid,
            "amount_total": 49.99,
            "stripe_session_id": "sess_a",
            "customer_email": "buyer@a.com"
        }, product_id=pid)
        
        # 4. Close Beta Cycle (7 days later)
        now = datetime.now(timezone.utc)
        self.le._state[pid]["beta_end"] = (now - timedelta(seconds=1)).isoformat()
        
        # 5. Snapshot & Consolidation
        # We need a cycle_id for the snapshot
        cycle_id = "cyc_a"
        self.te.close_cycle_snapshot(pid, cycle_id, self.orchestrator)
        
        # Verify Telemetry has refund_count=0
        latest_snap = self.te.get_latest_snapshot(pid)
        self.assertEqual(latest_snap["conversions"], 1)
        self.assertEqual(latest_snap["refund_count"], 0)
        
        # Consolidate
        self.orchestrator.receive_event("post_beta_consolidation_requested", {"product_id": pid}, product_id=pid)
        
        # FINAL VERIFICATION
        self.assertEqual(self.le._state[pid]["state"], "Ativo")
        self.assertEqual(self.le._state[pid]["classification"], "elegivel")
        
        # Check for constitutional correction event
        correction_events = [e for e in self.events if e["type"] == "constitutional_c5_life_authority_corrected"]
        self.assertTrue(len(correction_events) > 0)
        print("  [PASS] Scenario A: Activated with 1 sale.")

    def test_scenario_b_zero_sales_inactivation(self):
        """Draft -> Beta -> 0 Sales -> Inativo"""
        print("\n--- [SCENARIO B: Zero Sales] ---")
        pid = "prod_scenario_b"
        
        # 1. Setup Draft & Beta
        self.le.create_draft(self.orchestrator, "opp_b", 0.6, 0.6, 2.0, False, {"just": "ok"}, "v1", orchestrated=True)
        self.orchestrator.receive_event("beta_approved_requested", {"product_id": pid}, product_id=pid)
        
        # 2. Close Beta without sales
        now = datetime.now(timezone.utc)
        self.le._state[pid]["beta_end"] = (now - timedelta(seconds=1)).isoformat()
        
        # 3. Snapshot & Consolidation
        self.te.close_cycle_snapshot(pid, "cyc_b", self.orchestrator)
        self.orchestrator.receive_event("post_beta_consolidation_requested", {"product_id": pid}, product_id=pid)
        
        # FINAL VERIFICATION
        self.assertEqual(self.le._state[pid]["state"], "Inativo")
        self.assertEqual(self.le._state[pid]["classification"], "nao_elegivel")
        print("  [PASS] Scenario B: Inactivated with 0 sales.")

    def test_scenario_c_sale_plus_refund_inactivation(self):
        """Draft -> Beta -> 1 Sale + 1 Refund -> Inativo"""
        print("\n--- [SCENARIO C: Sale + Refund] ---")
        pid = "prod_scenario_c"
        
        # 1. Setup Draft & Beta
        self.le.create_draft(self.orchestrator, "opp_c", 0.9, 0.9, 8.0, True, {"just": "ok"}, "v1", orchestrated=True)
        self.orchestrator.receive_event("beta_approved_requested", {"product_id": pid}, product_id=pid)
        
        # 2. Simulate purchase_success
        self.orchestrator.receive_event("purchase_success", {
            "product_id": pid, "amount_total": 49.99, "stripe_session_id": "sess_c", "customer_email": "buyer@c.com"
        }, product_id=pid)
        
        # 3. Simulate refund_completed
        self.orchestrator.receive_event("refund_completed", {
            "product_id": pid, "user_id": "buyer@c.com", "amount": 49.99, "refund_id": "ref_c"
        }, product_id=pid)
        
        # 4. Close Beta Cycle
        now = datetime.now(timezone.utc)
        self.le._state[pid]["beta_end"] = (now - timedelta(seconds=1)).isoformat()
        
        # 5. Snapshot & Consolidation
        self.te.close_cycle_snapshot(pid, "cyc_c", self.orchestrator)
        
        # Verify Snapshot has net_conversions = 0
        latest_snap = self.te.get_latest_snapshot(pid)
        self.assertEqual(latest_snap["conversions"], 1)
        self.assertEqual(latest_snap["refund_count"], 1)
        
        self.orchestrator.receive_event("post_beta_consolidation_requested", {"product_id": pid}, product_id=pid)
        
        # FINAL VERIFICATION
        self.assertEqual(self.le._state[pid]["state"], "Inativo")
        self.assertEqual(self.le._state[pid]["classification"], "nao_elegivel")
        print("  [PASS] Scenario C: Inactivated with net zero sales.")

if __name__ == "__main__":
    unittest.main()
