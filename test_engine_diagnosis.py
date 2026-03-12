
import sys
import os

BASE_DIR = r"c:\Users\Cliente\Downloads\fastoolhub.com\autonomous-system-v2"
sys.path.append(BASE_DIR)

from core.strategic_opportunity_engine import StrategicOpportunityEngine

class MockPers:
    def load_all(self): return []
    def append_record(self, record):
        pass

class MockOrch:
    def emit_event(self, *args, **kwargs):
        pass

engine = StrategicOpportunityEngine(orchestrator=MockOrch(), persistence=MockPers())

payload = {
    "product_id":             "test_event",
    "global_state":           "NORMAL",
    "financial_alert_active": False,
    "active_betas":           0,
    "macro_exposure_blocked": False,
    "dataset_snapshot":       {"sources": ["src1", "src2", "src3"]},
    "occurrences":            150,
    "growth_percent":         25.0,
    "noise_filter_score":     70.0,
    "freq": 80.0, "intensity": 75.0, "recurrence": 70.0, "persistence": 65.0,
    "intent": 80.0, "solutions": 75.0, "cpc": 70.0, "validation": 75.0,
    "growth_score":            70.0,
    "products_in_cluster":     0,
    "total_active_products":   1,
    "score_global":            80.0,
    "roas":                    2.0,
    "positive_trend":          True,
}

result = engine.evaluate_opportunity_v2(payload)
print(f"Status: {result.get('status')}")
print(f"Reason: {result.get('reason')}")
print(f"ICE: {result.get('ice')}")
print(f"Score Final: {result.get('score_final')}")
print(f"Recommended: {result.get('recommended')}")
