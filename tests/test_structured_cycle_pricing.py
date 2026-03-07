import unittest
from unittest.mock import MagicMock, patch
import uuid
from datetime import datetime, timezone

from core.orchestrator import Orchestrator
from core.state_manager import StateManager
from core.event_bus import EventBus
from core.global_state import NORMAL, CONTENCAO_FINANCEIRA

class MockPersistence:
    def load(self): return {}
    def save(self, data): pass
    def append(self, data): pass

class TestStructuredCyclePricing(unittest.TestCase):
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
        
        # Default baseline from telemetry
        self.initial_baseline = {"rpm": 1.0, "roas": 1.5, "margin": 0.2, "snapshot_id": "snap_init"}
        self.telemetry.get_latest_snapshot.return_value = self.initial_baseline
        self.telemetry.get_official_cycle_metrics.return_value = self.initial_baseline

        with self.orc._write_context():
            self.state.set("cycle_history", [{"product_id": "p1", "id": "prev"}])
            self.state.set("active_cycles", {})

    def test_pricing_blocked_first_cycle(self):
        with self.orc._write_context():
            self.state.set("cycle_history", [])
        self.orc.execute_structured_cycle("p1")
        events = self.eb.get_events()
        blocked = [e for e in events if e["event_type"] == "pricing_test_blocked" and "First cycle" in e["payload"]["reason"]]
        self.assertEqual(len(blocked), 1)

    def test_pricing_blocked_under_financial_alert(self):
        self.finance.get_state.return_value = {
            "stripe_current_balance": 50.0,
            "openai_current_balance": 50.0
        }
        self.finance.calculate_daily_burn.return_value = 10.0
        self.orc.execute_structured_cycle("p1")
        events = self.eb.get_events()
        blocked = [e for e in events if e["event_type"] == "pricing_test_blocked" and "Financial alert" in e["payload"]["reason"]]
        self.assertEqual(len(blocked), 1)

    def test_offensive_pricing_success(self):
        def side_effect(*args, **kwargs):
            ph = args[2]
            if ph == 4: return {"rpm": 1.1, "snapshot_id": "snap4"}
            return self.initial_baseline
        self.telemetry.get_official_cycle_metrics.side_effect = side_effect
        self.orc.execute_structured_cycle("p1")
        self.pe.apply_offensive_increase.assert_called_once()
        events = self.eb.get_events()
        validated = [e for e in events if e["event_type"] == "price_increase_validated"]
        self.assertEqual(len(validated), 1)

    def test_offensive_pricing_rollback(self):
        def side_effect(*args, **kwargs):
            ph = args[2]
            if ph == 4: return {"rpm": 0.8, "snapshot_id": "snap4"}
            return self.initial_baseline
        self.telemetry.get_official_cycle_metrics.side_effect = side_effect
        self.orc.execute_structured_cycle("p1")
        self.pe.rollback_price.assert_called_once()
        events = self.eb.get_events()
        reverted = [e for e in events if e["event_type"] == "price_increase_reverted"]
        self.assertEqual(len(reverted), 1)

    def test_defensive_requires_prior_increase(self):
        def side_effect(*args, **kwargs):
            ph = args[2]
            if ph == 3:
                # Hack state so Phase 4 logic sees prior success
                with self.orc._write_context():
                    ac = self.state.get("active_cycles")
                    ac["p1"]["offensive_increases_validated"] = 1
                    ac["p1"]["consecutive_price_increases"] = 2
                    self.state.set("active_cycles", ac)
                return self.initial_baseline
            if ph == 4:
                return {"rpm": 1.2, "snapshot_id": "snap4"}
            return self.initial_baseline

        self.telemetry.get_official_cycle_metrics.side_effect = side_effect
        self.orc.execute_structured_cycle("p1")
        self.pe.apply_defensive_reduction.assert_called_once()
        events = self.eb.get_events()
        validated = [e for e in events if e["event_type"] == "price_defense_validated"]
        self.assertEqual(len(validated), 1)

    def test_price_never_below_original_base(self):
        def side_effect(*args, **kwargs):
            ph = args[2]
            if ph == 3:
                with self.orc._write_context():
                    ac = self.state.get("active_cycles")
                    ac["p1"]["offensive_increases_validated"] = 1
                    ac["p1"]["consecutive_price_increases"] = 2
                    self.state.set("active_cycles", ac)
                return self.initial_baseline
            if ph == 4:
                return {"rpm": 0.8, "snapshot_id": "snap4"}
            return self.initial_baseline

        self.telemetry.get_official_cycle_metrics.side_effect = side_effect
        self.orc.execute_structured_cycle("p1")
        self.pe.rollback_price.assert_called_once()
        events = self.eb.get_events()
        reverted = [e for e in events if e["event_type"] == "price_defense_reverted"]
        self.assertEqual(len(reverted), 1)

if __name__ == "__main__":
    unittest.main()
