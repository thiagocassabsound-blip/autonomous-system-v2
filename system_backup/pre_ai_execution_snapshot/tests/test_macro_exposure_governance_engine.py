"""
tests/test_macro_exposure_governance_engine.py — Bloco 29 Validation Suite

10 closure criteria:
  1.  Blocks when product exposure > base limit
  2.  Blocks when channel exposure > base limit
  3.  Blocks when global exposure > base limit
  4.  Allows within limits
  5.  Activates adaptive limits when criteria met
  6.  Reverts to base when criteria lost
  7.  No write outside Orchestrator (DirectWriteError)
  8.  Direct execution raises error
  9.  Adaptive not allowed during financial alert
 10.  Append-only persistence verified

Usage:
    py tests/test_macro_exposure_governance_engine.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus import EventBus
from core.macro_exposure_governance_engine import (
    MacroExposureGovernanceEngine,
    MacroExposureDirectExecutionError,
    _is_adaptive_eligible,
    _compute_projections,
)
from core.state_manager import StateManager, DirectWriteError


# ====================================================================
# In-memory stubs
# ====================================================================

class MemExposurePersistence:
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

def _make_engine(orchestrator=None, persistence=None):
    if orchestrator is None:
        orchestrator = MockOrchestrator(EventBus())
    return MacroExposureGovernanceEngine(
        orchestrator=orchestrator,
        persistence=persistence or MemExposurePersistence()
    )


# Convenience wrapper: total_capital=1000, all current allocations=0
def _validate(
    engine,
    bus,
    product_id="prod-1",
    channel_id="ch-1",
    requested_allocation=100.0,
    current_product_allocation=0.0,
    current_channel_allocation=0.0,
    current_global_allocation=0.0,
    total_capital=1000.0,
    roas_avg=3.0,
    score_global=90.0,
    refund_ratio_avg=0.05,
    global_state="NORMAL",
    financial_alert_active=False,
):
    return engine.validate_macro_exposure(
        product_id=product_id,
        channel_id=channel_id,
        requested_allocation=requested_allocation,
        current_product_allocation=current_product_allocation,
        current_channel_allocation=current_channel_allocation,
        current_global_allocation=current_global_allocation,
        total_capital=total_capital,
        roas_avg=roas_avg,
        score_global=score_global,
        refund_ratio_avg=refund_ratio_avg,
        global_state=global_state,
        financial_alert_active=financial_alert_active,
    )


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

def t1_blocks_product_exposure():
    """Blocks when (current_product + request) / capital > 20% (base limit)."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
    # capital=1000, current_product=0, request=210 → projected_product=0.21 > 0.20
    result = _validate(
        eng, bus,
        requested_allocation=210.0,
        current_product_allocation=0.0,
        total_capital=1000.0,
        # Use non-adaptive settings so base limits apply
        roas_avg=1.0, score_global=70.0, refund_ratio_avg=0.3,
        global_state="ALERTA",
    )
    assert result["allowed"] is False, f"Expected blocked, got {result}"
    assert "product" in " ".join(result.get("violations", [])), \
        f"Expected product violation, got {result['violations']}"
    evts = [e["event_type"] for e in bus.get_events()]
    assert "macro_exposure_blocked" in evts


def t2_blocks_channel_exposure():
    """Blocks when (current_channel + request) / capital > 40% (base limit)."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
    # projected_channel = 0 + 410 / 1000 = 0.41 > 0.40
    result = _validate(
        eng, bus,
        requested_allocation=410.0,
        current_channel_allocation=0.0,
        total_capital=1000.0,
        roas_avg=1.0, score_global=70.0, refund_ratio_avg=0.3,
        global_state="ALERTA",
    )
    assert result["allowed"] is False
    assert "channel" in " ".join(result.get("violations", [])), \
        f"Expected channel violation, got {result['violations']}"
    evts = [e["event_type"] for e in bus.get_events()]
    assert "macro_exposure_blocked" in evts


def t3_blocks_global_exposure():
    """Blocks when (current_global + request) / capital > 60% (base limit)."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
    # projected_global = 0 + 610 / 1000 = 0.61 > 0.60
    result = _validate(
        eng, bus,
        requested_allocation=610.0,
        current_global_allocation=0.0,
        total_capital=1000.0,
        roas_avg=1.0, score_global=70.0, refund_ratio_avg=0.3,
        global_state="ALERTA",
    )
    assert result["allowed"] is False
    assert "global" in " ".join(result.get("violations", [])), \
        f"Expected global violation, got {result['violations']}"


def t4_allows_within_limits():
    """Allows when all projected exposures are within base limits."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
    # request=100 / capital=1000 → each projected = 0.10 < all base limits
    result = _validate(
        eng, bus,
        requested_allocation=100.0,
        total_capital=1000.0,
        roas_avg=1.0, score_global=70.0, refund_ratio_avg=0.3,
        global_state="ALERTA",
    )
    assert result["allowed"] is True, f"Expected allowed, got {result}"
    evts = [e["event_type"] for e in bus.get_events()]
    assert "macro_exposure_validated" in evts


def t5_adaptive_limits_activated():
    """Adaptive limits are used (30/50/70%) when all criteria are met."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
    # request=280 / capital=1000 → projected_product=0.28 which > base (0.20)
    # but ≤ adaptive (0.30) → should be ALLOWED under adaptive mode
    result = _validate(
        eng, bus,
        requested_allocation=280.0,
        total_capital=1000.0,
        roas_avg=2.5, score_global=90.0, refund_ratio_avg=0.05,
        global_state="NORMAL", financial_alert_active=False,
    )
    assert result["allowed"] is True, \
        f"Expected adaptive mode to allow 0.28 product exposure, got {result}"
    assert result["adaptive_mode"] is True
    assert result["active_limits"]["mode"] == "adaptive"
    evts = [e["event_type"] for e in bus.get_events()]
    assert "macro_exposure_adapted" in evts or "macro_exposure_validated" in evts


def t6_reverts_to_base_when_criteria_lost():
    """Reverts from adaptive to base limits when conditions are no longer met."""
    bus  = EventBus()
    orc  = MockOrchestrator(bus)
    pers = MemExposurePersistence()
    eng  = _make_engine(orchestrator=orc, persistence=pers)
 
    # First call: adaptive mode activated
    _validate(
        eng, bus, product_id="p1",
        requested_allocation=100.0, total_capital=1000.0,
        roas_avg=2.5, score_global=90.0, refund_ratio_avg=0.05,
        global_state="NORMAL", financial_alert_active=False,
    )
    assert eng._last_adaptive.get("p1") is True
 
    # Second call: criteria lost (score drops, alert fires)
    bus2 = EventBus()
    _validate(
        eng, bus2, product_id="p1",
        requested_allocation=100.0, total_capital=1000.0,
        roas_avg=1.5, score_global=70.0, refund_ratio_avg=0.2,
        global_state="ALERTA", financial_alert_active=True,
    )
    assert eng._last_adaptive.get("p1") is False
    evts2 = [e["event_type"] for e in bus2.get_events()]
    assert "macro_exposure_reverted" in evts2, \
        f"Expected revert event, got {evts2}"


def t7_no_write_outside_orchestrator():
    """StateManager.set() raises DirectWriteError — confirms write governance."""
    sm = StateManager()
    raised = False
    try:
        sm.set("macro_bypass", {"inject": True})
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


def t8_direct_execution_raises():
    """Both execution guards raise MacroExposureDirectExecutionError."""
    # Static guard
    raised_direct = False
    try:
        MacroExposureGovernanceEngine.execute_directly()
    except MacroExposureDirectExecutionError:
        raised_direct = True
    assert raised_direct, "execute_directly() must raise"

    # Instance guard
    eng = _make_engine()
    raised_alloc = False
    try:
        eng.modify_allocation()
    except MacroExposureDirectExecutionError:
        raised_alloc = True
    assert raised_alloc, "modify_allocation() must raise"


def t9_adaptive_blocked_during_financial_alert():
    """financial_alert_active=True prevents adaptive mode regardless of other criteria."""
    eligible = _is_adaptive_eligible(
        roas_avg=3.0,
        score_global=90.0,
        refund_ratio_avg=0.05,
        global_state="NORMAL",
        financial_alert_active=True,   # ← alert active
    )
    assert eligible is False, "financial_alert should block adaptive mode"

    # Verify via full engine: request 280 / 1000 = 0.28 → base limit is 0.20, blocked
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)
    result = _validate(
        eng, bus,
        requested_allocation=280.0,
        total_capital=1000.0,
        roas_avg=3.0, score_global=90.0, refund_ratio_avg=0.05,
        global_state="NORMAL", financial_alert_active=True,
    )
    assert result["allowed"] is False, \
        f"With alert active, 0.28 should be blocked by base limit 0.20, got {result}"
    assert result["active_limits"]["mode"] == "base"


def t10_append_only_persistence():
    """Audit records accumulate monotonically; count never decreases."""
    bus  = EventBus()
    orc  = MockOrchestrator(bus)
    pers = MemExposurePersistence()
    eng  = _make_engine(orchestrator=orc, persistence=pers)
 
    count_0 = len(pers.load_all())

    _validate(eng, bus, product_id="x1", requested_allocation=50.0, total_capital=1000.0)
    count_1 = len(pers.load_all())
    assert count_1 > count_0

    _validate(eng, bus, product_id="x2", requested_allocation=80.0, total_capital=1000.0)
    count_2 = len(pers.load_all())
    assert count_2 > count_1

    # Same product, second validation also appends
    _validate(eng, bus, product_id="x1", requested_allocation=30.0, total_capital=1000.0)
    count_3 = len(pers.load_all())
    assert count_3 > count_2

    # Monotonicity
    for a, b in zip([count_0, count_1, count_2], [count_1, count_2, count_3]):
        assert b >= a


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 66)
    print("  BLOCO 29 MACRO EXPOSURE GOVERNANCE ENGINE — TEST SUITE")
    print("=" * 66)

    test("Blocks when product exposure > base limit",       t1_blocks_product_exposure)
    test("Blocks when channel exposure > base limit",       t2_blocks_channel_exposure)
    test("Blocks when global exposure > base limit",        t3_blocks_global_exposure)
    test("Allows within limits",                            t4_allows_within_limits)
    test("Activates adaptive limits when criteria met",     t5_adaptive_limits_activated)
    test("Reverts to base when criteria lost",              t6_reverts_to_base_when_criteria_lost)
    test("No write outside Orchestrator",                   t7_no_write_outside_orchestrator)
    test("Direct execution raises error",                   t8_direct_execution_raises)
    test("Adaptive not allowed during financial alert",     t9_adaptive_blocked_during_financial_alert)
    test("Append-only persistence verified",                t10_append_only_persistence)

    print("\n" + "=" * 66)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  BLOCO 29 MACRO EXPOSURE GOVERNANCE ENGINE — VALID")
        print("  BLOCO 29 LOCKED")
    else:
        print("  BLOCO 29 — INVALID (see failures above)")
    print("=" * 66 + "\n")

    sys.exit(0 if passed == total else 1)
