"""
tests/test_product_life_engine.py — A5 Product Life Engine Validation Suite

9 closure criteria:
  1. Beta starts correctly (timestamps + ledger event)
  2. Beta cannot close before 7 days (BetaWindowViolationError)
  3. beta_window_closed emitted after 7 days
  4. Consolidation fails without Telemetry snapshot
  5. Eligible product transitions to Ativo
  6. Non-eligible product transitions to Inativo
  7. ensure_no_product_in_limbo detects expired-but-unclosed beta
  8. Direct write to StateManager raises DirectWriteError
  9. GlobalState CONTENÇÃO_FINANCEIRA blocks consolidation

Usage:
    py tests/test_product_life_engine.py
"""
import sys
import os
import io
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus           import EventBus
from core.product_life_engine import (
    ProductLifeEngine,
    BetaWindowViolationError,
    ProductLifecycleIntegrityError,
    ConsolidationPreconditionError,
    BETA_WINDOW_DAYS,
)
from core.state_manager       import StateManager, DirectWriteError
from core.global_state        import GlobalState, CONTENCAO_FINANCEIRA

# ====================================================================
# In-memory stubs
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


class MockTelemetry:
    """Returns a fake snapshot with configurable KPIs."""
    def __init__(self, rpm=2.0, roas=2.5, margin=0.4, has_snapshot=True):
        self._rpm    = rpm
        self._roas   = roas
        self._margin = margin
        self._has    = has_snapshot

    def get_latest_snapshot(self, product_id):
        if not self._has:
            return None
        return {
            "snapshot_id":    "snap-test-001",
            "version_number": 1,
            "cycle_id":       "cycle-test-001",
            "product_id":     product_id,
            "rpm":            self._rpm,
            "roas":           self._roas,
            "margin":         self._margin,
        }


class MockStateMachine:
    """Records the last transition call."""
    def __init__(self):
        self.last_transition = None

    def transition(self, product_id, to_state, reason, metric, orchestrator):
        self.last_transition = {"product_id": product_id, "to_state": to_state}
        orchestrator.emit_event(
            event_type="state_transitioned",
            product_id=product_id,
            payload={"to": to_state, "reason": reason}
        )
        return self.last_transition

class MockOrchestrator:
    def __init__(self, bus):
        self._bus = bus
    def emit_event(self, event_type, payload, product_id=None, source=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload":    payload,
            "product_id": product_id,
            "source":     source or "system"
        })


# ====================================================================
# Helpers
# ====================================================================

def _make(now_fn=None, min_rpm=0.5, min_roas=1.2, min_margin=0.1):
    bus = EventBus()
    orc = MockOrchestrator(bus)
    ple = ProductLifeEngine(
        persistence=MemFile(),
        min_rpm=min_rpm,
        min_roas=min_roas,
        min_margin=min_margin,
        now_fn=now_fn,
    )
    return ple, orc

def _future(days=BETA_WINDOW_DAYS + 1):
    """Return a now_fn that always returns `days` after a fixed epoch."""
    epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def _now():
        return epoch + timedelta(days=days)
    return _now, epoch

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

def t1_beta_starts():
    """start_beta sets timestamps and emits beta_started."""
    ple, orc = _make()
    rec = ple.start_beta("prod-1", orc, orchestrated=True)

    assert "beta_start"   in rec, "beta_start missing"
    assert "beta_end"     in rec, "beta_end missing"
    assert rec["beta_closed_at"] is None

    # Ledger must contain beta_started
    bus = orc._bus
    types = [e["event_type"] for e in bus.get_events()]
    assert "beta_started" in types, f"beta_started not in ledger: {types}"

    # Payload must include beta_duration_days
    ev = next(e for e in bus.get_events() if e["event_type"] == "beta_started")
    assert ev["payload"]["beta_duration_days"] == BETA_WINDOW_DAYS


def t2_beta_no_early_close():
    """close_beta before 7 days must raise BetaWindowViolationError."""
    now_t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)

    # Engine thinks now = day 0
    t = [now_t0]
    def now_fn():
        return t[0]

    ple, orc = _make(now_fn=now_fn)
    ple.start_beta("prod-2", orc, orchestrated=True)

    # Advance to day 3 (before 7-day window)
    t[0] = now_t0 + timedelta(days=3)

    raised = False
    try:
        ple.close_beta("prod-2", orc)
    except BetaWindowViolationError:
        raised = True

    assert raised, "Expected BetaWindowViolationError on early close."


def t3_beta_window_closed():
    """After 7 days, check_beta_expiration emits beta_window_closed."""
    now_t0 = datetime(2026, 2, 1, tzinfo=timezone.utc)
    t = [now_t0]
    def now_fn():
        return t[0]

    ple, orc = _make(now_fn=now_fn)
    ple.start_beta("prod-3", orc, orchestrated=True)

    # Jump to day 8 (past window)
    t[0] = now_t0 + timedelta(days=8)

    closed = ple.check_beta_expiration("prod-3", orc)
    assert closed is True, "check_beta_expiration should return True after 7 days"

    bus = orc._bus
    types = [e["event_type"] for e in bus.get_events()]
    assert "beta_window_closed" in types, f"beta_window_closed not in ledger: {types}"

    ev = next(e for e in bus.get_events() if e["event_type"] == "beta_window_closed")
    p  = ev["payload"]
    assert p["product_id"]         == "prod-3"
    assert p["beta_duration_days"] == BETA_WINDOW_DAYS
    assert "closed_at"             in p


def t4_consolidation_needs_snapshot():
    """consolidate_post_beta without a telemetry snapshot must raise ConsolidationPreconditionError."""
    now_t0 = datetime(2026, 3, 1, tzinfo=timezone.utc)
    t = [now_t0]
    def now_fn():
        return t[0]

    ple, orc = _make(now_fn=now_fn)
    ple.start_beta("prod-4", orc, orchestrated=True)

    # Close beta after window
    t[0] = now_t0 + timedelta(days=8)
    ple.close_beta("prod-4", orc)

    # Telemetry with NO snapshot
    telemetry = MockTelemetry(has_snapshot=False)
    sm = MockStateMachine()
    gs = GlobalState(MemFile())

    raised = False
    try:
        ple.consolidate_post_beta("prod-4", orc, telemetry, sm, gs)
    except ConsolidationPreconditionError:
        raised = True

    assert raised, "Expected ConsolidationPreconditionError when no snapshot available."


def t5_eligible_to_ativo():
    """Good KPIs → classification=elegivel → StateMachine transitions to Ativo."""
    now_t0 = datetime(2026, 3, 10, tzinfo=timezone.utc)
    t = [now_t0]
    def now_fn():
        return t[0]

    ple, orc = _make(now_fn=now_fn, min_rpm=0.5, min_roas=1.2, min_margin=0.1)
    ple.start_beta("prod-5", orc, orchestrated=True)
    t[0] = now_t0 + timedelta(days=8)
    ple.close_beta("prod-5", orc)

    # High-performing snapshot
    telemetry = MockTelemetry(rpm=5.0, roas=3.0, margin=0.6)
    sm = MockStateMachine()
    gs = GlobalState(MemFile())

    result = ple.consolidate_post_beta("prod-5", orc, telemetry, sm, gs)

    assert result["classification"] == "elegivel", (
        f"Expected 'elegivel', got '{result['classification']}'"
    )
    assert sm.last_transition["to_state"] == "Ativo", (
        f"Expected 'Ativo', got '{sm.last_transition['to_state']}'"
    )

    bus = orc._bus
    types = [e["event_type"] for e in bus.get_events()]
    assert "post_beta_consolidated" in types, "post_beta_consolidated not in ledger"


def t6_not_eligible_to_inativo():
    """Zero KPIs → classification=nao_elegivel → StateMachine transitions to Inativo."""
    now_t0 = datetime(2026, 3, 20, tzinfo=timezone.utc)
    t = [now_t0]
    def now_fn():
        return t[0]

    ple, orc = _make(now_fn=now_fn, min_rpm=0.5, min_roas=1.2, min_margin=0.1)
    ple.start_beta("prod-6", orc, orchestrated=True)
    t[0] = now_t0 + timedelta(days=8)
    ple.close_beta("prod-6", orc)

    # Failing snapshot
    telemetry = MockTelemetry(rpm=0.0, roas=0.0, margin=0.0)
    sm = MockStateMachine()
    gs = GlobalState(MemFile())

    result = ple.consolidate_post_beta("prod-6", orc, telemetry, sm, gs)

    assert result["classification"] == "nao_elegivel", (
        f"Expected 'nao_elegivel', got '{result['classification']}'"
    )
    assert sm.last_transition["to_state"] == "Inativo", (
        f"Expected 'Inativo', got '{sm.last_transition['to_state']}'"
    )


def t7_no_product_in_limbo():
    """Beta expired but not closed → ensure_no_product_in_limbo raises error."""
    now_t0 = datetime(2026, 4, 1, tzinfo=timezone.utc)
    t = [now_t0]
    def now_fn():
        return t[0]

    ple, orc = _make(now_fn=now_fn)
    ple.start_beta("prod-7", orc, orchestrated=True)

    # Advance past window WITHOUT calling close_beta/check_beta_expiration
    t[0] = now_t0 + timedelta(days=10)

    raised = False
    try:
        ple.ensure_no_product_in_limbo()
    except ProductLifecycleIntegrityError:
        raised = True

    assert raised, (
        "Expected ProductLifecycleIntegrityError for expired-but-unclosed beta."
    )


def t8_direct_write_fails():
    """StateManager.set() directly must raise DirectWriteError (write lock active)."""
    sm = StateManager()
    raised = False
    try:
        sm.set("product_price", 99.99)
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write."


def t9_containment_blocks_consolidation():
    """GlobalState == CONTENÇÃO_FINANCEIRA blocks consolidate_post_beta."""
    now_t0 = datetime(2026, 4, 10, tzinfo=timezone.utc)
    t = [now_t0]
    def now_fn():
        return t[0]

    ple, orc = _make(now_fn=now_fn)
    ple.start_beta("prod-9", orc, orchestrated=True)
    t[0] = now_t0 + timedelta(days=8)
    ple.close_beta("prod-9", orc)

    telemetry = MockTelemetry(rpm=5.0, roas=3.0, margin=0.5)
    sm = MockStateMachine()

    # GlobalState in CONTENÇÃO
    gs = GlobalState(MemFile())
    gs.request_state_update(CONTENCAO_FINANCEIRA, orc._bus, "test setup", source="test", orchestrated=False)

    raised = False
    try:
        ple.consolidate_post_beta("prod-9", orc, telemetry, sm, gs)
    except ConsolidationPreconditionError:
        raised = True

    assert raised, (
        "Expected ConsolidationPreconditionError when GlobalState is CONTENÇÃO_FINANCEIRA."
    )


# ====================================================================
# Runner
# ====================================================================

if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A5 PRODUCT LIFE ENGINE — TEST SUITE")
    print("=" * 62)

    test("Beta starts correctly",                        t1_beta_starts)
    test("Beta cannot close before 7 days",              t2_beta_no_early_close)
    test("beta_window_closed emitted after 7 days",      t3_beta_window_closed)
    test("Consolidation fails without snapshot",         t4_consolidation_needs_snapshot)
    test("Eligible product transitions to Ativo",        t5_eligible_to_ativo)
    test("Non-eligible product transitions to Inativo",  t6_not_eligible_to_inativo)
    test("ensure_no_product_in_limbo detects limbo",     t7_no_product_in_limbo)
    test("DirectWriteError outside Orchestrator",        t8_direct_write_fails)
    test("CONTENÇÃO_FINANCEIRA blocks consolidation",    t9_containment_blocks_consolidation)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A5 PRODUCT LIFE ENGINE — VALID")
        print("  PRODUCT LIFE GOVERNANCE LOCKED")
    else:
        print("  A5 PRODUCT LIFE ENGINE — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
