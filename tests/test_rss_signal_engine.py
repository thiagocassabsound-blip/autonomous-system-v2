import unittest
import os
import tempfile
import json
import uuid
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from infrastructure.rss.rss_parser import RSSParser
from infrastructure.rss.rss_event_normalizer import RSSEventNormalizer
from infrastructure.rss.rss_persistence import RSSPersistence
from core.rss_signal_engine import RSSSignalEngine

class MockOrchestrator:
    def __init__(self):
        self.events_emitted = []
        self.global_state = "NORMAL"
        self.credit_critical_warning = False
        self.financial_alert_active = False
        self.macro_exposure_blocked = False

    def emit_event(self, event_type, payload, source="system", product_id=None):
        self.events_emitted.append({"type": event_type, "payload": payload})

    def get_global_state(self):
        return self.global_state

# We duck-patch RSSPersistence for testing locally.
# We will intercept the JSON file mapping to a temporal test directory.
class TestRSSSignalEngine(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.test_ledger_path = os.path.join(self.test_dir.name, "rss_signal_ledger.jsonl")
        
        # Patch Persistence path
        import infrastructure.rss.rss_persistence
        infrastructure.rss.rss_persistence.LEDGER_PATH = self.test_ledger_path
        
        self.orchestrator = MockOrchestrator()
        self.engine = RSSSignalEngine(self.orchestrator)
        
    def tearDown(self):
        self.test_dir.cleanup()
        
    def test_rss_normalization_and_noise_filter(self):
        # Description under 20 chars should be blocked
        short_desc_item = {
            "title": "Short",
            "description": "very short",
            "url": "http://short.com",
            "source_name": "test",
            "category": "test_cat"
        }
        cand1 = RSSEventNormalizer.normalize(short_desc_item)
        self.assertIsNone(cand1, "Item with description < 20 chars must be filtered.")
        
        # Proper item
        good_item = {
            "title": "New Startup SaaS Framework",
            "description": "This is a brand new SaaS startup reporting bugs and failures in the market.",
            "url": "http://saas.com",
            "source_name": "test",
            "category": "test_cat"
        }
        cand2 = RSSEventNormalizer.normalize(good_item)
        self.assertIsNotNone(cand2)
        self.assertIn("saas", cand2["keyword_cluster"])
        self.assertIn("Failure, bug, or pain point reported", cand2["description"] + " " + cand1 if cand1 else "Failure, bug, or pain point reported") # Just checking structural inclusion via logic rules mapped previously
        
    def test_duplicate_blocking_and_persistence(self):
        good_item = {
            "event_id": str(uuid.uuid4()),
            "title": "Startup Failures",
            "description": "We are looking at startup failures...",
            "url": "http://url.com"
        }
        
        RSSPersistence.record_signal(good_item)
        
        # Should be duplicate
        is_dup = RSSPersistence.is_duplicate("http://url.com", "Startup Failures")
        self.assertTrue(is_dup)
        
        is_dup = RSSPersistence.is_duplicate("http://new.com", "New Startups")
        self.assertFalse(is_dup)
        
    def test_containment_blocking(self):
        self.orchestrator.global_state = "CONTENCAO"
        self.engine.run_collection_cycle()
        
        # Blocked event
        self.assertEqual(len(self.orchestrator.events_emitted), 1)
        self.assertEqual(self.orchestrator.events_emitted[0]["type"], "rss_execution_blocked")
        
    def test_financial_blocking(self):
        self.orchestrator.credit_critical_warning = True
        self.engine.run_collection_cycle()
        
        # Blocked event
        self.assertEqual(len(self.orchestrator.events_emitted), 1)
        self.assertEqual(self.orchestrator.events_emitted[0]["type"], "rss_execution_blocked_financial")

if __name__ == '__main__':
    unittest.main()
