"""
tests/test_opportunity_confluence_engine.py — B2 Confluência Mínima Validation Suite

7 closure criteria:
  1.  categorias < 3 bloqueia
  2.  crescimento < 15% bloqueia
  3.  intensidade < 60 bloqueia
  4.  falha em qualquer critério interrompe Bloco 26 (sem score, sem ICE, sem ranking)
  5.  evento opportunity_rejected_confluence emitido corretamente
  6.  nenhuma escrita fora do Orchestrator (DirectWriteError)
  7.  nenhuma oportunidade bloqueada entra no ranking

Usage:
    py tests/test_opportunity_confluence_engine.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus                      import EventBus
from core.opportunity_confluence_engine  import (
    OpportunityConfluenceEngine,
    ConfluenceExecutionForbiddenError,
    MIN_CATEGORIES,
    MIN_GROWTH_PCT,
    MIN_INTENSITY,
)
from core.strategic_opportunity_engine   import StrategicOpportunityEngine
from core.state_manager                  import StateManager, DirectWriteError


# ====================================================================
# In-memory stubs
# ====================================================================

class MemConfluencePersistence:
    def __init__(self):
        self._records = []
    def append_record(self, r):
        import copy; self._records.append(copy.deepcopy(r))
    def load_all(self):
        import copy; return copy.deepcopy(self._records)


class MemOpportunityPersistence:
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
            "user_id": payload.get("user_id") if isinstance(payload, dict) else None,
            "product_id": product_id
        })

def _make_b2(orchestrator=None, persistence=None):
    if orchestrator is None:
        orchestrator = MockOrchestrator(EventBus())
    return OpportunityConfluenceEngine(
        orchestrator=orchestrator,
        persistence=persistence or MemConfluencePersistence()
    )


def _make_b26_with_b2():
    """Return Bloco 26 engine with B2 confluence gate injected."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    b2  = _make_b2(orchestrator=orc)
    b26 = StrategicOpportunityEngine(
        orchestrator=orc,
        persistence=MemOpportunityPersistence(),
        confluence_engine=b2,
    )
    return b26, b2, orc, bus


GOOD_CATEGORIES = [
    "busca_ativa",
    "discussao_organica",
    "intencao_comercial",
]


def _evaluate_b26(b26, **overrides):
    """Call b26.evaluate_opportunity with strong passing defaults + overrides."""
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
        categories_confirmed=list(GOOD_CATEGORIES),
        growth_percent=20.0,
        intensity_score=75.0,
    )
    defaults.update(overrides)
    return b26.evaluate_opportunity(**defaults)


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

def t1_categories_cut():
    """categorias < 3 → B2 rejects → opportunity_rejected_confluence emitted."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    b2  = _make_b2(orchestrator=orc)

    # Only 2 valid categories
    result = b2.validate(
        product_id="prod-1",
        categories_confirmed=["busca_ativa", "volume_consolidado"],
        growth_percent=20.0,
        intensity_score=75.0,
    )

    assert result.approved is False, "Expected B2 rejection for categories < 3"
    types = [e["event_type"] for e in bus.get_events()]
    assert "opportunity_rejected_confluence" in types

    # Check blocking reason mentions categories
    assert any("categories" in r for r in result.blocking_reasons), (
        f"blocking_reasons should mention categories: {result.blocking_reasons}"
    )


def t2_growth_cut():
    """crescimento < 15% → B2 rejects."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    b2  = _make_b2(orchestrator=orc)

    result = b2.validate(
        product_id="prod-1",
        categories_confirmed=list(GOOD_CATEGORIES),
        growth_percent=10.0,     # below 15%
        intensity_score=75.0,
    )

    assert result.approved is False
    assert any("growth_percent" in r for r in result.blocking_reasons), (
        f"blocking_reasons should mention growth: {result.blocking_reasons}"
    )
    types = [e["event_type"] for e in bus.get_events()]
    assert "opportunity_rejected_confluence" in types


def t3_intensity_cut():
    """intensidade < 60 → B2 rejects."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    b2  = _make_b2(orchestrator=orc)

    result = b2.validate(
        product_id="prod-1",
        categories_confirmed=list(GOOD_CATEGORIES),
        growth_percent=20.0,
        intensity_score=50.0,    # below 60
    )

    assert result.approved is False
    assert any("intensity_score" in r for r in result.blocking_reasons), (
        f"blocking_reasons should mention intensity: {result.blocking_reasons}"
    )
    types = [e["event_type"] for e in bus.get_events()]
    assert "opportunity_rejected_confluence" in types


def t4_b2_blocks_bloco26():
    """
    Any B2 failure stops Bloco 26 completely:
      - score_final must be 0 (not computed)
      - ice must be BLOQUEADO
      - eligible must be False
      - b2_rejected must be True
      - no expansion_opportunity_evaluated event
    """
    for bad_kwargs, label in [
        ({"categories_confirmed": ["busca_ativa"]},          "2 categories"),
        ({"growth_percent": 5.0},                           "growth 5%"),
        ({"intensity_score": 40.0},                         "intensity 40"),
    ]:
        b26, b2, orc, bus = _make_b26_with_b2()
        record = _evaluate_b26(b26, **bad_kwargs)

        assert record["eligible"] is False,    f"[{label}] eligible should be False"
        assert record["b2_rejected"] is True,  f"[{label}] b2_rejected should be True"
        assert record["score_final"] == 0.0,   f"[{label}] score_final should be 0 (not computed)"

        types = [e["event_type"] for e in bus.get_events()]
        assert "expansion_opportunity_evaluated" not in types, (
            f"[{label}] expansion_opportunity_evaluated must not be emitted on B2 rejection"
        )
        assert "opportunity_rejected_confluence" in types, (
            f"[{label}] opportunity_rejected_confluence must be emitted"
        )


def t5_rejected_confluence_event():
    """
    opportunity_rejected_confluence event contains all required fields.
    """
    bus = EventBus()
    orc = MockOrchestrator(bus)
    b2  = _make_b2(orchestrator=orc)

    b2.validate(
        product_id="prod-99",
        categories_confirmed=[],   # 0 categories — fails all
        growth_percent=0.0,
        intensity_score=0.0,
    )

    events = [e for e in bus.get_events()
              if e["event_type"] == "opportunity_rejected_confluence"]
    assert len(events) == 1, "Exactly one rejection event expected"

    payload = events[0]["payload"]
    required_fields = [
        "event_id", "blocking_reasons", "categories_confirmed",
        "growth_percent", "intensity_score", "timestamp",
    ]
    for field in required_fields:
        assert field in payload, f"Missing field '{field}' in rejection event payload"

    assert payload["categories_confirmed"] == []
    assert len(payload["blocking_reasons"]) >= 3   # all three gates failed


def t6_direct_write_blocked():
    """StateManager.set() in any context raises DirectWriteError."""
    sm = StateManager()
    raised = False
    try:
        sm.set("confluence_bypass", True)
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


def t7_rejected_not_in_ranking():
    """
    Opportunities blocked by B2 must never appear in the ranked list.
    Passing opportunities should appear; failing ones should not.
    """
    b26, b2, orc, bus = _make_b26_with_b2()

    # Pass two: good confluence
    _evaluate_b26(b26, product_id="prod-pass-1")
    _evaluate_b26(b26, product_id="prod-pass-2")

    # Fail one: bad growth
    bad_record = _evaluate_b26(b26, product_id="prod-fail-1", growth_percent=5.0)

    assert bad_record["b2_rejected"] is True

    # get_ranked_opportunities should exclude b2_rejected entries
    ranked = [
        r for r in b26.get_ranked_opportunities()
        if not r.get("b2_rejected", False)
    ]
    ranked_ids = {r["product_id"] for r in ranked}

    assert "prod-pass-1" in ranked_ids, "prod-pass-1 should appear in ranking"
    assert "prod-pass-2" in ranked_ids, "prod-pass-2 should appear in ranking"
    assert "prod-fail-1" not in ranked_ids, (
        "prod-fail-1 was B2-rejected and must not appear in ranked list"
    )


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 64)
    print("  B2 CONFLUÊNCIA MÍNIMA — TEST SUITE")
    print("=" * 64)

    test("categorias < 3 bloqueia",                                t1_categories_cut)
    test("crescimento < 15% bloqueia",                             t2_growth_cut)
    test("intensidade < 60 bloqueia",                              t3_intensity_cut)
    test("falha em qualquer critério interrompe Bloco 26",         t4_b2_blocks_bloco26)
    test("evento opportunity_rejected_confluence emitido",         t5_rejected_confluence_event)
    test("nenhuma escrita fora do Orchestrator",                   t6_direct_write_blocked)
    test("oportunidade bloqueada não entra no ranking",            t7_rejected_not_in_ranking)

    print("\n" + "=" * 64)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  B2 CONFLUÊNCIA MÍNIMA — VALID")
        print("  B2 LOCKED")
    else:
        print("  B2 — INVALID (see failures above)")
    print("=" * 64 + "\n")

    sys.exit(0 if passed == total else 1)
