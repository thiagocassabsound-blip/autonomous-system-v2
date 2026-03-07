"""
tests/test_legacy_bridge.py — Validation for C3A Transition Bridge
Tests observation of legacy writes without functional breakage.
"""
import os
import json
import unittest
import sys
from pathlib import Path

# -- path bootstrap -----------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.event_bus import EventBus
from core.state_machine import StateMachine
from core.global_state import GlobalState
from core.legacy_write_bridge import LOG_FILE, LEGACY_BRIDGE_ENABLED

class TestLegacyWriteBridge(unittest.TestCase):

    def setUp(self):
        # Clear log file before tests
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)

    def tearDown(self):
        # Clean up
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)

    def _read_logs(self):
        if not os.path.exists(LOG_FILE):
            return []
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_event_bus_interception(self):
        """Verify that EventBus.append_event is logged."""
        bus = EventBus()
        bus.append_event({"event_type": "legacy_test", "payload": {"data": 123}})
        
        logs = self._read_logs()
        self.assertTrue(len(logs) >= 1)
        self.assertEqual(logs[0]["write_type"], "event")
        self.assertEqual(logs[0]["details"]["event_type"], "legacy_test")
        # Origin should be this test module
        self.assertIn("test_legacy_bridge", logs[0]["origin"])

    def test_state_machine_interception(self):
        """Verify that StateMachine.transition is logged."""
        sm = StateMachine()
        bus = EventBus()
        # Mock transition
        sm.transition("p1", "Beta", "test", None, bus)
        
        logs = self._read_logs()
        # Might have 2 logs: 1 for state transition, 1 for the event emitted by SM
        state_logs = [l for l in logs if l["write_type"] == "state"]
        self.assertTrue(len(state_logs) >= 1)
        self.assertEqual(state_logs[0]["details"]["new_state"], "Beta")

    def test_global_state_interception(self):
        """Verify that GlobalState.update_state is logged."""
        gs = GlobalState()
        bus = EventBus()
        gs.request_state_update("CONTENÇÃO_FINANCEIRA", bus, "test", source="test", orchestrated=False)
        
        logs = self._read_logs()
        # Might have multiple logs due to cascading events
        gs_logs = [l for l in logs if l["write_type"] == "global_state"]
        self.assertTrue(len(gs_logs) >= 1)
        self.assertEqual(gs_logs[0]["details"]["new_value"], "CONTENÇÃO_FINANCEIRA")

    def test_no_breakage(self):
        """Verify that system works exactly as before."""
        bus = EventBus()
        formal = bus.append_event({"event_type": "formal_test", "payload": {}})
        self.assertIn("event_id", formal)
        self.assertEqual(formal["event_type"], "formal_test")

if __name__ == "__main__":
    unittest.main()
