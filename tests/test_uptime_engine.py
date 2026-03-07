"""
tests/test_uptime_engine.py — A11 Uptime Engine Validation Suite

9 closure criteria:
  1. created_at registrado corretamente
  2. Não permite dupla inicialização
  3. Resume ativa produto
  4. Pause acumula tempo corretamente
  5. total_active_seconds nunca diminui
  6. Não permite pause se já pausado
  7. Não permite resume se já ativo
  8. DirectWriteError fora do Orchestrator
  9. Tentativa de reset lança erro

Usage:
    py tests/test_uptime_engine.py
"""
import sys
import os
import io
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus     import EventBus
from core.uptime_engine import (
    UptimeEngine,
    ProductAlreadyInitializedError,
    ProductAlreadyActiveError,
    ProductNotActiveError,
    UptimeIntegrityViolationError,
)
from core.state_manager import StateManager, DirectWriteError

# ====================================================================
# Stubs
# ====================================================================

class MemUptimePersistence:
    def __init__(self):
        import copy
        self._d = {}
    def load(self):
        import copy; return copy.deepcopy(self._d)
    def save(self, data):
        import copy; self._d = copy.deepcopy(data)


class MockOrchestrator:
    """Simulates Orchestrator.emit_event() for unit tests."""
    def __init__(self, event_bus):
        self._bus = event_bus
    def emit_event(self, event_type, payload, source=None, product_id=None, month_id=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload": payload,
            "source": source,
            "product_id": product_id,
            "month_id": month_id
        })


def _make_engine(clock_steps=None):
    """Return an UptimeEngine with an injectable stepped clock."""
    if clock_steps is not None:
        # Iterator over datetime objects — each call to now_fn returns next step
        it = iter(clock_steps)
        def now_fn():
            return next(it)
        return UptimeEngine(persistence=MemUptimePersistence(), now_fn=now_fn)
    return UptimeEngine(persistence=MemUptimePersistence())


def _ts(offset_seconds: int = 0) -> datetime:
    base = datetime(2026, 2, 23, 18, 0, 0, tzinfo=timezone.utc)
    return base + timedelta(seconds=offset_seconds)


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

def t1_created_at_registered():
    """register_product sets created_at correctly and emits event."""
    clk = [_ts(0)]
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    record = eng.register_product("prod-A", orc)

    assert record["created_at"] == _ts(0).isoformat(), (
        f"created_at mismatch: {record['created_at']}"
    )
    assert record["total_active_seconds"] == 0
    assert record["is_active"] is False
    assert record["last_resume_timestamp"] is None

    types = [e["event_type"] for e in bus.get_events()]
    assert "product_created_timestamped" in types, "product_created_timestamped not in ledger"


def t2_double_init_blocked():
    """register_product raises ProductAlreadyInitializedError on second call."""
    clk = [_ts(0), _ts(60)]
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    eng.register_product("prod-B", orc)

    raised = False
    try:
        eng.register_product("prod-B", orc)
    except ProductAlreadyInitializedError:
        raised = True
    assert raised, "Expected ProductAlreadyInitializedError on second register"


def t3_resume_activates_product():
    """resume_product sets is_active=True and records last_resume_timestamp."""
    clk = [_ts(0), _ts(10)]   # 0=init, 10=resume
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    eng.register_product("prod-C", orc)
    record = eng.resume_product("prod-C", orc)

    assert record["is_active"] is True
    assert record["last_resume_timestamp"] == _ts(10).isoformat()
    assert record["total_active_seconds"] == 0   # nothing accumulated yet

    types = [e["event_type"] for e in bus.get_events()]
    assert "product_resumed" in types, "product_resumed not in ledger"


def t4_pause_accumulates_correctly():
    """pause_product delta is added to total_active_seconds accurately."""
    # Clock: init=0, resume=10, pause=70 → delta=60
    clk = [_ts(0), _ts(10), _ts(70)]
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    eng.register_product("prod-D", orc)
    eng.resume_product("prod-D", orc)
    record = eng.pause_product("prod-D", orc)

    assert record["total_active_seconds"] == 60, (
        f"Expected 60s, got {record['total_active_seconds']}"
    )
    assert record["is_active"] is False
    assert record["last_resume_timestamp"] is None

    types = [e["event_type"] for e in bus.get_events()]
    assert "product_paused" in types, "product_paused not in ledger"

    paused_events = [e for e in bus.get_events() if e["event_type"] == "product_paused"]
    assert paused_events[0]["payload"]["active_seconds_delta"] == 60


def t5_total_never_decreases():
    """Two resume/pause cycles: total_active_seconds always grows."""
    # init=0, resume1=0, pause1=30, resume2=50, pause2=80 → 30+30=60
    clk = [_ts(0), _ts(0), _ts(30), _ts(50), _ts(80)]
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    eng.register_product("prod-E", orc)
    eng.resume_product("prod-E", orc)
    eng.pause_product("prod-E", orc)
    after_first = eng.get_record("prod-E")["total_active_seconds"]

    eng.resume_product("prod-E", orc)
    eng.pause_product("prod-E", orc)
    after_second = eng.get_record("prod-E")["total_active_seconds"]

    assert after_second >= after_first, (
        f"total_active_seconds decreased: {after_first} → {after_second}"
    )
    assert after_second == 60, f"Expected 60s total, got {after_second}"


def t6_pause_blocked_when_already_paused():
    """pause_product raises ProductNotActiveError if product is not active."""
    # init consumes _ts(0); pause attempt consumes _ts(1) → still ProductNotActiveError
    clk = [_ts(0), _ts(1)]
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng.register_product("prod-F", orc)   # is_active=False

    raised = False
    try:
        eng.pause_product("prod-F", orc)
    except ProductNotActiveError:
        raised = True
    assert raised, "Expected ProductNotActiveError when pausing an already-paused product"



def t7_resume_blocked_when_already_active():
    """resume_product raises ProductAlreadyActiveError if product is active."""
    clk = [_ts(0), _ts(5), _ts(6)]
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)

    eng.register_product("prod-G", orc)
    eng.resume_product("prod-G", orc)  # now active

    raised = False
    try:
        eng.resume_product("prod-G", orc)
    except ProductAlreadyActiveError:
        raised = True
    assert raised, "Expected ProductAlreadyActiveError when resuming an already-active product"


def t8_direct_write_blocked():
    """StateManager.set() raises DirectWriteError — no direct writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("uptime_bypass", 999999)
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


def t9_reset_raises_error():
    """reset_uptime, overwrite_created_at, set_total_active_seconds all raise UptimeIntegrityViolationError."""
    clk = [_ts(0)]
    eng = _make_engine(clk)
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng.register_product("prod-H", orc)

    for method, args in [
        (eng.reset_uptime,              ("prod-H",)),
        (eng.overwrite_created_at,      ("prod-H", "2020-01-01T00:00:00+00:00")),
        (eng.set_total_active_seconds,  ("prod-H", 0)),
    ]:
        raised = False
        try:
            method(*args)
        except UptimeIntegrityViolationError:
            raised = True
        assert raised, f"Expected UptimeIntegrityViolationError from {method.__name__}"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A11 UPTIME ENGINE — TEST SUITE")
    print("=" * 62)

    test("created_at registrado corretamente",      t1_created_at_registered)
    test("Não permite dupla inicialização",         t2_double_init_blocked)
    test("Resume ativa produto",                    t3_resume_activates_product)
    test("Pause acumula tempo corretamente",        t4_pause_accumulates_correctly)
    test("total_active_seconds nunca diminui",      t5_total_never_decreases)
    test("Não permite pause se já pausado",         t6_pause_blocked_when_already_paused)
    test("Não permite resume se já ativo",          t7_resume_blocked_when_already_active)
    test("DirectWriteError fora do Orchestrator",   t8_direct_write_blocked)
    test("Tentativa de reset lança erro",           t9_reset_raises_error)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A11 UPTIME ENGINE — VALID")
        print("  A11 UPTIME GOVERNANCE LOCKED")
    else:
        print("  A11 UPTIME ENGINE — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
