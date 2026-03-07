import unittest
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime, timezone

from core.orchestrator import Orchestrator
from core.state_manager import StateManager
from core.event_bus import EventBus
from core.global_state import NORMAL

class MockPersistence:
    def load(self): return {}
    def save(self, data): pass
    def append(self, data): pass

class TestStructuredCycleFull(unittest.TestCase):
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
        self.pe = MagicMock()
        
        self.orc.register_service("state_machine", self.sm)
        self.orc.register_service("global_state", self.gs)
        self.orc.register_service("macro_exposure_governance_engine", self.macro)
        self.orc.register_service("finance", self.finance) 
        self.orc.register_service("telemetry", self.telemetry) 
        self.orc.register_service("pricing", self.pe)
        
        self.gs.get_state.return_value = NORMAL
        self.sm.get_state.return_value = "Ativo"
        self.macro.validate_macro_exposure.return_value = {"allowed": True}
        
        # Default finance state (healthy)
        self.finance.get_state.return_value = {
            "stripe_current_balance": 10000.0,
            "openai_current_balance": 500.0
        }
        self.finance.calculate_daily_burn.return_value = 10.0
        self.finance.min_buffer_days = 30
        
        # Default baseline
        self.initial_baseline = {"rpm": 1.0, "roas": 1.5, "margin": 0.2, "snapshot_id": "snap_init"}
        self.telemetry.get_latest_snapshot.return_value = self.initial_baseline
        self.telemetry.get_official_cycle_metrics.return_value = self.initial_baseline

        with self.orc._write_context():
            self.state.set("cycle_history", [{"product_id": "p1", "id": "prev"}])
            self.state.set("active_cycles", {})

    def test_full_loop_sequence(self):
        """Verify all 7 phases execute in order."""
        self.orc.execute_structured_cycle("p1")
        
        events = self.eb.get_events()
        
        # Check phase starts
        phases_started = [e["payload"]["phase"] for e in events if e["event_type"] == "market_phase_started"]
        self.assertEqual(phases_started, [1, 2, 3, 4, 5, 6, 7])
        
        # Check completion
        completed = [e for e in events if e["event_type"] == "market_cycle_completed"]
        self.assertEqual(len(completed), 1)
        
        # Check history
        history = self.state.get("cycle_history")
        self.assertEqual(len(history), 2) # 1 prev + 1 new
        self.assertEqual(history[-1]["product_id"], "p1")

    def test_structural_decline_rollback(self):
        """Verify Phase 6 rollback on structural decline."""
        # Mock structural decline (RPM 0.4 < 1.0 * 0.5)
        def side_effect(*args, **kwargs):
            ph = args[2]
            if ph >= 4: return {"rpm": 0.4, "snapshot_id": "bad"}
            return self.initial_baseline
        
        self.telemetry.get_official_cycle_metrics.side_effect = side_effect
        
        self.orc.execute_structured_cycle("p1")
        
        # Verify rollbacks called
        self.pe.rollback_price.assert_called()
        
        events = self.eb.get_events()
        alerts = [e for e in events if e["event_type"] == "product_structural_decline_alert"]
        self.assertEqual(len(alerts), 1)

if __name__ == "__main__":
    unittest.main()
