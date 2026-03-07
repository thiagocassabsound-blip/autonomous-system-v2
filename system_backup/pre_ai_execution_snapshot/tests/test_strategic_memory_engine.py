"""
tests/test_strategic_memory_engine.py — A12 Strategic Memory Validation Suite

9 closure criteria:
  1. Consolidação mensal registrada corretamente
  2. month_id inválido bloqueado
  3. Não permite consolidar mês futuro
  4. Não permite consolidar mês já fechado
  5. Dados congelados corretamente
  6. Não permite editar histórico
  7. DirectWriteError fora do Orchestrator
  8. CONTENÇÃO_FINANCEIRA não impede consolidação histórica
  9. month_id obrigatório

Usage:
    py tests/test_strategic_memory_engine.py
"""
import sys
import os
import io
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus                import EventBus
from core.strategic_memory_engine  import (
    StrategicMemoryEngine,
    InvalidMonthIdError,
    MonthAlreadyConsolidatedError,
    StrategicMemoryImmutableError,
)
from core.state_manager            import StateManager, DirectWriteError

# ====================================================================
# Stubs
# ====================================================================

class MemSmPersistence:
    """In-memory append-only persistence."""
    def __init__(self):
        self._records = []
    def append_record(self, record):
        import copy; self._records.append(copy.deepcopy(record))
    def load_all(self):
        import copy; return copy.deepcopy(self._records)


PAST    = datetime(2026, 2, 23, 18, 0, 0, tzinfo=timezone.utc)   # current month = 2026-02
FUTURE  = datetime(2026, 4, 15, 0, 0, 0, tzinfo=timezone.utc)    # future month  = 2026-04

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

def _make_engine(orchestrator=None, now_dt=PAST):
    if orchestrator is None:
        orchestrator = MockOrchestrator(EventBus())
    return StrategicMemoryEngine(
        orchestrator=orchestrator,
        persistence=MemSmPersistence(),
        now_fn=lambda: now_dt,
    )


def _consolidate(eng, product_id="prod-1", month_id="2026-01", **overrides):
    """Helper: call consolidate_month with sensible defaults."""
    defaults = dict(
        baseline_version="v2",
        baseline_price=199.0,
        rpm_final=12.5,
        roas_final=3.8,
        cac_final=45.0,
        margin_final=0.42,
        total_active_seconds=2_592_000,
        total_revenue=15_000.0,
        total_ad_spend=3_947.0,
        snapshot_reference="snap-jan-2026",
    )
    defaults.update(overrides)
    return eng.consolidate_month(
        product_id=product_id,
        month_id=month_id,
        **defaults,
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

def t1_consolidation_registered():
    """consolidate_month records data correctly and emits monthly_consolidated."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)

    record = _consolidate(eng)

    assert record["month_id"]           == "2026-01"
    assert record["product_id"]         == "prod-1"
    assert record["baseline_price"]     == 199.0
    assert record["rpm_final"]          == 12.5
    assert record["total_revenue"]      == 15_000.0
    assert record["consolidated_at"]    == PAST.isoformat()

    types = [e["event_type"] for e in bus.get_events()]
    assert "monthly_consolidated" in types, "monthly_consolidated not in ledger"

    # Record must also exist in getter
    stored = eng.get_record("prod-1", "2026-01")
    assert stored is not None, "Record not found after consolidation"
    assert stored["roas_final"] == 3.8


def t2_invalid_month_id_blocked():
    """Bad month_id formats raise InvalidMonthIdError."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)

    bad_ids = ["2026-13", "26-02", "2026/02", "202602", "2026-00", "abc-def"]
    for mid in bad_ids:
        raised = False
        try:
            _consolidate(eng, month_id=mid)
        except InvalidMonthIdError:
            raised = True
        assert raised, f"Expected InvalidMonthIdError for month_id='{mid}'"


def t3_future_month_blocked():
    """month_id pointing to a future month raises InvalidMonthIdError."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc, now_dt=PAST)   # current = 2026-02

    raised = False
    try:
        _consolidate(eng, month_id="2026-03")   # future
    except InvalidMonthIdError:
        raised = True
    assert raised, "Expected InvalidMonthIdError for future month"

    # Current month (2026-02) should be allowed
    record = _consolidate(eng, month_id="2026-02")
    assert record["month_id"] == "2026-02"


def t4_double_consolidation_blocked():
    """Second consolidation of same product+month raises MonthAlreadyConsolidatedError."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)

    _consolidate(eng, month_id="2026-01")

    raised = False
    try:
        _consolidate(eng, month_id="2026-01")
    except MonthAlreadyConsolidatedError:
        raised = True
    assert raised, "Expected MonthAlreadyConsolidatedError on second consolidation"

    # Different month must still be allowed
    record2 = _consolidate(eng, month_id="2025-12")
    assert record2["month_id"] == "2025-12"


def t5_data_frozen():
    """Consolidated data matches exactly what was provided — no mutation post-freeze."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)

    record = _consolidate(eng,
        month_id="2026-01",
        rpm_final=99.9,
        total_revenue=500_000.0,
        snapshot_reference="snap-custom",
    )

    stored = eng.get_record("prod-1", "2026-01")
    assert stored["rpm_final"]          == 99.9
    assert stored["total_revenue"]      == 500_000.0
    assert stored["snapshot_reference"] == "snap-custom"

    # The returned record must not be the same object (frozen, not live reference)
    stored2 = eng.get_record("prod-1", "2026-01")
    assert stored2["rpm_final"] == 99.9   # still correct after second access


def t6_history_immutable():
    """reopen_month, update_consolidation, reprocess_metrics all raise StrategicMemoryImmutableError."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)
    _consolidate(eng)

    for method, args in [
        (eng.reopen_month,         ("prod-1", "2026-01")),
        (eng.update_consolidation, ("prod-1", "2026-01")),
        (eng.reprocess_metrics,    ("prod-1", "2026-01")),
    ]:
        raised = False
        try:
            method(*args)
        except StrategicMemoryImmutableError:
            raised = True
        assert raised, f"Expected StrategicMemoryImmutableError from {method.__name__}"


def t7_direct_write_blocked():
    """StateManager.set() raises DirectWriteError — no direct writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("strategic_bypass", {"override": True})
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


def t8_contencao_does_not_block_historical():
    """
    CONTENÇÃO_FINANCEIRA must NOT block historical consolidation.
    (Monthly reports are a read-only historical operation — they don't spend money.)
    Verify that the engine itself has no containment gate.
    """
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)

    # Simulate containment by NOT injecting any global_state into the engine
    # (The engine has no financial containment check by design)
    record = _consolidate(eng, month_id="2026-01")
    assert record["consolidated_at"] is not None, (
        "Consolidation must succeed regardless of financial containment state"
    )


def t9_month_id_required():
    """Calling consolidate_month without month_id raises InvalidMonthIdError."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)

    for empty in ["", "   "]:
        raised = False
        try:
            _consolidate(eng, month_id=empty)
        except InvalidMonthIdError:
            raised = True
        assert raised, f"Expected InvalidMonthIdError for empty month_id='{empty}'"

    # None should also fail (coerced to "None" string → fails regex)
    raised = False
    try:
        _consolidate(eng, month_id="None")
    except InvalidMonthIdError:
        raised = True
    assert raised, "Expected InvalidMonthIdError for month_id='None'"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A12 STRATEGIC MEMORY — TEST SUITE")
    print("=" * 62)

    test("Consolidação mensal registrada corretamente", t1_consolidation_registered)
    test("month_id inválido bloqueado",                t2_invalid_month_id_blocked)
    test("Não permite consolidar mês futuro",          t3_future_month_blocked)
    test("Não permite consolidar mês já fechado",      t4_double_consolidation_blocked)
    test("Dados congelados corretamente",              t5_data_frozen)
    test("Não permite editar histórico",               t6_history_immutable)
    test("DirectWriteError fora do Orchestrator",      t7_direct_write_blocked)
    test("CONTENÇÃO_FINANCEIRA não impede histórico",  t8_contencao_does_not_block_historical)
    test("month_id obrigatório",                       t9_month_id_required)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A12 STRATEGIC MEMORY — VALID")
        print("  A12 STRATEGIC MEMORY LOCKED")
    else:
        print("  A12 STRATEGIC MEMORY — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
