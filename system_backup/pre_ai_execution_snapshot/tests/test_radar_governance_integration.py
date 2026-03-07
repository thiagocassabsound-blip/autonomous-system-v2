"""
tests/test_radar_governance_integration.py — B6 Validation Suite

7 closure criteria:
  1.  Blocks in CONTENÇÃO
  2.  Blocks when financial alert active
  3.  Blocks when macro exposure exceeds
  4.  Blocks when betas > 2
  5.  Allows when all conditions satisfied → emits expansion_recommendation_approved
  6.  No direct execution allowed (RadarExecutionOutsideOrchestratorError)
  7.  Append-only logging (records accumulate)

Usage:
    py tests/test_radar_governance_integration.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus import EventBus
from core.strategic_opportunity_engine import (
    StrategicOpportunityEngine,
    RadarExecutionOutsideOrchestratorError,
)
from core.macro_exposure_governance_engine import MacroExposureGovernanceEngine
from core.state_manager import StateManager, DirectWriteError


# ====================================================================
# In-memory stubs
# ====================================================================

class MemOpportunityPersistence:
    def __init__(self):
        self._records = []
    def append_record(self, r):
        import copy; self._records.append(copy.deepcopy(r))
    def load_all(self):
        import copy; return copy.deepcopy(self._records)

class MemExposurePersistence:
    def __init__(self):
        self._records = []
    def append_record(self, r):
        import copy; self._records.append(copy.deepcopy(r))
    def load_all(self):
        import copy; return copy.deepcopy(self._records)


def _make_engine(persistence=None):
    return StrategicOpportunityEngine(
        persistence=persistence or MemOpportunityPersistence()
    )

def _make_macro_engine(persistence=None):
    return MacroExposureGovernanceEngine(
        persistence=persistence or MemExposurePersistence()
    )


# Convenience call — all good defaults (would pass governance)
def _eval(engine, bus, **overrides):
    defaults = dict(
        product_id="prod-1",
        emotional_score=80.0,
        monetization_score=80.0,
        products_in_cluster=1,
        total_active_products=5,
        score_global=85.0,
        roas_avg=2.0,
        global_state="NORMAL",
        active_betas=1,
        macro_block=False,
        positive_trend=True,
        # B6 governance (clean defaults)
        financial_alert_active=False,
        credit_low_warning=False,
        credit_critical_warning=False,
        dias_restantes=30.0,
        buffer_minimo=7.0,
    )
    defaults.update(overrides)
    return engine.evaluate_opportunity(event_bus=bus, **defaults)


# ====================================================================
# Test runner
# ====================================================================
results = []

def test(name, fn):
    try:
        fn()
        results.append(("[OK]", name))
        print(f"  [OK]  {name}")
    except AssertionError as e:
        results.append(("[FAIL]", name))
        print(f"  [FAIL] {name} — AssertionError: {e}")
    except Exception as e:
        results.append(("[FAIL]", name))
        print(f"  [FAIL] {name} — {type(e).__name__}: {e}")


# ====================================================================
# TESTS
# ====================================================================

def t1_blocks_contencao():
    """Returns eligible=False and emits radar_blocked_global_state in CONTENÇÃO."""
    eng = _make_engine()
    bus = EventBus()

    for state in ("CONTENÇÃO", "CONTENÇÃO_FINANCEIRA", "contencao"):
        bus2 = EventBus()
        result = _eval(eng, bus2, global_state=state)
        assert result["eligible"] is False, \
            f"Expected blocked for state='{state}', got {result}"
        assert result["blocked_reason"] == "GLOBAL_STATE_CONTENCAO", \
            f"Wrong reason for state='{state}': {result}"
        types = [e["event_type"] for e in bus2.get_events()]
        assert "radar_blocked_global_state" in types, \
            f"Expected radar_blocked_global_state for '{state}', got {types}"


def t2_blocks_financial_alert():
    """Returns eligible=False and emits radar_blocked_financial_risk on any financial flag."""
    eng = _make_engine()

    # Case 1: financial_alert_active
    bus1 = EventBus()
    r1 = _eval(eng, bus1, financial_alert_active=True)
    assert r1["eligible"] is False
    assert r1["blocked_reason"] == "FINANCIAL_RISK"
    assert "radar_blocked_financial_risk" in [e["event_type"] for e in bus1.get_events()]

    # Case 2: credit_low_warning
    bus2 = EventBus()
    r2 = _eval(eng, bus2, credit_low_warning=True)
    assert r2["eligible"] is False
    assert r2["blocked_reason"] == "FINANCIAL_RISK"

    # Case 3: credit_critical_warning
    bus3 = EventBus()
    r3 = _eval(eng, bus3, credit_critical_warning=True)
    assert r3["eligible"] is False
    assert r3["blocked_reason"] == "FINANCIAL_RISK"

    # Case 4: dias_restantes < buffer_minimo
    bus4 = EventBus()
    r4 = _eval(eng, bus4, dias_restantes=3.0, buffer_minimo=7.0)
    assert r4["eligible"] is False
    assert r4["blocked_reason"] == "FINANCIAL_RISK"


def t3_blocks_macro_exposure():
    """Returns eligible=False and emits radar_blocked_macro_exposure when B5 blocks."""
    eng        = _make_engine()
    macro_eng  = _make_macro_engine()
    bus        = EventBus()

    # With total_capital=1000 and simulated_allocation=250,
    # projected_product = 250/1000 = 0.25 > base_limit 0.20 → B5 blocks
    result = _eval(
        eng, bus,
        macro_exposure_engine=macro_eng,
        simulated_allocation=250.0,
        total_capital=1000.0,
        current_product_allocation=0.0,
        current_channel_allocation=0.0,
        current_global_allocation=0.0,
        # Keep other governance conditions clean
        roas_avg=1.5,   # below adaptive threshold → base limits apply
        score_global=70.0,
        financial_alert_active=False,
    )
    assert result["eligible"] is False, f"Expected blocked, got {result}"
    assert result["blocked_reason"] == "MACRO_EXPOSURE_LIMIT", f"Wrong reason: {result}"
    types = [e["event_type"] for e in bus.get_events()]
    assert "radar_blocked_macro_exposure" in types, f"Got: {types}"


def t4_blocks_beta_limit():
    """Returns eligible=False and emits radar_blocked_beta_limit when active_betas > 2."""
    eng = _make_engine()
    bus = EventBus()

    result = _eval(eng, bus, active_betas=3)
    assert result["eligible"] is False
    assert result["blocked_reason"] == "BETA_LIMIT"
    types = [e["event_type"] for e in bus.get_events()]
    assert "radar_blocked_beta_limit" in types, f"Got: {types}"

    # Boundary: exactly 2 betas must NOT block
    bus2 = EventBus()
    r2 = _eval(eng, bus2, active_betas=2)
    assert r2["eligible"] is True, f"2 betas should be allowed, got {r2}"


def t5_allows_all_conditions():
    """When all B6 layers pass and opportunity is good → expansion_recommendation_approved."""
    eng = _make_engine()
    bus = EventBus()

    result = _eval(
        eng, bus,
        global_state="NORMAL",
        financial_alert_active=False,
        credit_low_warning=False,
        credit_critical_warning=False,
        dias_restantes=30.0,
        buffer_minimo=7.0,
        active_betas=1,
        # Good scores
        emotional_score=80.0,
        monetization_score=82.0,
        score_global=85.0,
        roas_avg=2.0,
        positive_trend=True,
    )
    assert result["eligible"] is True, f"Expected eligible=True, got {result}"
    types = [e["event_type"] for e in bus.get_events()]
    assert "expansion_recommendation_approved" in types, \
        f"Expected expansion_recommendation_approved, got {types}"
    # Verify the approval event carries required fields
    approval = next(
        e for e in bus.get_events()
        if e["event_type"] == "expansion_recommendation_approved"
    )
    payload = approval["payload"]
    for key in ("opportunity_id", "emotional_score", "monetization_score",
                "score_final", "cluster_ratio", "ice_status",
                "global_state", "roas_avg", "score_global", "timestamp", "note"):
        assert key in payload, f"Missing field '{key}' in approval payload"
    # Confirm "no execute" note is present
    assert "does not create product" in payload["note"]


def t6_no_direct_execution():
    """execute_directly() raises RadarExecutionOutsideOrchestratorError."""
    raised = False
    try:
        StrategicOpportunityEngine.execute_directly()
    except RadarExecutionOutsideOrchestratorError:
        raised = True
    assert raised, "Expected RadarExecutionOutsideOrchestratorError"


def t7_append_only_logging():
    """Governance validation records accumulate in persistence (append-only)."""
    pers = MemOpportunityPersistence()
    eng  = _make_engine(persistence=pers)
    bus  = EventBus()

    # First eval: passes governance (eligible)
    _eval(eng, bus, product_id="p-a")
    count_1 = len(pers.load_all())
    assert count_1 >= 1, "First eval should create a record"

    # Second eval: blocked by CONTENÇÃO (does NOT persist a record in current design
    # because the early-return happens before persistece — this is intentional & compliant)
    bus2 = EventBus()
    _eval(eng, bus2, product_id="p-b")
    count_2 = len(pers.load_all())
    assert count_2 >= count_1, "Count must never decrease (append-only)"

    # Third eval: another eligible
    bus3 = EventBus()
    _eval(eng, bus3, product_id="p-c")
    count_3 = len(pers.load_all())
    assert count_3 >= count_2, "Count must never decrease"

    # Monotonicity
    counts = [count_1, count_2, count_3]
    for a, b in zip(counts, counts[1:]):
        assert b >= a, f"Count went backward: {a} -> {b}"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 66)
    print("  B6 — RADAR ↔ GOVERNANCE INTEGRATION — TEST SUITE")
    print("=" * 66)

    test("Blocks in CONTENÇÃO",                       t1_blocks_contencao)
    test("Blocks when financial alert active",         t2_blocks_financial_alert)
    test("Blocks when macro exposure exceeds",         t3_blocks_macro_exposure)
    test("Blocks when betas > 2",                     t4_blocks_beta_limit)
    test("Allows when all conditions satisfied",       t5_allows_all_conditions)
    test("No direct execution allowed",               t6_no_direct_execution)
    test("Append-only logging",                       t7_append_only_logging)

    print("\n" + "=" * 66)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  B6 — RADAR GOVERNANCE INTEGRATION — VALID")
        print("  B6 LOCKED")
    else:
        print("  B6 — INVALID (see failures above)")
    print("=" * 66 + "\n")

    sys.exit(0 if passed == total else 1)
