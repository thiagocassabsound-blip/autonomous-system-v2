"""
tests/test_strategic_opportunity_engine.py — Bloco 26 Validation Suite

10 closure criteria:
  1.  Corte Emotional < 70 bloqueia elegibilidade
  2.  Corte Monetization < 75 bloqueia elegibilidade
  3.  Penalização cluster aplicada corretamente (cluster_ratio ≥ 0.30)
  4.  cluster_ratio calculado corretamente
  5.  ICE bloqueado quando ROAS < 1.6
  6.  ICE bloqueado quando Score_Global < 78
  7.  ICE bloqueado quando betas > 2
  8.  ICE bloqueado quando Estado_Global = Contenção
  9.  Nenhuma escrita fora do Orchestrator (DirectWriteError)
 10.  Execução automática proibida (AutoExpansionForbiddenError)

Usage:
    py tests/test_strategic_opportunity_engine.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus                  import EventBus
from core.strategic_opportunity_engine import (
    StrategicOpportunityEngine,
    AutoExpansionForbiddenError,
    compute_final_score,
    compute_cluster_ratio,
    classify_ice,
    ICE_BLOQUEADO,
    ICE_MODERADO,
    ICE_ALTO,
    CLUSTER_PENALTY_FACTOR,
)
from core.state_manager              import StateManager, DirectWriteError

# ====================================================================
# Stubs
# ====================================================================

class MemOpportunityPersistence:
    """In-memory append-only persistence."""
    def __init__(self):
        self._records = []
    def append_record(self, r):
        import copy; self._records.append(copy.deepcopy(r))
    def load_all(self):
        import copy; return copy.deepcopy(self._records)


class MockOrchestrator:
    def __init__(self, bus):
        self._bus = bus
    def emit_event(self, event_type, payload, source=None, product_id=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload": payload,
            "source": source or "orchestrator",
            "product_id": product_id
        })

def _make_engine(orchestrator=None):
    if orchestrator is None:
        orchestrator = MockOrchestrator(EventBus())
    return StrategicOpportunityEngine(orchestrator=orchestrator, persistence=MemOpportunityPersistence())


def _evaluate(eng, bus, **overrides):
    """Call evaluate_opportunity with sensible passing defaults + overrides."""
    defaults = dict(
        product_id="prod-1",
        emotional_score=80.0,
        monetization_score=80.0,
        products_in_cluster=1,
        total_active_products=5,
        score_global=80.0,
        roas_avg=2.0,
        global_state="NORMAL",
        active_betas=1,
        macro_block=False,
        positive_trend=False,
    )
    defaults.update(overrides)
    return eng.evaluate_opportunity(**defaults)


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

def t1_emotional_cut():
    """Emotional < 70 → eligible=False and expansion_not_recommended emitted."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)

    record = _evaluate(eng, bus, emotional_score=65.0)   # below 70

    assert record["eligible"] is False, "eligible should be False when Emotional < 70"
    event_types = [e["event_type"] for e in bus.get_events()]
    assert "expansion_not_recommended" in event_types, (
        "expansion_not_recommended not emitted for failed Emotional cut"
    )


def t2_monetization_cut():
    """Monetization < 75 → eligible=False and expansion_not_recommended emitted."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)

    record = _evaluate(eng, bus, monetization_score=70.0)   # below 75

    assert record["eligible"] is False
    event_types = [e["event_type"] for e in bus.get_events()]
    assert "expansion_not_recommended" in event_types


def t3_cluster_penalty_applied():
    """cluster_ratio ≥ 0.30 → score is reduced by 40% (multiplied by 0.60)."""
    # 3 in cluster, 6 total → ratio = 0.50 → penalty
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
 
    record = _evaluate(
        eng, bus,
        products_in_cluster=3,
        total_active_products=6,    # ratio = 0.50
    )

    assert record["cluster_ratio"] == 0.5,  f"cluster_ratio={record['cluster_ratio']}"
    assert record["cluster_penalty"] is True

    # Verify score is reduced correctly
    raw = (80.0 * 0.8) + (80.0 * 0.2)   # = 80.0
    expected = round(raw * CLUSTER_PENALTY_FACTOR, 4)
    assert abs(record["score_final"] - expected) < 0.001, (
        f"score_final={record['score_final']} expected≈{expected}"
    )


def t4_cluster_ratio_calculation():
    """compute_cluster_ratio produces exact values and handles zero denominator."""
    assert compute_cluster_ratio(2, 10)  == 0.2
    assert compute_cluster_ratio(3, 10)  == 0.3
    assert compute_cluster_ratio(0, 10)  == 0.0
    assert compute_cluster_ratio(5, 0)   == 0.0   # no division by zero

    # Below threshold → no penalty
    _, penalty = compute_final_score(80, 80, cluster_ratio=0.29)
    assert penalty is False, "0.29 < 0.30 should not trigger penalty"

    # At threshold → penalty
    _, penalty = compute_final_score(80, 80, cluster_ratio=0.30)
    assert penalty is True, "0.30 == threshold should trigger penalty"


def t5_ice_blocked_roas():
    """ICE = BLOQUEADO when roas_avg < 1.6."""
    ice, reasons = classify_ice(
        score_global=80,
        roas_avg=1.5,         # below 1.6
        global_state="NORMAL",
        active_betas=1,
        macro_block=False,
    )
    assert ice == ICE_BLOQUEADO, f"Expected BLOQUEADO, got {ice}"
    assert any("roas_avg" in r for r in reasons), f"roas reason missing: {reasons}"


def t6_ice_blocked_score_global():
    """ICE = BLOQUEADO when score_global < 78."""
    ice, reasons = classify_ice(
        score_global=75,      # below 78
        roas_avg=2.0,
        global_state="NORMAL",
        active_betas=1,
        macro_block=False,
    )
    assert ice == ICE_BLOQUEADO, f"Expected BLOQUEADO, got {ice}"
    assert any("score_global" in r for r in reasons)


def t7_ice_blocked_betas():
    """ICE = BLOQUEADO when active_betas > 2."""
    ice, reasons = classify_ice(
        score_global=80,
        roas_avg=2.0,
        global_state="NORMAL",
        active_betas=3,       # > 2
        macro_block=False,
    )
    assert ice == ICE_BLOQUEADO, f"Expected BLOQUEADO, got {ice}"
    assert any("active_betas" in r for r in reasons)


def t8_ice_blocked_contencao():
    """ICE = BLOQUEADO when global_state contains 'CONTENÇÃO' (case insensitive)."""
    for state in ["CONTENÇÃO_FINANCEIRA", "CONTENCAO", "contenção"]:
        ice, reasons = classify_ice(
            score_global=80,
            roas_avg=2.0,
            global_state=state,
            active_betas=1,
            macro_block=False,
        )
        assert ice == ICE_BLOQUEADO, f"Expected BLOQUEADO for state={state}, got {ice}"
        assert any("global_state" in r for r in reasons), (
            f"global_state reason missing for state={state}: {reasons}"
        )

    # B6 or ICE block: either radar_blocked_global_state (B6) or
    # expansion_blocked_macro (ICE path) satisfies the Contenção block requirement.
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
    record = _evaluate(eng, bus,
        global_state="CONTENÇÃO_FINANCEIRA",
        score_global=80, roas_avg=2.0, active_betas=1,
    )
    assert record["ice"] == ICE_BLOQUEADO
    assert record["eligible"] is False
    types = [e["event_type"] for e in bus.get_events()]
    assert (
        "expansion_blocked_macro" in types
        or "radar_blocked_global_state" in types
    ), f"Expected a Contenção block event, got {types}"


def t9_direct_write_blocked():
    """StateManager.set() raises DirectWriteError — no direct writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("opportunity_bypass", {"hack": True})
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


def t10_auto_execution_forbidden():
    """create_product_automatically and launch_beta_automatically always raise error."""
    eng = _make_engine()

    for method in [eng.create_product_automatically, eng.launch_beta_automatically]:
        raised = False
        try:
            method()
        except AutoExpansionForbiddenError:
            raised = True
        assert raised, f"Expected AutoExpansionForbiddenError from {method.__name__}"

    # Also verify a passing case emits correctly (no auto-create)
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
    record = _evaluate(eng, bus, positive_trend=True)
    assert record["ice"]      in [ICE_MODERADO, ICE_ALTO]
    assert record["eligible"] is True
    # Must NOT emit any product_created or beta_start event
    types = [e["event_type"] for e in bus.get_events()]
    assert "product_created" not in types,  "Auto product_created emitted — forbidden"
    assert "beta_start_requested" not in types, "Auto beta_start emitted — forbidden"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 64)
    print("  BLOCO 26 STRATEGIC OPPORTUNITY ENGINE — TEST SUITE")
    print("=" * 64)

    test("Corte Emotional < 70 bloqueia elegibilidade",        t1_emotional_cut)
    test("Corte Monetization < 75 bloqueia elegibilidade",     t2_monetization_cut)
    test("Penalização cluster aplicada corretamente",          t3_cluster_penalty_applied)
    test("cluster_ratio calculado corretamente",               t4_cluster_ratio_calculation)
    test("ICE bloqueado quando ROAS < 1.6",                   t5_ice_blocked_roas)
    test("ICE bloqueado quando Score_Global < 78",            t6_ice_blocked_score_global)
    test("ICE bloqueado quando betas > 2",                    t7_ice_blocked_betas)
    test("ICE bloqueado quando Estado_Global = Contenção",    t8_ice_blocked_contencao)
    test("Nenhuma escrita fora do Orchestrator",               t9_direct_write_blocked)
    test("Execução automática proibida",                       t10_auto_execution_forbidden)

    print("\n" + "=" * 64)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  BLOCO 26 STRATEGIC OPPORTUNITY ENGINE — VALID")
        print("  BLOCO 26 LOCKED")
    else:
        print("  BLOCO 26 — INVALID (see failures above)")
    print("=" * 64 + "\n")

    sys.exit(0 if passed == total else 1)
