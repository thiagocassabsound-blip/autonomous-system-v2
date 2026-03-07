import os
import sys
import time
from infrastructure.logger import get_logger
from radar.radar_engine import run_radar_cycle
from core.strategic_opportunity_engine import StrategicOpportunityEngine

logger = get_logger("RadarBatchTest")

class MockOrchestrator:
    def __init__(self):
        self.events = []
    def receive_event(self, event):
        self.events.append(event)
    def emit_event(self, event_type, product_id, payload, source="system"):
        self.events.append({"type": event_type, "payload": payload})

class MockPersistence:
    def __init__(self):
        self.records = []
    def load_all(self):
        return []
    def append_record(self, record):
        self.records.append(record)

def run_large_scale_validation():
    print("="*60)
    print("=== PHASE 3 & 4: REAL RADAR CYCLE BATCH TEST (20 KEYWORDS) ===")
    print("="*60)

    keywords = [
        # AI development tools
        ("AI coding assistant", "saas"),
        ("github copilot alternative", "saas"),
        # workflow automation
        ("marketing workflow automation", "saas"),
        ("zapier alternative for enterprise", "saas"),
        # developer productivity
        ("developer productivity tracking", "saas"),
        ("remote engineering team metrics", "saas"),
        # customer support platforms
        ("omnichannel helpdesk software", "saas"),
        ("AI customer service bot", "saas"),
        # no-code tools
        ("no-code internal tool builder", "saas"),
        ("retool alternative", "saas"),
        # data analytics tools
        ("product analytics for startups", "saas"),
        ("sql reporting tool", "saas"),
        # AI marketing tools
        ("AI ad copy generator", "saas"),
        ("automated seo writer", "saas"),
        # personal knowledge management
        ("networked thought app", "saas"),
        ("obsidian alternative sync", "saas"),
        # team collaboration software
        ("asynchronous video updates", "saas"),
        ("remote team virtual office", "saas"),
        # automation APIs
        ("headless browser scraping api", "saas"),
        ("screenshot api for developers", "saas")
    ]

    orchestrator = MockOrchestrator()
    strategic_engine = StrategicOpportunityEngine(
        orchestrator=orchestrator, 
        persistence=MockPersistence()
    )
    
    total_time = 0
    success_count = 0
    opportunities_emitted = 0
    overall_signals = 0

    print(f"Executing {len(keywords)} radar cycles...\n")

    for kw, cat in keywords:
        start = time.time()
        result = run_radar_cycle(
            keyword=kw,
            category=cat,
            orchestrator=orchestrator,
            strategic_engine=strategic_engine,
            execution_mode="autonomous",
            days_back=7,
            max_per_source=30
        )
        elapsed = time.time() - start
        total_time += elapsed
        
        status = result.get("status")
        rec = result.get("qualified", False)
        
        sig_count = 0
        sources = 0
        if "phases" in result and "phase_2_collection" in result["phases"]:
            sig_count = result["phases"]["phase_2_collection"].get("total_occurrences", 0)
            sources = result["phases"]["phase_2_collection"].get("distinct_sources", 0)
        
        if status not in ["error", "blocked_by_governance", "insufficient_data"]:
            success_count += 1
            overall_signals += sig_count
            
        if rec:
            opportunities_emitted += 1
            
        print(f"[{elapsed:.2f}s] {kw[:30]:<30} -> {status} \t| Signals: {sig_count:3} (Sources: {sources}) | Qualified: {rec}")

    print("\n" + "="*60)
    print("📋 BATCH TEST SUMMARY")
    print("="*60)
    print(f"Total Cycles         : {len(keywords)}")
    print(f"Successful Executions: {success_count}/{len(keywords)}")
    print(f"Opportunities Passed : {opportunities_emitted} (ICEGate & Confluence met)")
    print(f"Total Signals Gained : {overall_signals}")
    print(f"Total Latency        : {total_time:.2f}s")
    print(f"Average Latency      : {total_time/len(keywords):.2f}s per cycle")

if __name__ == "__main__":
    run_large_scale_validation()
