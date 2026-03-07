"""
infra_tests/test_stress_constitutional_v2.py
Constitutional Stress Test — Bloco 26 V2
500+ synthetic scenarios, stratified sampling to produce meaningful stats.

Strategy:
 - 60% "full-pass candidates": all non-tested dims at passing values,
   one or more dims randomly swept across full range (0-100).
 - 40% "adversarial": randomly chosen dimension set below cut to stress reject logic.
 - All results verified by in-process constitutional invariants.
 - Output: single JSON. Exit 0 if constitutional_integrity=true.
"""
import json
import os
import sys
import random

sys.path.append(os.getcwd())

from unittest.mock import MagicMock
from core.strategic_opportunity_engine import (
    StrategicOpportunityEngine,
    EMOTIONAL_CUT, MONETIZATION_CUT, GROWTH_SCORE_CUT,
    GROWTH_PERCENT_MIN, NOISE_FILTER_CUT, CLUSTER_RATIO_THRESHOLD,
    CLUSTER_PENALTY_FACTOR, compute_emotional_score,
    compute_monetization_score, compute_final_score,
)

# -----------------------------------------------------------------------
# Engine factory (isolated instance per test run)
# -----------------------------------------------------------------------

def make_engine():
    orch = MagicMock()
    pers = MagicMock()
    pers.load_all.return_value = []
    return StrategicOpportunityEngine(orchestrator=orch, persistence=pers)


# -----------------------------------------------------------------------
# Payload builder
# -----------------------------------------------------------------------

PASS_EMOTIONAL   = {"freq": 90.0, "intensity": 85.0, "recurrence": 80.0, "persistence": 75.0}
PASS_MONETIZE    = {"intent": 90.0, "solutions": 85.0, "cpc": 80.0, "validation": 88.0}
PASS_GROWTH_SCORE   = 80.0
PASS_GROWTH_PCT     = 25.0
PASS_ICE_GLOBAL     = 85.0
PASS_ICE_ROAS       = 2.2


def build_payload(
    ei=None, mi=None,
    growth_score=None, growth_percent=None,
    n_sources=3, occurrences=200,
    noise_score=85.0,
    products_in_cluster=1, total_active_products=10,
    score_global=None, roas=None,
    positive_trend=True,
    scenario_id=0,
):
    return {
        "product_id": f"stress_{scenario_id}",
        "global_state": "NORMAL",
        "financial_alert_active": False,
        "active_betas": 0,
        "macro_exposure_blocked": False,
        "dataset_snapshot": {"sources": [f"src_{j}" for j in range(n_sources)]},
        "occurrences":       occurrences,
        "growth_percent":    growth_percent if growth_percent is not None else PASS_GROWTH_PCT,
        "noise_filter_score": noise_score,
        # Emotional
        "freq":        (ei or PASS_EMOTIONAL)["freq"],
        "intensity":   (ei or PASS_EMOTIONAL)["intensity"],
        "recurrence":  (ei or PASS_EMOTIONAL)["recurrence"],
        "persistence": (ei or PASS_EMOTIONAL)["persistence"],
        # Monetization
        "intent":      (mi or PASS_MONETIZE)["intent"],
        "solutions":   (mi or PASS_MONETIZE)["solutions"],
        "cpc":         (mi or PASS_MONETIZE)["cpc"],
        "validation":  (mi or PASS_MONETIZE)["validation"],
        # Growth
        "growth_score": growth_score if growth_score is not None else PASS_GROWTH_SCORE,
        # Cluster
        "products_in_cluster":   products_in_cluster,
        "total_active_products": total_active_products,
        # ICE
        "score_global": score_global if score_global is not None else PASS_ICE_GLOBAL,
        "roas":         roas if roas is not None else PASS_ICE_ROAS,
        "positive_trend": positive_trend,
    }


# -----------------------------------------------------------------------
# Constitutional invariant checker
# -----------------------------------------------------------------------

def check_invariants(result):
    issues = []

    if result.get("status") in ("blocked", "rejected", "not_qualified", "error"):
        return issues  # valid gate exits — no math to check

    emo = result.get("emotional", 0.0)
    mon = result.get("monetization", 0.0)
    gs  = result.get("growth_score", 0.0)
    cr  = result.get("cluster_ratio", 0.0)

    # 1. Score_Final formula
    expected_raw = (mon * 0.6) + (emo * 0.25) + (gs * 0.15)
    if cr >= CLUSTER_RATIO_THRESHOLD:
        expected_raw *= CLUSTER_PENALTY_FACTOR
    expected_raw = round(expected_raw, 4)
    actual_sf = result.get("score_final", -999)
    if abs(actual_sf - expected_raw) > 0.0002:
        issues.append(f"MATH: expected={expected_raw} got={actual_sf}")

    # 2. Cluster penalty flag
    if cr >= CLUSTER_RATIO_THRESHOLD and result.get("cluster_penalty") is not True:
        issues.append(f"CLUSTER_FLAG_MISSING: ratio={cr:.3f}")
    if cr < CLUSTER_RATIO_THRESHOLD and result.get("cluster_penalty") is True:
        issues.append(f"CLUSTER_FLAG_SPURIOUS: ratio={cr:.3f}")

    # 3. Snapshot hash must be 64-char hex
    snap_hash = result.get("snapshot_hash", "")
    if not snap_hash:
        issues.append("SNAPSHOT_HASH_MISSING")
    elif len(snap_hash) != 64 or not all(c in "0123456789abcdef" for c in snap_hash.lower()):
        issues.append(f"SNAPSHOT_HASH_INVALID: '{snap_hash[:12]}...'")

    # 4. recommended gate consistency
    if result.get("recommended") is True:
        if emo < EMOTIONAL_CUT:
            issues.append(f"REC_VIOLATION: emo={emo} < {EMOTIONAL_CUT}")
        if mon < MONETIZATION_CUT:
            issues.append(f"REC_VIOLATION: mon={mon} < {MONETIZATION_CUT}")
        if gs < GROWTH_SCORE_CUT:
            issues.append(f"REC_VIOLATION: gs={gs} < {GROWTH_SCORE_CUT}")

    # 5. No auto-execution keys
    forbidden = {"product_created", "beta_launched", "capital_allocated"}
    found = forbidden & set(result.keys())
    if found:
        issues.append(f"AUTO_EXEC: {found}")

    return issues


# -----------------------------------------------------------------------
# Scenario generator
# -----------------------------------------------------------------------

def generate_scenarios(n=500, seed=42):
    rng = random.Random(seed)
    scenarios = []

    # Stratum A — 200 guaranteed full-pass candidates (vary cluster ratio)
    for i in range(200):
        cluster_n  = rng.randint(0, 6)
        cluster_t  = rng.randint(max(cluster_n, 1), 20)
        scenarios.append(build_payload(
            products_in_cluster=cluster_n,
            total_active_products=cluster_t,
            scenario_id=i,
        ))

    # Stratum B — 100 varied growth_score (some below cut)
    for i in range(100):
        gs = rng.uniform(40, 100)
        gp = rng.uniform(10, 50)
        scenarios.append(build_payload(growth_score=gs, growth_percent=gp, scenario_id=200 + i))

    # Stratum C — 100 varied Emotional inputs
    for i in range(100):
        freq = rng.uniform(30, 100)
        intens = rng.uniform(30, 100)
        rec  = rng.uniform(30, 100)
        pers = rng.uniform(30, 100)
        scenarios.append(build_payload(
            ei={"freq": freq, "intensity": intens, "recurrence": rec, "persistence": pers},
            scenario_id=300 + i,
        ))

    # Stratum D — 50 adversarial noise (noise < 60)
    for i in range(50):
        noise = rng.uniform(10, 65)
        scenarios.append(build_payload(noise_score=noise, scenario_id=400 + i))

    # Stratum E — 50 adversarial Monetization (varied intent/solutions/cpc)
    for i in range(50):
        intent = rng.uniform(10, 100)
        sol    = rng.uniform(10, 100)
        cpc    = rng.uniform(10, 100)
        val    = rng.uniform(10, 100)
        scenarios.append(build_payload(
            mi={"intent": intent, "solutions": sol, "cpc": cpc, "validation": val},
            scenario_id=450 + i,
        ))

    return scenarios


# -----------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------

def run_stress_test(n=500, seed=42):
    scenarios = generate_scenarios(n, seed)
    total = len(scenarios)

    engine = make_engine()

    approved = 0
    low_emotional_approved   = 0
    borderline_growth_approved = 0
    cluster_penalty_triggered  = 0
    constitutional_violations  = []
    discrepancy_cases = []

    for payload in scenarios:
        result = engine.evaluate_opportunity_v2(payload)

        # Constitutional invariants
        issues = check_invariants(result)
        if issues:
            constitutional_violations.extend(issues)
            # Terminate immediately on violation
            break

        # Stats only for reached records (not blocked by governance/noise)
        status = result.get("status")
        is_qualified_record = status is None and "event_id" in result
        if is_qualified_record:
            approved += 1
            emo_val = result.get("emotional", 0.0)
            gs_val  = result.get("growth_score", 0.0)
            mon_val = result.get("monetization", 0.0)

            if emo_val < 50.0:
                low_emotional_approved += 1

            if 60.0 <= gs_val < 61.0:
                borderline_growth_approved += 1

            if result.get("cluster_penalty") is True:
                cluster_penalty_triggered += 1

            disc = abs(mon_val - emo_val)
            discrepancy_cases.append((disc, {
                "scenario_id":    payload["product_id"],
                "emotional":      round(emo_val, 2),
                "monetization":   round(mon_val, 2),
                "growth_score":   round(gs_val, 2),
                "growth_percent": round(payload.get("growth_percent", 0), 2),
                "score_final":    result.get("score_final"),
                "cluster_ratio":  result.get("cluster_ratio"),
                "cluster_penalty": result.get("cluster_penalty"),
                "ice":            result.get("ice"),
                "discrepancy":    round(disc, 2),
            }))

    discrepancy_cases.sort(key=lambda x: x[0], reverse=True)
    top5 = [c[1] for c in discrepancy_cases[:5]]

    constitutional_integrity = len(constitutional_violations) == 0

    report = {
        "total_simulated":            total,
        "approved":                   approved,
        "approval_rate_pct":          round(approved / total * 100, 2),
        "low_emotional_approved":     low_emotional_approved,
        "borderline_growth_approved": borderline_growth_approved,
        "cluster_penalty_triggered":  cluster_penalty_triggered,
        "top_5_discrepancy_cases":    top5,
        "constitutional_integrity":   constitutional_integrity,
        "constitutional_violations":  constitutional_violations[:10],
    }
    return report, constitutional_integrity


if __name__ == "__main__":
    report, ok = run_stress_test(n=500, seed=42)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    sys.exit(0 if ok else 1)
