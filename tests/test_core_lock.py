"""
tests/test_core_lock.py — Foundation Core Lock Validation Suite

Runs all 6 closure criteria defined in the Foundation Core Lock spec.
Usage:
    py tests/test_core_lock.py

All 6 tests must print ✔ for the implementation to be considered valid.
"""
import sys
import os
import io

# Force UTF-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus        import EventBus
from core.state_manager    import StateManager, DirectWriteError
from core.orchestrator     import Orchestrator
from core.state_machine    import StateMachine, InvalidTransitionError
from core.snapshot_manager import SnapshotManager
from core.version_manager  import VersionManager
from infrastructure.db     import SnapshotPersistence

PASS = "[OK]"
FAIL = "[FAIL]"
results = []



def test(name: str, fn) -> bool:
    try:
        fn()
        results.append((PASS, name))
        print(f"  {PASS}  {name}")
        return True
    except AssertionError as e:
        results.append((FAIL, name))
        print(f"  {FAIL}  {name}")
        print(f"       AssertionError: {e}")
        return False
    except Exception as e:
        results.append((FAIL, name))
        print(f"  {FAIL}  {name}")
        print(f"       Unexpected error: {type(e).__name__}: {e}")
        return False


# ------------------------------------------------------------------
# Shared setup
# ------------------------------------------------------------------

def _make_bus():
    return EventBus()  # No persistence backend (in-memory only for tests)

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

def _make_state():
    sm = StateManager()          # No persistence — in-memory
    return sm


def _make_orch(bus=None, state=None):
    bus   = bus   or _make_bus()
    state = state or _make_state()
    return Orchestrator(bus, state), bus, state


# ==================================================================
# TEST 1 — Direct write to state raises DirectWriteError
# ==================================================================
def t1_direct_write_blocked():
    """Engine-simulated direct state.set() must raise DirectWriteError."""
    _, _, state = _make_orch()

    raised = False
    try:
        state.set("should_fail", True)   # ← direct write, must be blocked
    except DirectWriteError:
        raised = True

    assert raised, "DirectWriteError was NOT raised on direct state.set()"


# ==================================================================
# TEST 2 — Invalid state transition raises InvalidTransitionError
# ==================================================================
def t2_invalid_transition_blocked():
    """Arquivado → Ativo must be refused by StateMachine."""
    bus = _make_bus()
    sm  = StateMachine()   # in-memory

    # Force product to Arquivado
    sm._product_states["prod-1"] = "Arquivado"

    raised = False
    try:
        sm.transition("prod-1", "Ativo", reason="test", metric=None, event_bus=bus)
    except InvalidTransitionError:
        raised = True

    assert raised, "InvalidTransitionError was NOT raised for Arquivado → Ativo"


# ==================================================================
# TEST 3 — create_snapshot emits snapshot_created event
# ==================================================================
def t3_snapshot_creates_event():
    """create_snapshot must append a 'snapshot_created' event to the ledger."""

    class InMemorySnapshotPersistence:
        def __init__(self):
            self._data = []
        def load(self):
            return list(self._data)
        def append(self, item):
            self._data.append(item)

    bus    = _make_bus()
    orc    = MockOrchestrator(bus)
    snap_m = SnapshotManager(orc, InMemorySnapshotPersistence())
    snap   = snap_m.create_snapshot(
        product_id="prod-1",
        metrics={"total_cycles": 5},
        state="Beta",
        price=97.0,
        active_version="v1.0",
    )

    events = bus.get_events(product_id="prod-1")
    types  = [e["event_type"] for e in events]

    assert "snapshot_created" in types, (
        f"Expected 'snapshot_created' in events, got: {types}"
    )
    assert "snapshot_id" in snap, "Snapshot must have a snapshot_id"


# ==================================================================
# TEST 4 — rollback generates rollback_executed event
# ==================================================================
def t4_rollback_generates_event():
    """restore_snapshot must append a 'rollback_executed' event."""

    class InMemSnap:
        def __init__(self):
            self._data = []
        def load(self):
            return list(self._data)
        def append(self, item):
            self._data.append(item)

    bus    = _make_bus()
    orc    = MockOrchestrator(bus)
    persist = InMemSnap()
    snap_m = SnapshotManager(orc, persist)

    snap = snap_m.create_snapshot(
        "prod-2", {"total_cycles": 1}, "Ativo", 50.0, "v1"
    )

    snap_m.restore_snapshot("prod-2", snap["snapshot_id"])

    events = bus.get_events(product_id="prod-2")
    types  = [e["event_type"] for e in events]
    assert "rollback_executed" in types, (
        f"Expected 'rollback_executed', got: {types}"
    )


# ==================================================================
# TEST 5 — version promotion emits promotion_executed event
# ==================================================================
def t5_version_promotion_emits_event():
    """promote() must append a 'promotion_executed' event."""

    class MemPersist:
        def load(self):
            return {}
        def save(self, data):
            pass

    bus = _make_bus()
    orc = MockOrchestrator(bus)
    vm  = VersionManager(MemPersist())

    vm.create_candidate("prod-3", version_id="v2.0", orchestrator=orc)
    vm.promote_candidate("prod-3", orchestrator=orc, orchestrated=True, snapshot_id="snap-test")

    events  = bus.get_events(product_id="prod-3")
    types   = [e["event_type"] for e in events]
    assert "promotion_executed" in types, (
        f"Expected 'promotion_executed', got: {types}"
    )


# ==================================================================
# TEST 6 — All events have event_id, timestamp, and version
# ==================================================================
def t6_event_structure_required_fields():
    """Every appended event must have event_id, timestamp, and a sequential version."""
    bus = _make_bus()

    bus.append_event({"event_type": "test_event_a", "payload": {"x": 1}})
    bus.append_event({"event_type": "test_event_b", "payload": {"x": 2}})
    bus.append_event({"event_type": "test_event_c", "payload": {"x": 3}})

    events = bus.get_events()
    for i, e in enumerate(events):
        assert "event_id"  in e, f"event[{i}] missing 'event_id'"
        assert "timestamp" in e, f"event[{i}] missing 'timestamp'"
        assert "version"   in e, f"event[{i}] missing 'version'"

    versions = [e["version"] for e in events]
    assert versions == sorted(set(versions)), (
        f"Versions are not unique and incrementing: {versions}"
    )


# ==================================================================
# BONUS — Engine write via receive_event succeeds (no exception)
# ==================================================================
def t7_engine_write_via_orchestrator_succeeds():
    """An engine calling orchestrator.receive_event() must succeed."""
    orch, _, state = _make_orch()

    orch.receive_event("score_recorded", {"score": 99.5})

    value = state.get("last_score")
    assert value == 99.5, f"Expected last_score=99.5, got {value}"


# ==================================================================
# Runner
# ==================================================================
if __name__ == "__main__":
    print("\n" + "=" * 56)
    print("  FOUNDATION CORE LOCK — TEST SUITE")
    print("=" * 56)

    test("Direct write to state raises DirectWriteError",    t1_direct_write_blocked)
    test("Invalid transition raises InvalidTransitionError", t2_invalid_transition_blocked)
    test("create_snapshot emits snapshot_created event",     t3_snapshot_creates_event)
    test("restore_snapshot emits rollback_executed event",   t4_rollback_generates_event)
    test("promote() emits promotion_executed event",         t5_version_promotion_emits_event)
    test("All events have event_id, timestamp, version",     t6_event_structure_required_fields)
    test("Engine write via receive_event() succeeds",        t7_engine_write_via_orchestrator_succeeds)

    print("\n" + "=" * 56)
    passed = sum(1 for r in results if r[0] == PASS)
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  ✅ FOUNDATION CORE LOCK — VALID")
    else:
        print("  ❌ FOUNDATION CORE LOCK — INVALID (see failures above)")
    print("=" * 56 + "\n")
    sys.exit(0 if passed == total else 1)
