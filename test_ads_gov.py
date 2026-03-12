import os
import sys
import logging
from unittest.mock import MagicMock

# Absolute base path
BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from infra.traffic.engines.google_ads_engine import GoogleAdsEngine

class MockLogger:
    def info(self, msg, *args):
        print(f"INFO: {msg % args}")
    def warning(self, msg, *args):
        print(f"WARN: {msg % args}")
    def error(self, msg, *args):
        print(f"ERR: {msg % args}")

def test_ads_engine_governance():
    print("Testing GoogleAdsEngine Governance...")
    
    orchestrator = MagicMock()
    # Case 1: TRAFFIC_MODE = manual
    orchestrator.get_traffic_mode.return_value = "manual"
    
    engine = GoogleAdsEngine(orchestrator)
    engine.logger = MockLogger()
    
    payload = {"product_id": "test_prod", "landing_url": "http://test.com"}
    print("Running with TRAFFIC_MODE='manual'...")
    engine.handle_landing_ready_event(payload)
    
    # Case 2: TRAFFIC_MODE = ads
    print("\nRunning with TRAFFIC_MODE='ads'...")
    orchestrator.get_traffic_mode.return_value = "ads"
    # We expect initialization warning since we won't mock all credentials here, 
    # but we want to see if it proceeds past the governance block.
    engine.handle_landing_ready_event(payload)

if __name__ == "__main__":
    test_ads_engine_governance()
