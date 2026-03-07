import unittest
import threading
import time
import os
import json
import copy
from unittest.mock import MagicMock
from core.orchestrator import Orchestrator
from core.event_bus import EventBus
from core.state_manager import StateManager

class MockPersistence:
    def __init__(self, name="Generic"): 
        self.name = name
        self.data = []
    def load(self):
        # Always return a fresh copy to simulate disk reload
        return list(self.data) if isinstance(self.data, list) else copy.deepcopy(self.data)
    def save(self, data): 
        self.data = copy.deepcopy(data)
    def append(self, data):
        # Real append doesn't return anything
        if isinstance(self.data, list): self.data.append(copy.deepcopy(data))
        else: self.data = [copy.deepcopy(data)]

class TestTransactionalShield(unittest.TestCase):
    def setUp(self):
        # Ensure total isolation of persistence objects
        self.eb_persist = MockPersistence("EventBus")
        self.eb = EventBus(self.eb_persist)
        
        self.sm_persist = MockPersistence("StateManager")
        self.sm_persist.data = {"processed_events": []}
        self.sm = StateManager(self.sm_persist)
        
        self.orchestrator = Orchestrator(self.eb, self.sm)

    def test_event_idempotency_duplicate(self):
        payload = {"data": "test"}
        event_id = "uniq_123"
        res1 = self.orchestrator.receive_event("test_event", payload, event_id=event_id)
        self.assertEqual(res1.get("event_id"), event_id)
        res2 = self.orchestrator.receive_event("test_event", payload, event_id=event_id)
        self.assertEqual(res2.get("status"), "ignored")
        events = self.eb.get_events()
        test_events = [e for e in events if e["event_type"] == "test_event"]
        self.assertEqual(len(test_events), 1)

    def test_event_idempotency_persistence_restart(self):
        event_id = "persist_123"
        self.orchestrator.receive_event("persist_test", {"x": 1}, event_id=event_id)
        new_sm = StateManager(self.sm_persist)
        new_orchestrator = Orchestrator(self.eb, new_sm)
        res = new_orchestrator.receive_event("persist_test", {"x": 1}, event_id=event_id)
        self.assertEqual(res.get("status"), "ignored")

    def test_concurrent_event_append(self):
        num_threads = 10
        events_per_thread = 5
        total_expected = num_threads * events_per_thread
        
        def send_events():
            for i in range(events_per_thread):
                self.orchestrator.receive_event("concurrent_event", {"val": i})

        threads = [threading.Thread(target=send_events) for _ in range(num_threads)]
        for t in threads: t.start()
        for t in threads: t.join()
        
        all_events = self.eb.get_events()
        events = [e for e in all_events if e["event_type"] == "concurrent_event"]
        
        if len(events) != total_expected:
            print(f"\nDEBUG: Expected {total_expected}, got {len(events)}")
            for i, e in enumerate(all_events):
                print(f"  {i}: {e['event_type']} (ID: {e.get('event_id')})")
        
        self.assertEqual(len(events), total_expected)
        versions = sorted([e["version"] for e in events])
        self.assertEqual(len(set(versions)), total_expected)

    def test_atomic_failure_mid_execution(self):
        def failing_handler(orchestrator, state, payload):
            raise RuntimeError("Crashed during state update")
        self.orchestrator._STATE_HANDLERS["crash_event"] = failing_handler
        event_id = "crash_123"
        with self.assertRaises(RuntimeError):
            self.orchestrator.receive_event("crash_event", {"bad": True}, event_id=event_id)
        events = [e for e in self.eb.get_events() if e["event_type"] == "crash_event"]
        self.assertEqual(len(events), 0)
        processed = self.sm.get("processed_events")
        self.assertNotIn(event_id, processed)
        failed_alerts = [e for e in self.eb.get_events() if e["event_type"] == "event_processing_failed"]
        found = any(a.get("payload", {}).get("payload", {}).get("event_id") == event_id for a in failed_alerts)
        self.assertTrue(found)

if __name__ == "__main__":
    unittest.main()
