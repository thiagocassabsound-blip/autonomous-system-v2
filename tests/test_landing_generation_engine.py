"""
tests/test_landing_generation_engine.py — LandingGenerationEngine Validation Suite
"""
import os
import sys
import unittest
from pathlib import Path

# Add core to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from core.landing_generation_engine import LandingGenerationEngine

class MockOrchestrator:
    def __init__(self):
        self.emitted_events = []

    def emit_event(self, event_type, product_id, payload):
        self.emitted_events.append({
            "event_type": event_type,
            "product_id": product_id,
            "payload": payload
        })

class TestLandingGenerationEngine(unittest.TestCase):
    def setUp(self):
        self.output_dir = "test_landings"
        self.engine = LandingGenerationEngine(output_dir=self.output_dir)
        self.orchestrator = MockOrchestrator()
        self.product_id = "test-prod-123"
        self.statement = "Automate your daily reports in 60 seconds."
        self.price = 29.99

    def tearDown(self):
        # Cleanup test files
        p = Path(self.output_dir) / f"{self.product_id}.html"
        if p.exists():
            p.unlink()
        if Path(self.output_dir).exists():
            Path(self.output_dir).rmdir()

    def test_generate_landing_creates_file(self):
        file_path = self.engine.generate_landing(
            self.product_id, self.statement, self.price, self.orchestrator
        )
        self.assertTrue(Path(file_path).exists())

    def test_html_content(self):
        file_path = self.engine.generate_landing(
            self.product_id, self.statement, self.price, self.orchestrator
        )
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        self.assertIn(self.statement, content)
        self.assertIn(f'data-product-id="{self.product_id}"', content)
        self.assertIn(f"${self.price:.2f}", content)
        self.assertIn('href="{{CHECKOUT_URL}}"', content)

    def test_event_emission(self):
        self.engine.generate_landing(
            self.product_id, self.statement, self.price, self.orchestrator
        )
        
        self.assertEqual(len(self.orchestrator.emitted_events), 1)
        event = self.orchestrator.emitted_events[0]
        self.assertEqual(event["event_type"], "landing_created")
        self.assertEqual(event["product_id"], self.product_id)
        self.assertEqual(event["payload"]["price"], self.price)
        self.assertIn(self.product_id, event["payload"]["file_path"])

if __name__ == "__main__":
    unittest.main()
