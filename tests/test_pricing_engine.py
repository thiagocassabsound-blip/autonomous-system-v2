"""
tests/test_pricing_engine.py — A7 Pricing Engine Validation Suite

8 closure criteria:
  1. Offensive +25% applied correctly
  2. Defensive −15% applied correctly
  3. Price cannot go below base_price
  4. Blocked after 3 consecutive offensive increases
  5. Blocked outside FASE_4 of Market Loop
  6. Auto-rollback on statistical loss (margin drop > 10%)
  7. CONTENÇÃO_FINANCEIRA blocks price changes
  8. DirectWriteError outside Orchestrator

Usage:
    py tests/test_pricing_engine.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus     import EventBus
from core.pricing_engine import (
    PricingEngine,
    PricingOffensiveLimitError,
    PricingBelowBaseError,
    PricingPhaseViolationError,
    PricingContainmentError,
)
from core.state_manager import StateManager, DirectWriteError
from core.global_state  import GlobalState, CONTENCAO_FINANCEIRA

# ====================================================================
# Stubs / helpers
# ====================================================================

class MemFile:
    def __init__(self):
        self._d = {}
    def load(self):
        import copy; return copy.deepcopy(self._d)
    def save(self, data):
        import copy; self._d = copy.deepcopy(data)


class MockOrchestrator:
    def __init__(self, event_bus):
        self._bus = event_bus
    def emit_event(self, event_type, payload, source=None, product_id=None, month_id=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload":    payload,
            "source":     source,
            "product_id": product_id,
            "month_id":   month_id
        })


class MockMarketLoop:
    """Simulates an open Market Loop cycle at an injectable phase."""
    def __init__(self, phase: int):
        self._phase = phase
    def _find_open_cycle(self, product_id):
        return {"current_phase": self._phase, "cycle_id": "test-cycle"}


def _make_engine(**kwargs):
    return PricingEngine(persistence=MemFile(), **kwargs)


def _init(eng, orc, pid="prod-a", base=100.0, rpm_ref=50.0):
    eng.initialize_product(pid, base_price=base, rpm_base_reference=rpm_ref, orchestrator=orc)


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

def t1_offensive_increase():
    """Offensive +25% sets new price correctly and emits event."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ml  = MockMarketLoop(phase=4)
    gs  = GlobalState(MemFile())

    _init(eng, orc, base=100.0)
    rec = eng.apply_offensive_increase("prod-a", orc, global_state=gs, market_loop=ml)

    expected = round(100.0 * 1.25, 4)
    assert rec["current_price"] == expected, (
        f"Expected {expected}, got {rec['current_price']}"
    )
    assert rec["offensive_increases_count"] == 1, "offensive counter should be 1"

    types = [e["event_type"] for e in bus.get_events()]
    assert "pricing_offensive_applied" in types, "Event 'pricing_offensive_applied' not in ledger"


def t2_defensive_reduction():
    """Defensive -15% sets new price and resets offensive counter."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ml  = MockMarketLoop(phase=4)
    gs  = GlobalState(MemFile())

    _init(eng, orc, base=80.0)
    # Apply one offensive first
    eng.apply_offensive_increase("prod-a", orc, global_state=gs, market_loop=ml)
    assert eng.get_record("prod-a")["offensive_increases_count"] == 1

    # Now defensive
    rec = eng.apply_defensive_reduction("prod-a", orc, global_state=gs, market_loop=ml)
    expected = round(80.0 * 1.25 * 0.85, 4)
    assert rec["current_price"] == expected, (
        f"Expected {expected}, got {rec['current_price']}"
    )
    assert rec["offensive_increases_count"] == 0, "offensive counter must reset after defensive"

    types = [e["event_type"] for e in bus.get_events()]
    assert "pricing_defensive_applied" in types, "Event 'pricing_defensive_applied' not in ledger"


def t3_cannot_go_below_base():
    """Defensive reduction blocked when result < base_price."""
    eng = _make_engine(defensive_multiplier=0.85)
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ml  = MockMarketLoop(phase=4)
    gs  = GlobalState(MemFile())

    # base=100, current already at 105 (one offensive), then try to reduce
    # Set a very low base that would cause the defensive check to trigger
    # instead: initialize at base=100, apply defensive from base with no prior increase
    # 100 * 0.85 = 85 which is still > 0, so use a contrived case:
    # set base=100 and current_price == base (no room to go down)
    _init(eng, orc, base=100.0)
    # Force current_price to exactly base via direct internal manipulation (test only)
    eng._state["prod-a"]["current_price"] = 100.0
    eng._pers.save(eng._state)

    # 100 * 0.85 = 85 < base (100)? No, 85 < 100 YES → PricingBelowBaseError
    raised = False
    try:
        eng.apply_defensive_reduction("prod-a", orc, global_state=gs, market_loop=ml)
    except PricingBelowBaseError:
        raised = True
    assert raised, "Expected PricingBelowBaseError when reduction goes below base_price"


def t4_offensive_limit_3():
    """After 3 offensive increases, a 4th raises PricingOffensiveLimitError."""
    eng = _make_engine(max_offensive_increases=3)
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ml  = MockMarketLoop(phase=4)
    gs  = GlobalState(MemFile())

    _init(eng, orc, base=1.0, rpm_ref=0.5)   # small base so price stays above 1.0

    # Apply 3 offensives
    for _ in range(3):
        eng.apply_offensive_increase("prod-a", orc, global_state=gs, market_loop=ml)
    assert eng.get_record("prod-a")["offensive_increases_count"] == 3

    raised = False
    try:
        eng.apply_offensive_increase("prod-a", orc, global_state=gs, market_loop=ml)
    except PricingOffensiveLimitError:
        raised = True
    assert raised, "Expected PricingOffensiveLimitError on 4th consecutive offensive"


def t5_phase_4_gate():
    """Price changes blocked when Market Loop is not in FASE_4."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ml  = MockMarketLoop(phase=2)   # wrong phase
    gs  = GlobalState(MemFile())

    _init(eng, orc, base=100.0)

    raised_off = False
    try:
        eng.apply_offensive_increase("prod-a", orc, global_state=gs, market_loop=ml)
    except PricingPhaseViolationError:
        raised_off = True

    raised_def = False
    try:
        eng.apply_defensive_reduction("prod-a", orc, global_state=gs, market_loop=ml)
    except PricingPhaseViolationError:
        raised_def = True

    assert raised_off, "Expected PricingPhaseViolationError for offensive outside phase 4"
    assert raised_def, "Expected PricingPhaseViolationError for defensive outside phase 4"


def t6_rollback_on_statistical_loss():
    """Auto-rollback executes when post-change margin drops > 10%."""
    eng = _make_engine(rollback_margin_thr=0.10)
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ml  = MockMarketLoop(phase=4)
    gs  = GlobalState(MemFile())

    _init(eng, orc, base=100.0)
    # Apply one offensive so there's a history entry
    eng.apply_offensive_increase("prod-a", orc, global_state=gs, market_loop=ml)
    price_after_offensive = eng.get_record("prod-a")["current_price"]

    # Simulate: before offensive margin=0.50, after offensive margin=0.35 → drop=0.15 > 0.10
    pre_snap  = {"margin": 0.50, "roas": 3.0}
    post_snap = {"margin": 0.35, "roas": 2.8}

    result = eng.evaluate_pricing_performance("prod-a", pre_snap, post_snap, orc)
    assert result["rolled_back"] is True, "Expected rollback on margin drop > 10%"

    restored = eng.get_record("prod-a")["current_price"]
    assert restored < price_after_offensive, (
        f"Restored price {restored} should be less than post-offensive price {price_after_offensive}"
    )
    assert eng.get_record("prod-a")["offensive_increases_count"] == 0, (
        "offensive counter must reset after rollback"
    )

    types = [e["event_type"] for e in bus.get_events()]
    assert "pricing_rollback_executed" in types, "Event 'pricing_rollback_executed' not in ledger"


def t7_containment_blocks_pricing():
    """CONTENÇÃO_FINANCEIRA blocks both offensive and defensive pricing."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ml  = MockMarketLoop(phase=4)

    gs = GlobalState(MemFile())
    gs.request_state_update(CONTENCAO_FINANCEIRA, bus, "test containment", source="test", orchestrated=False)

    _init(eng, orc, base=100.0)

    raised_off = False
    try:
        eng.apply_offensive_increase("prod-a", orc, global_state=gs, market_loop=ml)
    except PricingContainmentError:
        raised_off = True

    raised_def = False
    try:
        eng.apply_defensive_reduction("prod-a", orc, global_state=gs, market_loop=ml)
    except PricingContainmentError:
        raised_def = True

    assert raised_off, "Expected PricingContainmentError for offensive during CONTENÇÃO"
    assert raised_def, "Expected PricingContainmentError for defensive during CONTENÇÃO"


def t8_direct_write_fails():
    """StateManager.set() directly raises DirectWriteError."""
    sm = StateManager()
    raised = False
    try:
        sm.set("product_price", 19.99)
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A7 PRICING ENGINE — TEST SUITE")
    print("=" * 62)

    test("Offensive +25% applied correctly",        t1_offensive_increase)
    test("Defensive −15% applied correctly",        t2_defensive_reduction)
    test("Price cannot go below base_price",        t3_cannot_go_below_base)
    test("Blocked after 3 offensive increases",     t4_offensive_limit_3)
    test("Blocked outside FASE_4",                  t5_phase_4_gate)
    test("Rollback on statistical loss > 10%",      t6_rollback_on_statistical_loss)
    test("CONTENÇÃO_FINANCEIRA blocks pricing",     t7_containment_blocks_pricing)
    test("DirectWriteError outside Orchestrator",   t8_direct_write_fails)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A7 PRICING ENGINE — VALID")
        print("  A7 PRICING GOVERNANCE LOCKED")
    else:
        print("  A7 PRICING ENGINE — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
