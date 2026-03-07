import unittest
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime, timezone

from core.orchestrator import Orchestrator
from core.state_manager import StateManager
from core.event_bus import EventBus
from core.global_state import NORMAL
from core.substitution_service import SubstitutionService

class MockPersistence:
    def load(self): return {}
    def save(self, data): pass
    def append(self, data): pass

class TestStructuredCyclePhaseLoop(unittest.TestCase):
    def setUp(self):
        self.eb = EventBus()
        self.state = StateManager(MockPersistence())
        self.orc = Orchestrator(self.eb, self.state)
        
        # Mock services
        self.sm = MagicMock()
        self.gs = MagicMock()
        self.macro = MagicMock()
        self.finance = MagicMock()
        self.telemetry = MagicMock()
        self.vm = MagicMock()
        
        self.orc.register_service("state_machine", self.sm)
        self.orc.register_service("global_state", self.gs)
        self.orc.register_service("macro_exposure_governance_engine", self.macro)
        self.orc.register_service("finance_engine", self.finance)
        self.orc.register_service("telemetry_engine", self.telemetry)
        self.orc.register_service("version_manager", self.vm)
        
        self.gs.get_state.return_value = NORMAL
        self.sm.get_state.return_value = "Ativo"
        self.macro.validate_macro_exposure.return_value = {"allowed": True}
        
        # Initial baseline metrics
        self.initial_baseline = {"rpm": 1.0, "roas": 1.5, "margin": 0.2}
        self.telemetry.get_latest_snapshot.return_value = self.initial_baseline
        
    def test_phase_loop_sequential_execution(self):
        # All phases approved
        with patch('core.substitution_service.SubstitutionService.evaluate') as mock_eval:
            mock_eval.return_value = {"approved": True, "reason": "better"}
            
            # Setup telemetry to return unique snapshots for each phase
            self.telemetry.get_official_cycle_metrics.side_effect = [
                {"snapshot_id": "s1", "rpm": 1.1, "roas": 1.6, "margin": 0.2, "phase_id": 1},
                {"snapshot_id": "s2", "rpm": 1.2, "roas": 1.7, "margin": 0.2, "phase_id": 2},
                {"snapshot_id": "s3", "rpm": 1.3, "roas": 1.8, "margin": 0.2, "phase_id": 3},
            ]
            
            self.orc.execute_structured_cycle("p1")
            
            # Check phase started/completed events
            events = self.eb.get_events()
            phases_started = [e for e in events if e["event_type"] == "market_phase_started"]
            phases_completed = [e for e in events if e["event_type"] == "market_phase_completed"]
            
            self.assertEqual(len(phases_started), 3)
            self.assertEqual(len(phases_completed), 3)
            
            for i, ph in enumerate([1, 2, 3]):
                self.assertEqual(phases_started[i]["payload"]["phase"], ph)
                self.assertEqual(phases_completed[i]["payload"]["phase"], ph)

    def test_phase_substitution_approved(self):
        # Phase 1 approved
        with patch('core.substitution_service.SubstitutionService.evaluate') as mock_eval:
            mock_eval.return_value = {"approved": True, "reason": "better"}
            
            candidate_metrics = {"snapshot_id": "snap_123", "rpm": 2.0, "roas": 3.0, "margin": 0.2, "phase_id": 1}
            self.telemetry.get_official_cycle_metrics.return_value = candidate_metrics
            
            # Mock phase 2 & 3 to be rejected to isolate phase 1
            mock_eval.side_effect = [
                {"approved": True, "reason": "better"},
                {"approved": False, "reason": "worse"},
                {"approved": False, "reason": "worse"}
            ]
            
            self.orc.execute_structured_cycle("p1")
            
            # Verify promotion call to VersionManager (via receive_event/service handler)
            self.vm.promote_candidate.assert_any_call(
                "p1",
                snapshot_id="snap_123",
                linked_price=None,
                orchestrator=self.orc,
                global_state=self.gs,
                financial_alert_active=False,
                orchestrated=True
            )
            
            # Verify version_promoted event
            promoted_events = [e for e in self.eb.get_events() if e["event_type"] == "version_promoted" and e["payload"]["phase"] == 1]
            self.assertEqual(len(promoted_events), 1)

    def test_phase_substitution_rejected(self):
        # Phase 1 rejected
        with patch('core.substitution_service.SubstitutionService.evaluate') as mock_eval:
            mock_eval.return_value = {"approved": False, "reason": "worse"}
            
            candidate_metrics = {"snapshot_id": "snap_failed", "rpm": 0.5, "roas": 1.0, "margin": 0.1, "phase_id": 1}
            self.telemetry.get_official_cycle_metrics.return_value = candidate_metrics
            
            self.orc.execute_structured_cycle("p1")
            
            # Verify rollback call to VersionManager
            self.vm.rollback_to_previous_baseline.assert_any_call(
                "p1",
                orchestrator=self.orc,
                orchestrated=True
            )
            
            # Verify version_rejected event
            rejected_events = [e for e in self.eb.get_events() if e["event_type"] == "version_rejected" and e["payload"]["phase"] == 1]
            self.assertEqual(len(rejected_events), 1)

    def test_no_parallel_phase_execution(self):
        # We test this by trying to start a cycle while one is active
        # Phase A Guard already does this, but we verify it here too.
        with self.orc._write_context():
            self.state.set("active_cycles", {"p1": {"cycle_id": "running"}})
            
        self.orc.execute_structured_cycle("p1")
        
        blocked_events = [e for e in self.eb.get_events() if e["event_type"] == "market_cycle_blocked"]
        self.assertEqual(len(blocked_events), 1)
        self.assertIn("already running", blocked_events[0]["payload"]["reason"])

if __name__ == "__main__":
    unittest.main()
