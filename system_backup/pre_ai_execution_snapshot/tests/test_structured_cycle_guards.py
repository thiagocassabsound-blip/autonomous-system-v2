import unittest
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime, timezone

from core.orchestrator import Orchestrator
from core.state_manager import StateManager
from core.event_bus import EventBus
from core.global_state import CONTENCAO_FINANCEIRA, NORMAL

class MockPersistence:
    def load(self): return {}
    def save(self, data): pass
    def append(self, data): pass

class TestStructuredCycleGuards(unittest.TestCase):
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
        
        self.orc.register_service("state_machine", self.sm)
        self.orc.register_service("global_state", self.gs)
        self.orc.register_service("macro_exposure_governance_engine", self.macro)
        self.orc.register_service("finance_engine", self.finance)
        self.orc.register_service("telemetry_engine", self.telemetry)
        
        self.gs.get_state.return_value = NORMAL
        self.sm.get_state.return_value = "Ativo"
        self.macro.validate_macro_exposure.return_value = {"allowed": True}
        
    def test_execute_structured_cycle_blocked_state(self):
        self.sm.get_state.return_value = "Beta"
        
        with patch.object(self.eb, 'append_event', wraps=self.eb.append_event) as mock_append:
            self.orc.execute_structured_cycle("p1")
            
            # Should emit market_cycle_blocked
            blocked_events = [e for e in self.eb.get_events() if e["event_type"] == "market_cycle_blocked"]
            self.assertEqual(len(blocked_events), 1)
            self.assertIn("expected 'Ativo'", blocked_events[0]["payload"]["reason"])
            
            # Should NOT be in active_cycles
            self.assertNotIn("p1", self.state.get("active_cycles", {}))

    def test_execute_structured_cycle_blocked_financial(self):
        self.gs.get_state.return_value = CONTENCAO_FINANCEIRA
        
        self.orc.execute_structured_cycle("p1")
        
        blocked_events = [e for e in self.eb.get_events() if e["event_type"] == "market_cycle_blocked"]
        self.assertEqual(len(blocked_events), 1)
        self.assertIn("CONTENÇÃO_FINANCEIRA", blocked_events[0]["payload"]["reason"])

    def test_execute_structured_cycle_blocked_paused(self):
        with self.orc._write_context():
            self.state.set("product:p1:paused", True)
            
        self.orc.execute_structured_cycle("p1")
        
        blocked_events = [e for e in self.eb.get_events() if e["event_type"] == "market_cycle_blocked"]
        self.assertEqual(len(blocked_events), 1)
        self.assertIn("manually paused", blocked_events[0]["payload"]["reason"])

    def test_execute_structured_cycle_blocked_running(self):
        with self.orc._write_context():
            self.state.set("active_cycles", {"p1": {"cycle_id": "existing"}})
            
        self.orc.execute_structured_cycle("p1")
        
        blocked_events = [e for e in self.eb.get_events() if e["event_type"] == "market_cycle_blocked"]
        self.assertEqual(len(blocked_events), 1)
        self.assertIn("already running", blocked_events[0]["payload"]["reason"])

    def test_execute_structured_cycle_blocked_macro(self):
        self.macro.validate_macro_exposure.return_value = {"allowed": False, "violations": ["limit exceeded"]}
        
        self.orc.execute_structured_cycle("p1")
        
        blocked_events = [e for e in self.eb.get_events() if e["event_type"] == "market_cycle_blocked"]
        self.assertEqual(len(blocked_events), 1)
        self.assertIn("Macro exposure validation failed", blocked_events[0]["payload"]["reason"])

    def test_execute_structured_cycle_success_init(self):
        self.telemetry.get_latest_snapshot.return_value = {"rpm": 1.5, "roas": 2.0}
        
        self.orc.execute_structured_cycle("p1")
        
        # Check event
        started_events = [e for e in self.eb.get_events() if e["event_type"] == "cycle_started"]
        self.assertEqual(len(started_events), 1)
        self.assertEqual(started_events[0]["payload"]["product_id"], "p1")
        self.assertEqual(started_events[0]["payload"]["current_phase"], 1)
        
        # Check StateManager
        active = self.state.get("active_cycles", {})
        self.assertIn("p1", active)
        self.assertEqual(active["p1"]["current_phase"], 1)
        self.assertEqual(active["p1"]["baseline_metrics"]["rpm"], 1.5)

if __name__ == "__main__":
    unittest.main()
