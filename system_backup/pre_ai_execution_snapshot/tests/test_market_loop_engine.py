"""
tests/test_market_loop_engine.py — A6 Market Loop Engine Validation Suite

9 closure criteria:
  1. Non-Ativo product cannot start cycle
  2. Phase out of order raises MarketLoopPhaseOrderError
  3. cycle_id is unique per cycle
  4. Substitution only with real improvement (RPM or ROAS↑)
  5. No improvement → baseline unchanged
  6. Rollback executed on post-substitution regression
  7. New cycle blocked while previous is open (microcycle)
  8. GlobalState CONTENÇÃO blocks cycle start
  9. DirectWriteError outside Orchestrator

Usage:
    py tests/test_market_loop_engine.py
"""
import sys
import os
import io
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus          import EventBus
from core.market_loop_engine import (
    MarketLoopEngine,
    MarketLoopPhaseOrderError,
    MarketLoopProductStateError,
    MarketLoopMicrocycleError,
    PHASES,
)
from core.state_manager      import StateManager, DirectWriteError
from core.global_state       import GlobalState, CONTENCAO_FINANCEIRA

# ====================================================================
# Stubs
# ====================================================================

class MemFile:
    def __init__(self, initial=None):
        import copy
        self._d = copy.deepcopy(initial) if initial else {}
    def load(self):
        import copy
        return copy.deepcopy(self._d)
    def save(self, data):
        import copy
        self._d = copy.deepcopy(data)


class MockOrchestrator:
    def __init__(self, event_bus):
        self._bus = event_bus
        self.received = []
    def emit_event(self, event_type, payload, source=None, product_id=None, month_id=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload":    payload,
            "source":     source,
            "product_id": product_id,
            "month_id":   month_id
        })
    def receive_event(self, event_type, payload):
        self.received.append({"event_type": event_type, "payload": payload})


class MockStateManager:
    """Returns a configurable product state for any product_id."""
    def __init__(self, product_state: str = "Ativo"):
        self._state = product_state
    def get(self, key):
        if key == "product_states":
            # Return a defaultdict-like behaviour: any product_id returns _state
            return _AnyKeyDict(self._state)
        return None


class _AnyKeyDict:
    """Dict-like that returns the same value for any key."""
    def __init__(self, value):
        self._v = value
    def get(self, key, default=None):
        return self._v



class MockTelemetry:
    """Returns a configurable snapshot."""
    def __init__(self, rpm=2.0, roas=2.5, margin=0.4, version=1, snap_id="snap-123"):
        self._s = {
            "snapshot_id":    snap_id,
            "rpm":            rpm,
            "roas":           roas,
            "margin":         margin,
            "version_number": version
        }
    def get_latest_snapshot(self, product_id):
        return dict(self._s)


class MockVersionManager:
    """Records promote/rollback calls."""
    def __init__(self):
        self.promoted = []
        self.rolled   = []
    def promote_version(self, product_id, event_bus):
        v = {"version_id": f"v-promoted-{len(self.promoted)+1}"}
        self.promoted.append(v)
        return v
    def rollback_version(self, product_id, event_bus):
        v = {"version_id": "v-rollback"}
        self.rolled.append(v)
        return v


def _make_engine(min_rpm=0.0, min_roas=0.0, max_margin_deg=0.05, rollback_thr=0.10):
    return MarketLoopEngine(
        persistence=MemFile(),
        min_rpm_improvement=min_rpm,
        min_roas_improvement=min_roas,
        max_margin_degradation=max_margin_deg,
        rollback_loss_threshold=rollback_thr,
    )

# ====================================================================
# Runner
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

def t1_non_ativo_blocked():
    """Non-Ativo product cannot start Market Loop cycle."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    sm  = MockStateManager(product_state="Inativo")
    gs  = GlobalState(MemFile())

    raised = False
    try:
        eng.start_new_cycle("prod-1", orc, state_manager=sm, global_state=gs)
    except MarketLoopProductStateError:
        raised = True
    assert raised, "Expected MarketLoopProductStateError for non-Ativo product."


def t2_phase_order_enforced():
    """Phase out of order raises MarketLoopPhaseOrderError."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    sm  = MockStateManager("Ativo")
    gs  = GlobalState(MemFile())

    eng.start_new_cycle("prod-2", orc, state_manager=sm, global_state=gs)

    # Skip FASE_1 and try to execute FASE_2 directly
    raised = False
    try:
        eng.execute_phase("prod-2", 2, orc)   # should fail — FASE_1 not done
    except MarketLoopPhaseOrderError:
        raised = True
    assert raised, "Expected MarketLoopPhaseOrderError when skipping phase."

    # Also test repeat: execute FASE_1 then try again
    eng2 = _make_engine()
    bus2 = EventBus()
    orc2 = MockOrchestrator(bus2)
    eng2.start_new_cycle("prod-2b", orc2, state_manager=sm, global_state=gs)
    eng2.execute_phase("prod-2b", 1, orc2)
    # Mark phase 1 as completed manually so evaluate can work
    cycle = eng2._find_open_cycle("prod-2b")
    cycle["phases_completed"].append(1)
    eng2._save()

    raised2 = False
    try:
        eng2.execute_phase("prod-2b", 1, orc2)  # repeat — should fail
    except MarketLoopPhaseOrderError:
        raised2 = True
    assert raised2, "Expected MarketLoopPhaseOrderError when repeating phase."


def t3_cycle_id_unique():
    """Each new cycle generates a unique cycle_id."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    sm  = MockStateManager("Ativo")
    gs  = GlobalState(MemFile())

    c1 = eng.start_new_cycle("prod-3", orc, state_manager=sm, global_state=gs)
    # Close cycle 1
    eng.close_cycle("prod-3", orc)

    c2 = eng.start_new_cycle("prod-3", orc, state_manager=sm, global_state=gs)
    assert c1["cycle_id"] != c2["cycle_id"], (
        f"cycle_ids must be unique: got '{c1['cycle_id']}' vs '{c2['cycle_id']}'"
    )

    # Both cycle_ids must appear in ledger events
    events = bus.get_events()
    cycle_started = [e for e in events if e["event_type"] == "market_cycle_started"]
    ids = {e["payload"]["cycle_id"] for e in cycle_started}
    assert c1["cycle_id"] in ids, "cycle_id of first cycle not in ledger"
    assert c2["cycle_id"] in ids, "cycle_id of second cycle not in ledger"


def t4_substitution_only_with_improvement():
    """Substitution only occurs when RPM or ROAS shows real improvement."""
    eng = _make_engine(min_rpm=0.1, min_roas=0.0, max_margin_deg=0.05)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    baseline = {"rpm": 1.0, "roas": 2.0, "margin": 0.4, "version_number": 1}
    # Current snapshot: RPM improved by 0.5 (> 0.1), margin same
    current_tm = MockTelemetry(rpm=1.5, roas=2.1, margin=0.4, version=2)

    # Start cycle so there's an open cycle for the method
    sm = MockStateManager("Ativo")
    gs = GlobalState(MemFile())
    eng.start_new_cycle("prod-4", orc, state_manager=sm, global_state=gs)

    result = eng.apply_substitution_if_valid(
        "prod-4", orc, current_tm, baseline_snapshot=baseline
    )
    assert result["substituted"] is True, (
        f"Expected substitution, got: {result}"
    )
    assert len(orc.received) == 1, "Orchestrator.receive_event should have been called once."
    assert orc.received[0]["event_type"] == "version_promotion_requested"

    types = [e["event_type"] for e in bus.get_events()]
    assert "baseline_replaced" in types, "Expected baseline_replaced in ledger."


def t5_no_improvement_baseline_unchanged():
    """No improvement → no substitution, baseline unchanged, no baseline_replaced event."""
    eng = _make_engine(min_rpm=0.1, min_roas=0.1, max_margin_deg=0.05)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    baseline   = {"rpm": 2.0, "roas": 3.0, "margin": 0.5, "version_number": 1}
    # Worse than baseline
    current_tm = MockTelemetry(rpm=1.5, roas=2.5, margin=0.45, version=2)

    sm = MockStateManager("Ativo")
    gs = GlobalState(MemFile())
    eng.start_new_cycle("prod-5", orc, state_manager=sm, global_state=gs)

    result = eng.apply_substitution_if_valid(
        "prod-5", orc, current_tm, baseline_snapshot=baseline
    )
    assert result["substituted"] is False, (
        f"Expected NO substitution, got: {result}"
    )
    assert len(orc.received) == 0, "Orchestrator.receive_event should NOT have been called."

    types = [e["event_type"] for e in bus.get_events()]
    assert "baseline_replaced" not in types, "baseline_replaced should NOT be in ledger."


def t6_rollback_on_regression():
    """Rollback executes when post-substitution margin drops beyond threshold."""
    eng = _make_engine(rollback_thr=0.10)  # 10% margin drop triggers rollback
    bus = EventBus()
    orc = MockOrchestrator(bus)

    # Pre-substitution snapshot: margin=0.45
    pre_snap    = {"rpm": 2.0, "roas": 3.0, "margin": 0.45, "version_number": 2}
    # Post-substitution: margin dropped 0.15 → regression
    post_tm     = MockTelemetry(rpm=1.8, roas=2.8, margin=0.30, version=3)

    sm = MockStateManager("Ativo")
    gs = GlobalState(MemFile())
    eng.start_new_cycle("prod-6", orc, state_manager=sm, global_state=gs)

    result = eng.rollback_if_loss("prod-6", orc, post_tm, pre_substitution_snapshot=pre_snap)
    assert result["rolled_back"] is True, (
        f"Expected rollback, got: {result}"
    )
    assert len(orc.received) == 1, "Orchestrator.receive_event should have been called."
    assert orc.received[0]["event_type"] == "version_rollback_requested"

    types = [e["event_type"] for e in bus.get_events()]
    assert "market_rollback_executed" in types, "market_rollback_executed not in ledger."


def t7_microcycle_blocked():
    """New cycle is rejected if a previous cycle is still open."""
    eng = _make_engine()
    bus = EventBus()
    orc = MockOrchestrator(bus)
    sm  = MockStateManager("Ativo")
    gs  = GlobalState(MemFile())

    eng.start_new_cycle("prod-7", orc, state_manager=sm, global_state=gs)

    raised = False
    try:
        eng.start_new_cycle("prod-7", orc, state_manager=sm, global_state=gs)
    except MarketLoopMicrocycleError:
        raised = True
    assert raised, "Expected MarketLoopMicrocycleError when previous cycle still open."


def t8_containment_blocks_cycle():
    """GlobalState CONTENÇÃO_FINANCEIRA blocks cycle start."""
    eng = _make_engine()
    bus = EventBus()
    sm  = MockStateManager("Ativo")

    gs = GlobalState(MemFile())
    gs.request_state_update(CONTENCAO_FINANCEIRA, bus, "test setup", source="test", orchestrated=False)

    orc = MockOrchestrator(bus)
    raised = False
    try:
        eng.start_new_cycle("prod-8", orc, state_manager=sm, global_state=gs)
    except MarketLoopProductStateError:
        raised = True
    assert raised, "Expected MarketLoopProductStateError when GlobalState is CONTENÇÃO_FINANCEIRA."


def t9_direct_write_fails():
    """StateManager.set() directly raises DirectWriteError."""
    sm = StateManager()
    raised = False
    try:
        sm.set("product_price", 9.99)
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write."


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A6 MARKET LOOP ENGINE — TEST SUITE")
    print("=" * 62)

    test("Non-Ativo product cannot start cycle",           t1_non_ativo_blocked)
    test("Phase out of order raises PhaseOrderError",      t2_phase_order_enforced)
    test("cycle_id is unique per cycle",                   t3_cycle_id_unique)
    test("Substitution only with real improvement",        t4_substitution_only_with_improvement)
    test("No improvement → baseline unchanged",            t5_no_improvement_baseline_unchanged)
    test("Rollback executed on post-substitution loss",    t6_rollback_on_regression)
    test("Microcycle blocked (open cycle exists)",         t7_microcycle_blocked)
    test("CONTENÇÃO_FINANCEIRA blocks cycle start",        t8_containment_blocks_cycle)
    test("DirectWriteError outside Orchestrator",          t9_direct_write_fails)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A6 MARKET LOOP ENGINE — VALID")
        print("  MARKET OPTIMIZATION GOVERNED")
    else:
        print("  A6 MARKET LOOP ENGINE — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
