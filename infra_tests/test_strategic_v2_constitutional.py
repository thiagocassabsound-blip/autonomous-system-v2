"""
infra_tests/test_strategic_v2_constitutional.py
9 mandatory scenarios for Bloco 26 V2 constitutional verification.
Strict: only final JSON, exit 0 on pass, exit 1 on fail.
"""
import json, os, sys
sys.path.append(os.getcwd())

from unittest.mock import MagicMock
from core.strategic_opportunity_engine import StrategicOpportunityEngine

PASS, FAIL = [], []

def make_engine():
    orch = MagicMock()
    pers = MagicMock()
    pers.load_all.return_value = []
    return StrategicOpportunityEngine(orchestrator=orch, persistence=pers), orch

# --- Base payload (all gates pass) ---
def base_payload(**overrides):
    p = {
        "product_id": "test_product",
        "global_state": "NORMAL",
        "financial_alert_active": False,
        "active_betas": 0,
        "macro_exposure_blocked": False,
        "dataset_snapshot": {"sources": ["reddit", "google", "custom"]},
        "occurrences": 200,
        "growth_percent": 25.0,
        "noise_filter_score": 80.0,
        "freq": 90.0, "intensity": 85.0, "recurrence": 80.0, "persistence": 75.0,
        "intent": 90.0, "solutions": 85.0, "cpc": 80.0, "validation": 88.0,
        "growth_score": 80.0,
        "products_in_cluster": 1,
        "total_active_products": 10,
        "score_global": 85.0,
        "roas": 2.0,
        "positive_trend": True,
    }
    p.update(overrides)
    return p

# ===========================================================================
# SCENARIO 1 — Caso ideal qualificado
# ===========================================================================
def test_1_ideal():
    engine, _ = make_engine()
    r = engine.evaluate_opportunity_v2(base_payload())
    ok = r.get("recommended") is True and r.get("ice") == "ALTO"
    PASS.append("1_ideal") if ok else FAIL.append("1_ideal (expected recommended=True, ICE=ALTO)")
    return r

# ===========================================================================
# SCENARIO 2 — Emotional < 70
# ===========================================================================
def test_2_low_emotional():
    engine, _ = make_engine()
    # freq=10, intensity=10, recurrence=10, persistence=10 → Emotional = 10.0
    r = engine.evaluate_opportunity_v2(base_payload(freq=10.0, intensity=10.0, recurrence=10.0, persistence=10.0))
    ok = r.get("status") == "not_qualified"
    PASS.append("2_low_emotional") if ok else FAIL.append(f"2_low_emotional (got status={r.get('status')})")
    return r

# ===========================================================================
# SCENARIO 3 — Monetization < 75
# ===========================================================================
def test_3_low_monetization():
    engine, _ = make_engine()
    r = engine.evaluate_opportunity_v2(base_payload(intent=10.0, solutions=10.0, cpc=10.0, validation=10.0))
    ok = r.get("status") == "not_qualified"
    PASS.append("3_low_monetization") if ok else FAIL.append(f"3_low_monetization (got status={r.get('status')})")
    return r

# ===========================================================================
# SCENARIO 4 — growth_score < 60
# ===========================================================================
def test_4_low_growth_score():
    engine, _ = make_engine()
    r = engine.evaluate_opportunity_v2(base_payload(growth_score=30.0))
    ok = r.get("status") == "not_qualified"
    PASS.append("4_low_growth_score") if ok else FAIL.append(f"4_low_growth_score (got status={r.get('status')})")
    return r

# ===========================================================================
# SCENARIO 5 — growth_percent < 15%
# ===========================================================================
def test_5_low_growth_percent():
    engine, _ = make_engine()
    r = engine.evaluate_opportunity_v2(base_payload(growth_percent=5.0))
    ok = r.get("status") == "not_qualified"
    PASS.append("5_low_growth_percent") if ok else FAIL.append(f"5_low_growth_percent (got status={r.get('status')})")
    return r

# ===========================================================================
# SCENARIO 6 — noise < 60
# ===========================================================================
def test_6_noise_below_cutoff():
    engine, _ = make_engine()
    r = engine.evaluate_opportunity_v2(base_payload(noise_filter_score=40.0))
    ok = r.get("status") == "rejected"
    PASS.append("6_noise_rejected") if ok else FAIL.append(f"6_noise_rejected (got status={r.get('status')})")
    return r

# ===========================================================================
# SCENARIO 7 — cluster_ratio >= 30% (penalization)
# ===========================================================================
def test_7_cluster_penalty():
    engine, _ = make_engine()
    # 4/10 = 40% cluster ratio → penalty
    r = engine.evaluate_opportunity_v2(base_payload(products_in_cluster=4, total_active_products=10))
    ok = r.get("cluster_penalty") is True and r.get("cluster_ratio", 0) >= 0.30
    PASS.append("7_cluster_penalty") if ok else FAIL.append(f"7_cluster_penalty (got penalty={r.get('cluster_penalty')} ratio={r.get('cluster_ratio')})")
    return r

# ===========================================================================
# SCENARIO 8 — ICE BLOQUEADO (ROAS too low)
# ===========================================================================
def test_8_ice_blocked():
    engine, _ = make_engine()
    r = engine.evaluate_opportunity_v2(base_payload(roas=0.5, score_global=50.0))
    ok = r.get("ice") == "BLOQUEADO" and r.get("recommended") is False
    PASS.append("8_ice_blocked") if ok else FAIL.append(f"8_ice_blocked (got ice={r.get('ice')} recommended={r.get('recommended')})")
    return r

# ===========================================================================
# SCENARIO 9 — global_state = CONTENCAO → blocked
# ===========================================================================
def test_9_contencao():
    engine, _ = make_engine()
    r = engine.evaluate_opportunity_v2(base_payload(global_state="CONTENCAO_FINANCEIRA"))
    ok = r.get("status") == "blocked"
    PASS.append("9_contencao_blocked") if ok else FAIL.append(f"9_contencao_blocked (got status={r.get('status')})")
    return r

# ===========================================================================
# RUN ALL
# ===========================================================================
if __name__ == "__main__":
    results = {}
    tests = [
        ("1_ideal",             test_1_ideal),
        ("2_low_emotional",     test_2_low_emotional),
        ("3_low_monetization",  test_3_low_monetization),
        ("4_low_growth_score",  test_4_low_growth_score),
        ("5_low_growth_percent", test_5_low_growth_percent),
        ("6_noise_rejected",    test_6_noise_below_cutoff),
        ("7_cluster_penalty",   test_7_cluster_penalty),
        ("8_ice_blocked",       test_8_ice_blocked),
        ("9_contencao_blocked", test_9_contencao),
    ]

    for name, fn in tests:
        try:
            r = fn()
            results[name] = r
        except Exception as e:
            FAIL.append(f"{name} (EXCEPTION: {e})")
            results[name] = {"error": str(e)}

    report = {
        "total": len(tests),
        "passed": len(PASS),
        "failed": len(FAIL),
        "pass_list": PASS,
        "fail_list": FAIL,
        "adherence_pct": round(len(PASS) / len(tests) * 100, 1),
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if not FAIL else 1)
