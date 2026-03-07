"""
tests/test_finance_engine.py — A4 Finance Engine Validation Suite

Tests 7 closure criteria:
  1. Days-remaining projection correct
  2. credit_low_warning triggered at correct threshold
  3. credit_critical_warning triggered at correct threshold
  4. GlobalState changes correctly
  5. AUTO_RECHARGE emits formal event
  6. Orchestrator blocks sensitive action in CONTENÇÃO_FINANCEIRA
  7. No direct write outside Orchestrator (DirectWriteError)

Usage:
    py tests/test_finance_engine.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus       import EventBus
from core.global_state    import (
    GlobalState, NORMAL, ALERTA_FINANCEIRO, CONTENCAO_FINANCEIRA
)
from core.finance_engine  import FinanceEngine, _INF_DAYS
from core.state_manager   import StateManager, DirectWriteError
from core.orchestrator    import Orchestrator, FinancialContainmentError

# ====================================================================
# Minimal in-memory persistence stubs
# ====================================================================

class MemFile:
    def __init__(self, initial=None):
        self._data = initial or {}
    def load(self):
        import copy
        return copy.deepcopy(self._data)
    def save(self, data):
        import copy
        self._data = copy.deepcopy(data)

class MemAppend:
    def __init__(self):
        self._data = []
    def load(self):
        return list(self._data)
    def append(self, item):
        self._data.append(dict(item))


class MockOrchestrator:
    """Simulates Orchestrator gateway for finance tests."""
    def __init__(self, event_bus, global_state=None):
        self._bus = event_bus
        self._gs = global_state
    def emit_event(self, event_type, payload, source=None, product_id=None, month_id=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload":    payload,
            "source":     source,
            "product_id": product_id,
            "month_id":   month_id
        })
    def set_global_state(self, new_value, reason="Mock"):
        if self._gs:
            self._gs.request_state_update(
                new_value, 
                event_bus=self._bus, 
                reason=reason, 
                source="mock_orchestrator", 
                orchestrated=True
            )

# ====================================================================
# Runner
# ====================================================================
results = []

def test(name: str, fn) -> None:
    try:
        fn()
        results.append(("[OK]", name))
        print(f"  [OK]  {name}")
    except AssertionError as e:
        results.append(("[FAIL]", name))
        print(f"  [FAIL] {name}")
        print(f"         AssertionError: {e}")
    except Exception as e:
        results.append(("[FAIL]", name))
        print(f"  [FAIL] {name}")
        print(f"         {type(e).__name__}: {e}")


def _make(min_buffer=14, auto_recharge=False, avg_window=7):
    bus = EventBus()
    gs  = GlobalState(MemFile())
    fe  = FinanceEngine(
        state_persistence=MemFile(),
        projection_persistence=MemAppend(),
        global_state=gs,
        min_buffer_days=min_buffer,
        auto_recharge_enabled=auto_recharge,
        moving_avg_days=avg_window,
    )
    orc = MockOrchestrator(bus, gs)
    return fe, gs, orc


# ====================================================================
# TEST 1 — Projection correct
# ====================================================================

def t1_projection_correct():
    """
    stripe=1000, openai=400, avg burn=100 (3 sessions) → days=14.0
    """
    fe, gs, orc = _make()
    fe.register_stripe_balance(1000.0, orc)
    fe.register_openai_balance(400.0, orc)
    # 3 ad-spend sessions: 80, 100, 120 → avg = 100
    for spend in [80, 100, 120]:
        fe.register_ad_spend(spend, orc)

    proj = fe.project_days_remaining(orc)
    assert proj["total_available"] == 1400.0, (
        f"Expected total=1400, got {proj['total_available']}"
    )
    assert proj["daily_burn"] == 100.0, (
        f"Expected burn=100, got {proj['daily_burn']}"
    )
    assert proj["days_remaining"] == 14.0, (
        f"Expected 14 days, got {proj['days_remaining']}"
    )


# ====================================================================
# TEST 2 — credit_low_warning at threshold
# ====================================================================

def t2_credit_low_warning():
    """
    With 500 balance, burn=50/day → 10 days ≤ buffer(14) → credit_low_warning.
    Must NOT trigger credit_critical_warning (10 > 7).
    """
    fe, gs, orc = _make(min_buffer=14)
    fe.register_stripe_balance(500.0, orc)
    fe.register_ad_spend(50.0, orc)   # burn=50, days=10

    fe.validate_financial_health(orc)

    types = [e["event_type"] for e in orc._bus.get_events()]
    assert "credit_low_warning" in types, (
        f"Expected credit_low_warning; got events: {types}"
    )
    assert "credit_critical_warning" not in types, (
        f"credit_critical_warning should NOT fire at 10 days (threshold=7)"
    )


# ====================================================================
# TEST 3 — credit_critical_warning at half-threshold
# ====================================================================

def t3_credit_critical_warning():
    """
    500 balance, burn=100 → 5 days ≤ buffer/2(7) → credit_critical_warning.
    """
    fe, gs, orc = _make(min_buffer=14)
    fe.register_stripe_balance(500.0, orc)
    fe.register_ad_spend(100.0, orc)  # burn=100, days=5

    fe.validate_financial_health(orc)

    types = [e["event_type"] for e in orc._bus.get_events()]
    assert "credit_critical_warning" in types, (
        f"Expected credit_critical_warning; got: {types}"
    )


# ====================================================================
# TEST 4 — GlobalState transitions correctly
# ====================================================================

def t4_global_state_transitions():
    """
    credit_low_warning  → ALERTA_FINANCEIRO
    credit_critical     → CONTENÇÃO_FINANCEIRA
    Normalized          → NORMAL
    """
    # Stage A — low warning
    fe_a, gs_a, orc_a = _make(min_buffer=14)
    fe_a.register_stripe_balance(500.0, orc_a)
    fe_a.register_ad_spend(50.0, orc_a)         # 10 days → LOW
    fe_a.validate_financial_health(orc_a)
    assert gs_a.get_state() == ALERTA_FINANCEIRO, (
        f"Expected ALERTA_FINANCEIRO, got {gs_a.get_state()}"
    )

    # Stage B — critical warning
    fe_b, gs_b, orc_b = _make(min_buffer=14)
    fe_b.register_stripe_balance(500.0, orc_b)
    fe_b.register_ad_spend(100.0, orc_b)        # 5 days → CRITICAL
    fe_b.validate_financial_health(orc_b)
    assert gs_b.get_state() == CONTENCAO_FINANCEIRA, (
        f"Expected CONTENÇÃO_FINANCEIRA, got {gs_b.get_state()}"
    )

    # Stage C — situation normalized
    fe_c, gs_c, orc_c = _make(min_buffer=14)
    fe_c.register_stripe_balance(10_000.0, orc_c)
    fe_c.register_ad_spend(50.0, orc_c)         # 200 days → NORMAL
    fe_c.validate_financial_health(orc_c)
    assert gs_c.get_state() == NORMAL, (
        f"Expected NORMAL, got {gs_c.get_state()}"
    )


# ====================================================================
# TEST 5 — AUTO_RECHARGE emits formal event
# ====================================================================

def t5_auto_recharge_event():
    """
    When auto_recharge_enabled=True and credit_critical fires,
    auto_recharge_triggered must appear in the ledger.
    """
    fe, gs, orc = _make(min_buffer=14, auto_recharge=True)
    fe.register_stripe_balance(300.0, orc)
    fe.register_ad_spend(100.0, orc)            # 3 days → CRITICAL

    fe.validate_financial_health(orc)

    types = [e["event_type"] for e in orc._bus.get_events()]
    assert "auto_recharge_triggered" in types, (
        f"Expected auto_recharge_triggered in ledger; got: {types}"
    )

    # The event must have required fields
    ev = next(e for e in orc._bus.get_events() if e["event_type"] == "auto_recharge_triggered")
    p  = ev["payload"]
    assert "days_remaining"  in p, "auto_recharge payload: days_remaining missing"
    assert "total_available" in p, "auto_recharge payload: total_available missing"
    assert "timestamp"       in p, "auto_recharge payload: timestamp missing"


# ====================================================================
# TEST 6 — Orchestrator blocks action in CONTENÇÃO_FINANCEIRA
# ====================================================================

def t6_orchestrator_blocks_in_containment():
    """
    With GlobalState == CONTENÇÃO_FINANCEIRA, sending a sensitive event
    (price_update_requested) must raise FinancialContainmentError.
    """
    bus = EventBus()
    sm  = StateManager()
    orc = Orchestrator(bus, sm)

    # Put GlobalState in CONTENÇÃO_FINANCEIRA
    gs  = GlobalState(MemFile())
    gs.request_state_update(CONTENCAO_FINANCEIRA, bus, "test setup", source="test", orchestrated=False)
    orc.register_service("global_state", gs)

    raised = False
    try:
        orc.receive_event(
            "price_update_requested",
            {"price": 99.99},
            product_id="prod-test",
        )
    except FinancialContainmentError:
        raised = True

    assert raised, (
        "Expected FinancialContainmentError when posting price_update_requested "
        "while in CONTENÇÃO_FINANCEIRA."
    )


# ====================================================================
# TEST 7 — No direct write outside Orchestrator
# ====================================================================

def t7_no_direct_write():
    """
    StateManager must raise DirectWriteError on any direct .set() call
    when write-lock is active (i.e., outside Orchestrator._write_context).
    """
    sm = StateManager()
    raised = False
    try:
        sm.set("product_price", 99.99)
    except DirectWriteError:
        raised = True

    assert raised, (
        "Expected DirectWriteError when writing directly to StateManager."
    )


# ====================================================================
# Runner
# ====================================================================

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  A4 FINANCE ENGINE — TEST SUITE")
    print("=" * 60)

    test("Days-remaining projection correct",              t1_projection_correct)
    test("credit_low_warning triggered correctly",        t2_credit_low_warning)
    test("credit_critical_warning triggered correctly",   t3_credit_critical_warning)
    test("GlobalState transitions correctly",             t4_global_state_transitions)
    test("AUTO_RECHARGE emits formal event",              t5_auto_recharge_event)
    test("Orchestrator blocks in CONTENÇÃO_FINANCEIRA",   t6_orchestrator_blocks_in_containment)
    test("DirectWriteError outside Orchestrator",         t7_no_direct_write)

    print("\n" + "=" * 60)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A4 FINANCE ENGINE — VALID")
        print("  FINANCIAL GOVERNANCE LOCKED")
    else:
        print("  A4 FINANCE ENGINE — INVALID (see failures above)")
    print("=" * 60 + "\n")

    sys.exit(0 if passed == total else 1)
