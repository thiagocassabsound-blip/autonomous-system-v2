import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Add project root to path
sys.path.append(os.getcwd())

from core.strategic_opportunity_engine import StrategicOpportunityEngine

def test_v2_full_pipeline_success():
    print("\n--- Test 1: Full Pipeline Success ---")
    mock_orch = MagicMock()
    mock_pers = MagicMock()
    mock_pers.load_all.return_value = []
    
    engine = StrategicOpportunityEngine(orchestrator=mock_orch, persistence=mock_pers)
    
    payload = {
        "product_id": "ai_profit_machine",
        "global_state": "NORMAL",
        "financial_alert_active": False,
        "active_betas": 0,
        "macro_exposure_blocked": False,
        "assisted_input": True,
        "query_spec": {"segment": "AI", "problem": "Inefficiency"},
        "dataset_snapshot": {"sources": ["reddit", "google_trends", "custom_provider"]},
        "noise_filter_score": 85,
        "freq": 80,
        "intensity": 75,
        "recurrence": 70,
        "intent": 90,
        "solutions": 80,
        "cpc": 70,
        "validation": 85,
        "growth_score": 80,
        "occurrences": 150,
        "products_in_cluster": 2,
        "total_active_products": 10,
        "score_global": 85,
        "roas": 2.5,
        "positive_trend": True
    }
    
    result = engine.evaluate_opportunity_v2(payload)
    print(json.dumps(result, indent=2))
    
    assert result["recommended"] is True
    assert result["score_final"] > 0
    assert result["ice"] == "ALTO"
    assert "expansion_recommendation_event" in [call[0][0] if call[0] else call[1].get('event_type') for call in mock_orch.emit_event.call_args_list]
    print("Success case passed.")

def test_v2_governance_block():
    print("\n--- Test 2: Governance Block (Contencao) ---")
    mock_orch = MagicMock()
    mock_pers = MagicMock()
    mock_pers.load_all.return_value = []
    
    engine = StrategicOpportunityEngine(orchestrator=mock_orch, persistence=mock_pers)
    
    payload = {
        "product_id": "risky_product",
        "global_state": "CONTENCAO_FINANCEIRA",
    }
    
    result = engine.evaluate_opportunity_v2(payload)
    print(json.dumps(result, indent=2))
    
    assert result["status"] == "blocked"
    assert "CONTENÇÃO" in result["reason"]
    print("Governance block passed.")

def test_v2_noise_rejection():
    print("\n--- Test 3: Noise Rejection ---")
    mock_orch = MagicMock()
    mock_pers = MagicMock()
    mock_pers.load_all.return_value = []
    
    engine = StrategicOpportunityEngine(orchestrator=mock_orch, persistence=mock_pers)
    
    payload = {
        "product_id": "noisy_signal",
        "global_state": "NORMAL",
        "dataset_snapshot": {"sources": ["s1", "s2", "s3"]},
        "noise_filter_score": 45  # Below cutoff of 60
    }
    
    result = engine.evaluate_opportunity_v2(payload)
    print(json.dumps(result, indent=2))
    
    assert result["status"] == "rejected"
    print("Noise rejection passed.")

def test_v2_low_monetization():
    print("\n--- Test 4: Low Monetization (Not Recommended) ---")
    mock_orch = MagicMock()
    mock_pers = MagicMock()
    mock_pers.load_all.return_value = []
    
    engine = StrategicOpportunityEngine(orchestrator=mock_orch, persistence=mock_pers)
    
    payload = {
        "product_id": "free_tool_idea",
        "global_state": "NORMAL",
        "dataset_snapshot": {"sources": ["s1", "s2", "s3"]},
        "noise_filter_score": 100,
        "freq": 90, "intensity": 90, "recurrence": 90, # High emotional
        "intent": 20, "solutions": 10, "cpc": 5, "validation": 5, # Low monetization
        "growth_score": 90,
        "occurrences": 500,
        "products_in_cluster": 0,
        "total_active_products": 10,
        "score_global": 80,
        "roas": 2.0
    }
    
    result = engine.evaluate_opportunity_v2(payload)
    print(json.dumps(result, indent=2))
    
    assert result["recommended"] is False
    print("Low monetization check passed.")

if __name__ == "__main__":
    try:
        test_v2_full_pipeline_success()
        test_v2_governance_block()
        test_v2_noise_rejection()
        test_v2_low_monetization()
        print("\nALL STRATEGIC OPPORTUNITY V2 TESTS PASSED!")
    except Exception as e:
        print(f"\nTEST FAILURE: {e}")
        sys.exit(1)
