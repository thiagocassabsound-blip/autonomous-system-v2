"""
tests/test_global_state_encapsulation.py — Verification for C3B-1.
Verifies that:
1. Orchestrated updates (via set_global_state) work without legacy warnings.
2. Direct updates (via request_state_update with orchestrated=False) trigger legacy warnings.
3. LegacyWriteBridge correctly captures both.
4. Core logic of state change remains intact.
"""
import unittest
import json
import os
from datetime import datetime, timezone
from core.global_state import GlobalState, NORMAL, ALERTA_FINANCEIRO, VALID_GLOBAL_STATES
from core.event_bus import EventBus
from core.orchestrator import Orchestrator
from core.legacy_write_bridge import LegacyWriteBridge

class MemFile:
    def load(self): return {}
    def save(self, data): pass

class TestGlobalStateEncapsulation(unittest.TestCase):
    def setUp(self):
        self.log_file = "logs/legacy_write_monitor.jsonl"
        if os.path.exists(self.log_file):
            os.remove(self.log_file)
        
        self.bus = EventBus()
        self.gs = GlobalState(MemFile())
        
        # Simple mock for StateManager
        class MockSM:
            def log_transition(self, *args, **kwargs): pass
        
        self.orc = Orchestrator(self.bus, MockSM())
        self.orc.register_service("global_state", self.gs)

    def _read_logs(self):
        if not os.path.exists(self.log_file):
            return []
        with open(self.log_file, "r", encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_orchestrated_update(self):
        """Orchestrator should be able to update state without legacy_warning flag."""
        initial_logs = self._read_logs()
        
        self.orc.set_global_state(ALERTA_FINANCEIRO, reason="Testing orchestration")
        
        self.assertEqual(self.gs.get_state(), ALERTA_FINANCEIRO)
        
        logs = self._read_logs()
        self.assertGreater(len(logs), len(initial_logs))
        
        # Find the global_state log
        gs_logs = [l for l in logs if l.get("write_type") == "global_state"]
        self.assertTrue(any(gs_logs))
        
        last_gs_log = gs_logs[-1]
        self.assertEqual(last_gs_log["origin"], "core.orchestrator")
        self.assertNotIn("legacy_warning", last_gs_log)

    def test_legacy_update(self):
        """Direct call to request_state_update(orchestrated=False) should trigger legacy warning."""
        self.gs.request_state_update(NORMAL, self.bus, "Back to normal", source="legacy_tester", orchestrated=False)
        
        logs = self._read_logs()
        gs_logs = [l for l in logs if l.get("write_type") == "global_state"]
        self.assertTrue(any(gs_logs))
        
        last_gs_log = gs_logs[-1]
        self.assertEqual(last_gs_log["legacy_warning"], True)
        self.assertEqual(last_gs_log["severity"], "GLOBAL_STATE_DIRECT_WRITE")

    def test_invalid_state_remains_blocked(self):
        """Sanity check: invalid states should still raise ValueError."""
        with self.assertRaises(ValueError):
            self.gs.request_state_update("INVALID_STATE", self.bus)

if __name__ == "__main__":
    unittest.main()
