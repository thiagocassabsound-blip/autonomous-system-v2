"""
tests/test_version_governance_hardening.py — Version Governance Hardening Suite

ID: VERSION_MANAGER_HARDENING_V1
Validates 8 constitutional requirements:

  1.  promote_version()             → raises DeprecatedVersionFlowError
  2.  rollback_version()            → raises DeprecatedVersionFlowError
  3.  promote_candidate(no snap)    → raises VersionPromotionViolationError
  4.  promote_candidate(no orch.)   → raises VersionPromotionOutsideOrchestratorError
  5.  promote during CONTENÇÃO      → raises VersionPromotionViolationError
  6.  promote without candidate     → raises VersionPromotionViolationError
  7.  promote with financial_alert  → raises VersionPromotionViolationError
  8.  All promotions create version_promoted in ledger
  9.  Rollback only via orchestrated=True
  10. MarketLoop does NOT call version_manager directly

Tests are self-contained and do not mutate the filesystem.

Usage:
    py tests/test_version_governance_hardening.py
"""
import sys
import os
import io
import inspect

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus      import EventBus
from core.global_state   import GlobalState, CONTENCAO_FINANCEIRA
from core.version_manager import (
    VersionManager,
    VersionCandidateExistsError,
    VersionPromotionViolationError,
    VersionPromotionOutsideOrchestratorError,
    DeprecatedVersionFlowError,
    NoPreviousBaselineError,
)

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
    def __init__(self, valid_ids=None):
        self._valid = set(valid_ids or [])
    def exists(self, sid):
        return sid in self._valid
    def add(self, sid):
        self._valid.add(sid)


def _make_vm(snapshot_store=None):
    return VersionManager(persistence=MemFile(), snapshot_store=snapshot_store)


class MockOrchestrator:
    """
    Minimal orchestrator stub that delegates to VersionManager with orchestrated=True.
    Simulates the real Orchestrator._sh_version_promote / _sh_version_rollback.
    """
    def __init__(self, vm, gs, bus, snap_store=None):
        self._vm  = vm
        self._gs  = gs
        self._bus = bus

    def receive_event(self, event_type: str, payload: dict) -> None:
        pid = payload.get("product_id", "")
        if event_type == "version_promotion_requested":
            self._vm.promote_candidate(
                pid,
                snapshot_id=payload.get("snapshot_id", ""),
                event_bus=self._bus,
                global_state=self._gs,
                financial_alert_active=payload.get("financial_alert_active", False),
                orchestrated=True,
            )
        elif event_type == "version_rollback_requested":
            self._vm.rollback_to_previous_baseline(pid, event_bus=self._bus, orchestrated=True)
        else:
            raise ValueError(f"MockOrchestrator: unknown event_type '{event_type}'")


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

def t1_promote_version_deprecated():
    """promote_version() always raises DeprecatedVersionFlowError."""
    vm  = _make_vm()
    bus = EventBus()
    vm.create_candidate("p1", version_id="v1", event_bus=bus)

    raised = False
    try:
        vm.promote_version("p1", event_bus=bus)
    except DeprecatedVersionFlowError:
        raised = True
    assert raised, "Expected DeprecatedVersionFlowError from promote_version()"


def t2_rollback_version_deprecated():
    """rollback_version() always raises DeprecatedVersionFlowError."""
    vm  = _make_vm()
    bus = EventBus()

    raised = False
    try:
        vm.rollback_version("p2", event_bus=bus)
    except DeprecatedVersionFlowError:
        raised = True
    assert raised, "Expected DeprecatedVersionFlowError from rollback_version()"


def t3_promote_candidate_without_snapshot_raises():
    """promote_candidate with empty snapshot_id raises VersionPromotionViolationError."""
    vm  = _make_vm()
    bus = EventBus()
    gs  = GlobalState(MemFile())

    vm.create_candidate("p3", version_id="v1", event_bus=bus)

    raised = False
    try:
        vm.promote_candidate("p3", snapshot_id="", event_bus=bus, global_state=gs,
                             orchestrated=True)
    except VersionPromotionViolationError:
        raised = True
    assert raised, "Expected VersionPromotionViolationError when snapshot_id is empty"


def t4_promote_candidate_outside_orchestrator_raises():
    """promote_candidate without orchestrated=True raises VersionPromotionOutsideOrchestratorError."""
    snap_store = MockSnapshotStore(valid_ids=["snap-ok"])
    vm  = _make_vm(snapshot_store=snap_store)
    bus = EventBus()
    gs  = GlobalState(MemFile())

    vm.create_candidate("p4", version_id="v1", event_bus=bus)

    raised = False
    try:
        # orchestrated defaults to False — must raise
        vm.promote_candidate("p4", snapshot_id="snap-ok", event_bus=bus, global_state=gs)
    except VersionPromotionOutsideOrchestratorError:
        raised = True
    assert raised, "Expected VersionPromotionOutsideOrchestratorError when not orchestrated"


def t5_promote_during_contencao_raises():
    """promote_candidate during CONTENÇÃO_FINANCEIRA raises VersionPromotionViolationError."""
    snap_store = MockSnapshotStore(valid_ids=["snap-ok"])
    vm  = _make_vm(snapshot_store=snap_store)
    bus = EventBus()

    gs = GlobalState(MemFile())
    gs.request_state_update(CONTENCAO_FINANCEIRA, bus, "test containment", source="test", orchestrated=False)

    vm.create_candidate("p5", version_id="v1", event_bus=bus)

    raised = False
    try:
        vm.promote_candidate("p5", snapshot_id="snap-ok", event_bus=bus,
                             global_state=gs, orchestrated=True)
    except VersionPromotionViolationError:
        raised = True
    assert raised, "Expected VersionPromotionViolationError during CONTENÇÃO_FINANCEIRA"


def t6_promote_without_candidate_raises():
    """promote_candidate with no candidate version raises VersionPromotionViolationError."""
    snap_store = MockSnapshotStore(valid_ids=["snap-ok"])
    vm  = _make_vm(snapshot_store=snap_store)
    bus = EventBus()
    gs  = GlobalState(MemFile())

    # No create_candidate called — candidate is None
    raised = False
    try:
        vm.promote_candidate("p6", snapshot_id="snap-ok", event_bus=bus,
                             global_state=gs, orchestrated=True)
    except VersionPromotionViolationError:
        raised = True
    assert raised, "Expected VersionPromotionViolationError when no candidate exists"


def t7_promote_with_financial_alert_raises():
    """promote_candidate with financial_alert_active=True raises VersionPromotionViolationError."""
    snap_store = MockSnapshotStore(valid_ids=["snap-ok"])
    vm  = _make_vm(snapshot_store=snap_store)
    bus = EventBus()
    gs  = GlobalState(MemFile())

    vm.create_candidate("p7", version_id="v1", event_bus=bus)

    raised = False
    try:
        vm.promote_candidate("p7", snapshot_id="snap-ok", event_bus=bus,
                             global_state=gs, financial_alert_active=True,
                             orchestrated=True)
    except VersionPromotionViolationError:
        raised = True
    assert raised, "Expected VersionPromotionViolationError when financial_alert_active=True"


def t8_promotion_creates_version_promoted_in_ledger():
    """Successful promotion via MockOrchestrator creates version_promoted in the ledger."""
    snap_store = MockSnapshotStore(valid_ids=["snap-real"])
    vm  = _make_vm(snapshot_store=snap_store)
    bus = EventBus()
    gs  = GlobalState(MemFile())
    orch = MockOrchestrator(vm, gs, bus, snap_store)

    vm.create_candidate("p8", version_id="v1", event_bus=bus)

    orch.receive_event("version_promotion_requested", {
        "product_id": "p8",
        "snapshot_id": "snap-real",
    })

    types = [e["event_type"] for e in bus.get_events()]
    assert "version_promoted" in types, \
        f"Expected 'version_promoted' in ledger. Got: {types}"

    # Baseline must be the promoted candidate
    assert vm.get_baseline("p8") == "v1", \
        f"Expected baseline='v1', got '{vm.get_baseline('p8')}'"

    # Candidate must be None after promotion
    assert vm.get_candidate("p8") is None, \
        "candidate_version must be None after promotion"


def t9_rollback_only_via_orchestrated():
    """rollback_to_previous_baseline without orchestrated=True raises VersionPromotionOutsideOrchestratorError."""
    snap_store = MockSnapshotStore(valid_ids=["snap-1", "snap-2"])
    vm  = _make_vm(snapshot_store=snap_store)
    bus = EventBus()
    gs  = GlobalState(MemFile())
    orch = MockOrchestrator(vm, gs, bus)

    # Build two baselines
    vm.create_candidate("p9", version_id="v1", event_bus=bus)
    orch.receive_event("version_promotion_requested", {"product_id": "p9", "snapshot_id": "snap-1"})
    vm.create_candidate("p9", version_id="v2", event_bus=bus)
    orch.receive_event("version_promotion_requested", {"product_id": "p9", "snapshot_id": "snap-2"})

    # Direct rollback must be blocked
    raised = False
    try:
        vm.rollback_to_previous_baseline("p9", event_bus=bus)   # orchestrated missing
    except VersionPromotionOutsideOrchestratorError:
        raised = True
    assert raised, "Expected VersionPromotionOutsideOrchestratorError on direct rollback"

    # Via orchestrator should succeed
    orch.receive_event("version_rollback_requested", {"product_id": "p9"})
    assert vm.get_baseline("p9") == "v1", \
        f"Expected baseline='v1' after rollback, got '{vm.get_baseline('p9')}'"

    types = [e["event_type"] for e in bus.get_events()]
    assert "version_rollback_executed" in types, \
        f"Expected 'version_rollback_executed' in ledger. Got: {types}"


def t10_market_loop_no_direct_version_manager_calls():
    """
    MarketLoopEngine source code must NOT contain direct calls to:
      - version_manager.promote_version
      - version_manager.rollback_version
    
    All version mutations must go through orchestrator.receive_event().
    """
    import core.market_loop_engine as mle_module
    src = inspect.getsource(mle_module)

    forbidden = [
        "version_manager.promote_version",
        "version_manager.rollback_version",
        ".promote_version(",
        ".rollback_version(",
    ]
    for pattern in forbidden:
        assert pattern not in src, (
            f"Forbidden pattern found in market_loop_engine.py: '{pattern}'. "
            "MarketLoopEngine must route all version mutations through "
            "orchestrator.receive_event()."
        )

    # Must contain orchestrator.receive_event calls
    assert "orchestrator.receive_event" in src, (
        "market_loop_engine.py must call orchestrator.receive_event() "
        "for version promotion/rollback."
    )


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 66)
    print("  VERSION GOVERNANCE HARDENING — TEST SUITE (V1)")
    print("=" * 66)

    test("T01 promote_version() raises DeprecatedVersionFlowError",        t1_promote_version_deprecated)
    test("T02 rollback_version() raises DeprecatedVersionFlowError",       t2_rollback_version_deprecated)
    test("T03 promote_candidate without snapshot raises Violation",        t3_promote_candidate_without_snapshot_raises)
    test("T04 promote_candidate outside orchestrator raises Guard",        t4_promote_candidate_outside_orchestrator_raises)
    test("T05 promote during CONTENÇÃO raises Violation",                  t5_promote_during_contencao_raises)
    test("T06 promote without candidate raises Violation",                 t6_promote_without_candidate_raises)
    test("T07 promote with financial_alert=True raises Violation",         t7_promote_with_financial_alert_raises)
    test("T08 successful promotion creates version_promoted in ledger",    t8_promotion_creates_version_promoted_in_ledger)
    test("T09 rollback only via orchestrated=True",                        t9_rollback_only_via_orchestrated)
    test("T10 MarketLoop has no direct VersionManager calls",              t10_market_loop_no_direct_version_manager_calls)

    print("\n" + "=" * 66)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  VERSION GOVERNANCE — HARDENED")
        print("  CONSTITUTIONAL VERSION FLOW — LOCKED")
    else:
        print("  VERSION GOVERNANCE — VIOLATIONS DETECTED (see above)")
    print("=" * 66 + "\n")

    sys.exit(0 if passed == total else 1)
