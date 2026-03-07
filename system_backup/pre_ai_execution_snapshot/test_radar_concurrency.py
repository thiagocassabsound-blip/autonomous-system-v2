import os
import sys
import time
from infrastructure.logger import get_logger
from radar.radar_engine import run_radar_cycle
from core.strategic_opportunity_engine import StrategicOpportunityEngine

logger = get_logger("RadarValidationTest")

class MockOrchestrator:
    def receive_event(self, event):
        logger.info(f"[MockOrchestrator] Received event: {event.get('event_type')} -> {event.get('reason')}")

def test_full_radar_cycles():
    orchestrator = MockOrchestrator()
    class MockPersistence:
        def save(self, *args, **kwargs): pass
        def load_all(self): return []
    
    strategic_engine = StrategicOpportunityEngine(orchestrator=orchestrator, persistence=MockPersistence())
    
    keywords = [
        ("AI code assistant", "saas"),
        ("productivity automation", "saas"),
        ("customer support software", "saas")
    ]
    
    print("\n" + "="*50)
    print("=== PHASE 5/6: REAL CONCURRENT RADAR CYCLE VALIDATION ===")
    print("="*50)
    
    for kw, cat in keywords:
        print(f"\n--- Testing Keyword: '{kw}' ---")
        start_time = time.time()
        
        result = run_radar_cycle(
            keyword=kw,
            category=cat,
            orchestrator=orchestrator,
            strategic_engine=strategic_engine,
            execution_mode="autonomous",
            days_back=7,
            max_per_source=30,
            # using default providers
        )
        
        elapsed = time.time() - start_time
        
        print(f"Cycle Result: {result.get('status')} | Emitted: {result.get('recommended')} | Runtime: {elapsed:.2f}s")
        if "phases" in result and "phase_2_collection" in result["phases"]:
            col = result["phases"]["phase_2_collection"]
            print(f"  Signals Collected: {col.get('total_occurrences')} across {col.get('distinct_sources')} sources")
        
if __name__ == "__main__":
    test_full_radar_cycles()

