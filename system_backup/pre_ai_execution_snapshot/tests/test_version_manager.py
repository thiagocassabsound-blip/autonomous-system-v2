"""
tests/test_version_manager.py — A8 Version Manager Validation Suite

8 closure criteria:
  1. Only 1 candidate allowed at a time
  2. Promotion requires valid snapshot_id
  3. Promotion emits formal event
  4. Previous baseline preserved in history after promotion
  5. Rollback restores version + snapshot_id + price
  6. Candidate invalidated after promotion
  7. CONTENÇÃO_FINANCEIRA blocks promotion
  8. DirectWriteError outside Orchestrator

Usage:
    py tests/test_version_manager.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus      import EventBus
from core.version_manager import (
    VersionManager,
    VersionCandidateExistsError,
    BaselineSnapshotMissingError,
    VersionPromotionPreconditionError,
    VersionPromotionViolationError,
    VersionPromotionOutsideOrchestratorError,
    NoPreviousBaselineError,
    VersionContainmentError,
    DeprecatedVersionFlowError,
)
from core.state_manager  import StateManager, DirectWriteError
from core.global_state   import GlobalState, CONTENCAO_FINANCEIRA

# ====================================================================
# Stubs
# ====================================================================

class MemFile:
    def __init__(self):
        self._d = {}
    def load(self):
        import copy; return copy.deepcopy(self._d)
    def save(self, data):
        import copy; self._d = copy.deepcopy(data)


class MockSnapshotStore:
    """Controls which snapshot IDs are 'valid'."""
    def __init__(self, valid_ids=None):
        self._valid = set(valid_ids or [])
    def exists(self, sid):
        return sid in self._valid
    def add(self, sid):
        self._valid.add(sid)


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


def _make_vm(snapshot_store=None):
    return VersionManager(persistence=MemFile(), snapshot_store=snapshot_store)


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

def t1_only_one_candidate():
    """Creating a second candidate while one is active raises VersionCandidateExistsError."""
    vm  = _make_vm()
    orc = MockOrchestrator(EventBus())

    vm.create_candidate("prod-1", version_id="v1", snapshot_id="snap-1", orchestrator=orc)

    raised = False
    try:
        vm.create_candidate("prod-1", version_id="v2", snapshot_id="snap-2", orchestrator=orc)
    except VersionCandidateExistsError:
        raised = True
    assert raised, "Expected VersionCandidateExistsError for second candidate"


def t2_promotion_requires_snapshot():
    """Promotion blocked when snapshot_id is missing or invalid."""
    snap_store = MockSnapshotStore(valid_ids=["snap-valid"])
    vm  = _make_vm(snapshot_store=snap_store)
    orc = MockOrchestrator(EventBus())
    gs  = GlobalState(MemFile())

    vm.create_candidate("prod-2", version_id="v1", snapshot_id="snap-valid", orchestrator=orc)

    # No snapshot_id at all
    raised_none = False
    try:
        vm.promote_candidate("prod-2", snapshot_id="", orchestrator=orc, global_state=gs, orchestrated=True)
    except (BaselineSnapshotMissingError, VersionPromotionViolationError):
        raised_none = True
    assert raised_none, "Expected error when snapshot_id is empty"

    # Snapshot doesn't exist in store
    raised_inv = False
    try:
        vm.promote_candidate("prod-2", snapshot_id="snap-does-not-exist", orchestrator=orc, global_state=gs, orchestrated=True)
    except (BaselineSnapshotMissingError, VersionPromotionViolationError):
        raised_inv = True
    assert raised_inv, "Expected error for non-existent snapshot"


def t3_promotion_emits_event():
    """Promotion emits promotion_executed event in the ledger."""
    snap_store = MockSnapshotStore(valid_ids=["snap-1"])
    vm  = _make_vm(snapshot_store=snap_store)
    orc = MockOrchestrator(EventBus())
    gs  = GlobalState(MemFile())

    vm.create_candidate("prod-3", version_id="v1", snapshot_id="snap-1", orchestrator=orc)
    result = vm.promote_candidate("prod-3", snapshot_id="snap-1", linked_price=99.0,
                                  orchestrator=orc, global_state=gs, orchestrated=True)

    types = [e["event_type"] for e in orc._bus.get_events()]
    assert any(t in types for t in ("version_promoted", "promotion_executed")), \
        f"version_promoted not in ledger: {types}"
    assert result["version_id"] == "v1", f"Expected version_id='v1', got '{result['version_id']}'"
    assert result["linked_price"] == 99.0, f"Expected linked_price=99.0, got {result['linked_price']}"


def t4_old_baseline_preserved():
    """After promoting, the previous baseline remains in version_history."""
    snap_store = MockSnapshotStore(valid_ids=["snap-1", "snap-2"])
    vm  = _make_vm(snapshot_store=snap_store)
    orc = MockOrchestrator(EventBus())
    gs  = GlobalState(MemFile())

    # First promotion: v1 becomes baseline
    vm.create_candidate("prod-4", version_id="v1", snapshot_id="snap-1", orchestrator=orc)
    vm.promote_candidate("prod-4", snapshot_id="snap-1", linked_price=50.0,
                         orchestrator=orc, global_state=gs, orchestrated=True)

    # Second promotion: v2 becomes baseline, v1 should stay in history
    vm.create_candidate("prod-4", version_id="v2", snapshot_id="snap-2", orchestrator=orc)
    vm.promote_candidate("prod-4", snapshot_id="snap-2", linked_price=60.0,
                         orchestrator=orc, global_state=gs, orchestrated=True)

    history = vm.get_history("prod-4")
    vids    = [h["version_id"] for h in history]
    assert "v1" in vids, f"Old baseline 'v1' not found in history: {vids}"
    assert "v2" in vids, f"New baseline 'v2' not found in history: {vids}"
    assert vm.get_baseline("prod-4") == "v2", "Current baseline should be v2"


def t5_rollback_restores_version_snapshot_price():
    """Rollback restores version_id, snapshot_id, and linked_price of previous baseline."""
    snap_store = MockSnapshotStore(valid_ids=["snap-1", "snap-2"])
    vm  = _make_vm(snapshot_store=snap_store)
    orc = MockOrchestrator(EventBus())
    gs  = GlobalState(MemFile())

    # First baseline: v1 / snap-1 / price=50
    vm.create_candidate("prod-5", version_id="v1", snapshot_id="snap-1", orchestrator=orc)
    vm.promote_candidate("prod-5", snapshot_id="snap-1", linked_price=50.0,
                         orchestrator=orc, global_state=gs, orchestrated=True)

    # Second baseline: v2 / snap-2 / price=75
    vm.create_candidate("prod-5", version_id="v2", snapshot_id="snap-2", orchestrator=orc)
    vm.promote_candidate("prod-5", snapshot_id="snap-2", linked_price=75.0,
                         orchestrator=orc, global_state=gs, orchestrated=True)

    assert vm.get_baseline("prod-5") == "v2"

    # Rollback → should restore v1
    restored = vm.rollback_to_previous_baseline("prod-5", orchestrator=orc, orchestrated=True)
    assert restored["version_id"] == "v1", (
        f"Expected rollback to v1, got: {restored['version_id']}"
    )
    assert restored["linked_snapshot_id"] == "snap-1", (
        f"Expected linked_snapshot_id='snap-1', got: {restored['linked_snapshot_id']}"
    )
    assert restored["linked_price"] == 50.0, (
        f"Expected linked_price=50.0, got: {restored['linked_price']}"
    )

    types = [e["event_type"] for e in orc._bus.get_events()]
    assert "version_rollback_executed" in types, "version_rollback_executed not in ledger"


def t6_candidate_invalidated_after_promotion():
    """After promoting, candidate_version is set to None."""
    snap_store = MockSnapshotStore(valid_ids=["snap-1"])
    vm  = _make_vm(snapshot_store=snap_store)
    orc = MockOrchestrator(EventBus())
    gs  = GlobalState(MemFile())

    vm.create_candidate("prod-6", version_id="v1", snapshot_id="snap-1", orchestrator=orc)
    assert vm.get_candidate("prod-6") == "v1"

    vm.promote_candidate("prod-6", snapshot_id="snap-1", orchestrator=orc, global_state=gs, orchestrated=True)

    assert vm.get_candidate("prod-6") is None, (
        "candidate_version must be None after promotion"
    )


def t7_containment_blocks_promotion():
    """CONTENÇÃO_FINANCEIRA blocks version promotion."""
    snap_store = MockSnapshotStore(valid_ids=["snap-1"])
    vm  = _make_vm(snapshot_store=snap_store)
    orc = MockOrchestrator(EventBus())

    gs = GlobalState(MemFile())
    gs.request_state_update(CONTENCAO_FINANCEIRA, orc._bus, "test containment", source="test", orchestrated=False)

    vm.create_candidate("prod-7", version_id="v1", snapshot_id="snap-1", orchestrator=orc)

    raised = False
    try:
        vm.promote_candidate("prod-7", snapshot_id="snap-1", orchestrator=orc, global_state=gs, orchestrated=True)
    except (VersionContainmentError, VersionPromotionViolationError):
        raised = True
    assert raised, "Expected VersionContainmentError or VersionPromotionViolationError during CONTENÇÃO_FINANCEIRA"


def t8_direct_write_fails():
    """StateManager.set() directly raises DirectWriteError."""
    sm = StateManager()
    raised = False
    try:
        sm.set("baseline_version", "v-hack")
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A8 VERSION MANAGER — TEST SUITE")
    print("=" * 62)

    test("Only 1 candidate allowed at a time",              t1_only_one_candidate)
    test("Promotion requires valid snapshot_id",            t2_promotion_requires_snapshot)
    test("Promotion emits formal event",                    t3_promotion_emits_event)
    test("Previous baseline preserved in history",         t4_old_baseline_preserved)
    test("Rollback restores version + snapshot + price",   t5_rollback_restores_version_snapshot_price)
    test("Candidate invalidated after promotion",           t6_candidate_invalidated_after_promotion)
    test("CONTENÇÃO_FINANCEIRA blocks promotion",           t7_containment_blocks_promotion)
    test("DirectWriteError outside Orchestrator",           t8_direct_write_fails)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A8 VERSION MANAGER — VALID")
        print("  A8 VERSION GOVERNANCE LOCKED")
    else:
        print("  A8 VERSION MANAGER — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
