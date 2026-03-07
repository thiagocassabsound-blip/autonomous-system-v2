"""
tests/test_telemetry_engine.py — A3 Telemetry Engine Validation Suite

Validates all 8 closure criteria for the A3 Telemetry system.
Usage:
    py tests/test_telemetry_engine.py
"""
import sys
import os
import io
import copy

# Force UTF-8 stdout on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# Project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus      import EventBus
from core.cycle_manager  import CycleManager, CycleNotFoundError
from core.telemetry_engine import TelemetryEngine

# ====================================================================
# Minimal in-memory persistence stubs
# ====================================================================

class MemAppend:
    """Append-only in-memory list — simulates snapshots.json."""
    def __init__(self):
        self._data = []
    def load(self) -> list:
        return list(self._data)
    def append(self, item: dict) -> None:
        self._data.append(dict(item))   # store a copy — immutable after this


class MemFile:
    """Generic JSON file stub — simulates accumulators.json / cycles.json."""
    def __init__(self):
        self._data = {}
    def load(self):
        return dict(self._data)
    def save(self, data) -> None:
        self._data = copy.deepcopy(data)


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


# ====================================================================
# Helpers
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


def _make_telemetry():
    """Return a fresh in-memory TelemetryEngine + MockOrchestrator."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    te  = TelemetryEngine(MemAppend(), MemFile())
    return te, orc


def _make_cycle_manager():
    return CycleManager(MemFile())


def _open_and_populate(te: TelemetryEngine, orc: MockOrchestrator, product_id: str) -> dict:
    """Open a cycle, record metrics, close, return snapshot."""
    cm = _make_cycle_manager()
    cm.open_cycle(product_id, orc)

    te.record_visit(product_id)
    te.record_visit(product_id)         # 2 visitors
    te.record_revenue(product_id, 200)  # 1 conversion, R$200 bruta
    te.record_ad_spend(product_id, 50)  # R$50 ad spend

    closed = cm.close_cycle(product_id, orc)
    return te.close_cycle_snapshot(product_id, closed["cycle_id"], orc)


# ====================================================================
# TESTS
# ====================================================================

# ── TEST 1 — RPM ──────────────────────────────────────────────────────
def t1_rpm():
    """RPM = revenue_liquida / visitors == 200 / 2 == 100.0."""
    te, orc = _make_telemetry()
    snap = _open_and_populate(te, orc, "p1")
    expected = 200.0 / 2          # revenue_liquida=200, visitors=2
    assert snap["rpm"] == expected, (
        f"Expected RPM={expected}, got {snap['rpm']}"
    )


# ── TEST 2 — ROAS ─────────────────────────────────────────────────────
def t2_roas():
    """ROAS = revenue_liquida / ad_spend == 200 / 50 == 4.0."""
    te, orc = _make_telemetry()
    snap = _open_and_populate(te, orc, "p2")
    expected = 200.0 / 50
    assert snap["roas"] == expected, (
        f"Expected ROAS={expected}, got {snap['roas']}"
    )


# ── TEST 3 — CAC ──────────────────────────────────────────────────────
def t3_cac():
    """CAC = ad_spend / conversions == 50 / 1 == 50.0."""
    te, orc = _make_telemetry()
    snap = _open_and_populate(te, orc, "p3")
    expected = 50.0 / 1           # 1 revenue event = 1 conversion
    assert snap["cac"] == expected, (
        f"Expected CAC={expected}, got {snap['cac']}"
    )


# ── TEST 4 — Margin ───────────────────────────────────────────────────
def t4_margin():
    """Margin = (revenue_liquida - ad_spend) / revenue_liquida == (200-50)/200 == 0.75."""
    te, orc = _make_telemetry()
    snap = _open_and_populate(te, orc, "p4")
    expected = round((200 - 50) / 200, 6)
    assert snap["margin"] == expected, (
        f"Expected Margin={expected}, got {snap['margin']}"
    )


# ── TEST 5 — Snapshot created on cycle close ──────────────────────────
def t5_snapshot_on_close():
    """Closing a cycle must create a snapshot and emit cycle_snapshot_created."""
    te, orc = _make_telemetry()
    snap = _open_and_populate(te, orc, "p5")

    assert "snapshot_id"    in snap, "snapshot_id missing"
    assert "version_number" in snap, "version_number missing"
    assert "timestamp"      in snap, "timestamp missing"
    assert snap["version_number"] >= 1, "version_number must be >= 1"

    # Ledger must contain cycle_snapshot_created
    events = orc._bus.get_events(product_id="p5")
    types  = [e["event_type"] for e in events]
    assert "cycle_snapshot_created" in types, (
        f"Expected 'cycle_snapshot_created' in ledger events, got: {types}"
    )


# ── TEST 6 — Snapshot is immutable after creation ─────────────────────
def t6_snapshot_immutable():
    """
    After creation, the snapshot stored in persistence must be unchanged.
    There is no public API to modify a snapshot.
    """
    snap_store = MemAppend()
    te  = TelemetryEngine(snap_store, MemFile())
    orc = MockOrchestrator(EventBus())
    cm  = _make_cycle_manager()

    cm.open_cycle("p6", orc)
    te.record_revenue("p6", 300)
    closed = cm.close_cycle("p6", orc)
    snap = te.close_cycle_snapshot("p6", closed["cycle_id"], orc)

    snapshot_id = snap["snapshot_id"]

    # Attempt external modification (simulating a bad actor)
    stored = snap_store.load()
    original_rpm = stored[0]["rpm"]

    # Even if we mutate the returned dict, the store is unchanged
    snap["rpm"] = 99999
    stored_after = snap_store.load()
    assert stored_after[0]["rpm"] == original_rpm, (
        "Snapshot was mutated in persistence after creation!"
    )
    assert stored_after[0]["snapshot_id"] == snapshot_id, "Snapshot ID changed!"


# ── TEST 7 — New cycle creates new snapshot ───────────────────────────
def t7_new_cycle_new_snapshot():
    """
    Two independent cycles for the same product must produce two distinct snapshots.
    """
    te, orc = _make_telemetry()
    cm = _make_cycle_manager()

    # Cycle 1
    cm.open_cycle("p7", orc)
    te.record_revenue("p7", 100)
    c1 = cm.close_cycle("p7", orc)
    s1 = te.close_cycle_snapshot("p7", c1["cycle_id"], orc)

    # Cycle 2
    cm.open_cycle("p7", orc)
    te.record_revenue("p7", 500)
    c2 = cm.close_cycle("p7", orc)
    s2 = te.close_cycle_snapshot("p7", c2["cycle_id"], orc)

    assert s1["snapshot_id"] != s2["snapshot_id"], "Two cycles must produce different snapshot_ids"
    assert s1["cycle_id"]    != s2["cycle_id"],    "Two cycles must have different cycle_ids"
    assert s2["version_number"] > s1["version_number"], "Version must increment"
    assert s2["revenue_bruta"]  > s1["revenue_bruta"],  "Revenues must differ"


# ── TEST 8 — Attempting to close already-closed cycle fails ───────────
def t8_recalculate_closed_fails():
    """
    Closing a cycle that is already closed must raise CycleNotFoundError.
    This enforces immutability: metrics cannot be recalculated retroactively.
    """
    te, orc = _make_telemetry()
    cm = _make_cycle_manager()

    cm.open_cycle("p8", orc)
    te.record_revenue("p8", 100)
    cm.close_cycle("p8", orc)

    raised = False
    try:
        cm.close_cycle("p8", orc)   # second close attempt
    except CycleNotFoundError:
        raised = True

    assert raised, (
        "Expected CycleNotFoundError when closing an already-closed cycle."
    )


# ====================================================================
# Runner
# ====================================================================

if __name__ == "__main__":
    print("\n" + "=" * 58)
    print("  A3 TELEMETRY ENGINE — TEST SUITE")
    print("=" * 58)

    test("RPM calculated correctly",                   t1_rpm)
    test("ROAS calculated correctly",                  t2_roas)
    test("CAC calculated correctly",                   t3_cac)
    test("Margin calculated correctly",                t4_margin)
    test("Snapshot created at cycle close",            t5_snapshot_on_close)
    test("Snapshot immutable after creation",          t6_snapshot_immutable)
    test("New cycle creates new snapshot",             t7_new_cycle_new_snapshot)
    test("Closing already-closed cycle raises error",  t8_recalculate_closed_fails)

    print("\n" + "=" * 58)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A3 TELEMETRY ENGINE — VALID")
    else:
        print("  A3 TELEMETRY ENGINE — INVALID (failures above)")
    print("=" * 58 + "\n")

    sys.exit(0 if passed == total else 1)
