import unittest
from core.event_bus import EventBus
from core.global_state import GlobalState, NORMAL, ALERTA_FINANCEIRO, STRICT_MODE as GS_STRICT
from core.state_machine import StateMachine, STRICT_MODE as SM_STRICT
from core.event_bus import STRICT_MODE as EB_STRICT
from core.orchestrator import Orchestrator
from core.state_manager import StateManager

class MockPersistence:
    def load(self): return {}
    def save(self, data): pass
    def append(self, data): pass

class TestStrictModeLock(unittest.TestCase):
    def test_strict_mode_constants_active(self):
        self.assertTrue(EB_STRICT)
        self.assertTrue(GS_STRICT)
        self.assertTrue(SM_STRICT)

    def test_strict_mode_event_bus_violation(self):
        eb = EventBus()
        # Direct append should fail
        with self.assertRaises(RuntimeError) as cm:
            eb.append_event({"event_type": "test_violation", "payload": {}})
        self.assertIn("STRICT_MODE_VIOLATION", str(cm.exception))

    def test_strict_mode_global_state_violation(self):
        eb = EventBus()
        sm = StateMachine()
        state = StateManager(MockPersistence())
        orc = Orchestrator(eb, state)
        gs = GlobalState(orc)
        # Direct internal update should fail
        with self.assertRaises(RuntimeError) as cm:
            gs._update_state_internal(ALERTA_FINANCEIRO, reason="test violation")
        self.assertIn("STRICT_MODE_VIOLATION", str(cm.exception))

    def test_strict_mode_state_machine_violation(self):
        eb = EventBus()
        sm = StateMachine()
        state = StateManager(MockPersistence())
        orc = Orchestrator(eb, state)
        # Direct transition should fail
        with self.assertRaises(RuntimeError) as cm:
            sm.transition("p1", "Beta", "test violation", None, orchestrator=orc)
        self.assertIn("STRICT_MODE_VIOLATION", str(cm.exception))

    def test_orchestrator_authorized_event_emission(self):
        eb = EventBus()
        state = StateManager(MockPersistence())
        orc = Orchestrator(eb, state)
        
        # Orchestrator.emit_event should succeed because it manages context
        formal = orc.emit_event("test_authorized", {"val": 100}, source="test_suite")
        self.assertEqual(formal["event_type"], "test_authorized")
        self.assertEqual(len(eb.get_events()), 1)

    def test_orchestrator_authorized_global_state(self):
        eb = EventBus()
        state = StateManager(MockPersistence())
        orc = Orchestrator(eb, state)
        gs = GlobalState(orc)
        orc.register_service("global_state", gs)
        
        # Orchestrator.set_global_state should succeed
        orc.set_global_state(ALERTA_FINANCEIRO, reason="testing authorized")
        self.assertEqual(gs.get_state(), ALERTA_FINANCEIRO)

    def test_orchestrator_authorized_transition_via_receive_event(self):
        eb = EventBus()
        sm = StateMachine()
        state = StateManager(MockPersistence())
        orc = Orchestrator(eb, state)
        orc.register_service("state_machine", sm)
        
        # We define a dummy handler that performs a transition
        def dummy_handler(o, state, payload):
            sm.transition(payload["pid"], "Beta", "authorized test", None, orchestrator=o)
        
        # Register as state handler
        orc._STATE_HANDLERS["test_trigger_transition"] = dummy_handler
        
        # This should succeed because receive_event wraps handlers in SM context
        orc.receive_event("test_trigger_transition", {"pid": "prod_123"})
        
        self.assertEqual(sm.get_state("prod_123"), "Beta")

if __name__ == "__main__":
    unittest.main()
