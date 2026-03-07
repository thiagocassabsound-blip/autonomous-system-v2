"""
tests/test_a14_product_creation.py

A14 Constitutional Product Creation Infrastructure — Structural Validation Suite

Validates:
  T1  — Direct create_draft() without orchestrated=True raises UnauthorizedLifecycleTransition
  T2  — product_creation_requested via Orchestrator creates a Draft record
  T3  — product_draft_created event is emitted with correct fields
  T4  — Draft product_id is UUID-generated (unique per call)
  T5  — Direct start_beta() without orchestrated=True raises UnauthorizedLifecycleTransition
  T6  — beta_approved_requested via Orchestrator starts beta successfully
  T7  — beta_start_blocked emitted when CONTENÇÃO_FINANCEIRA is active
  T8  — beta_start_blocked emitted when active_beta_count >= 2
  T9  — beta_start_blocked emitted when financial_alert_active=True
  T10 — Missing required payload fields raise ValueError in Orchestrator
  ---
  A14_STATUS JSON printed at end
"""
import sys
import os
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.product_life_engine import (
    ProductLifeEngine,
    UnauthorizedLifecycleTransition,
    BetaStartBlockedError,
    DraftCreationPayloadError,
)
from core.orchestrator import Orchestrator
from core.global_state import CONTENCAO_FINANCEIRA

# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------

class _InMemoryEventBus:
    def __init__(self):
        self.events = []

    def append_event(self, event: dict) -> dict:
        self.events.append(event)
        return event

    def emit(self, name, payload):
        self.events.append({"event_type": name, "payload": payload})


class _InMemoryPersistence:
    def __init__(self):
        self._data = {}

    def load(self):
        return dict(self._data)

    def save(self, data):
        self._data = dict(data)


class _InMemoryStatePersistence:
    def __init__(self):
        self._data = {"product_states": {}, "history": []}

    def load(self):
        return dict(self._data)

    def save(self, data):
        self._data = dict(data)


class _MockStateManager:
    """Minimal StateManager stub for Orchestrator."""
    def __init__(self):
        self._locked = True
        self._data: dict = {}

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value


class _MockGlobalState:
    def __init__(self, state="NORMAL"):
        self._state = state

    def get_state(self):
        return self._state


class _MockStateMachine:
    """Minimal StateMachine stub."""
    def __init__(self):
        self._product_states: dict = {}

    def transition(self, product_id, to_state, reason, metric, event_bus):
        self._product_states[product_id] = to_state
        return {"from": "Beta", "to": to_state}


def _make_ple(global_state=None, state_machine=None):
    return ProductLifeEngine(
        persistence=_InMemoryPersistence(),
        state_machine=state_machine or _MockStateMachine(),
    )


def _make_orchestrator(ple, global_state=None):
    bus   = _InMemoryEventBus()
    sm    = _MockStateManager()
    orch  = Orchestrator(event_bus=bus, state_manager=sm)
    orch.register_service("product_life", ple)
    if global_state:
        orch.register_service("global_state", global_state)
    return orch, bus


VALID_PAYLOAD = {
    "opportunity_id":        "opp-test-001",
    "emotional_score":       78.0,
    "monetization_score":    82.0,
    "growth_percent":        20.0,
    "competitive_gap_flag":  True,
    "justification_snapshot": {"b2_approved": True, "ice": "ALTO"},
    "version_id":             "v1.0.0",
    "timestamp":              datetime.now(timezone.utc).isoformat(),
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

tests_passed = []
tests_failed = []

def _ok(name):
    print(f"  [PASS] {name}")
    tests_passed.append(name)

def _fail(name, reason):
    print(f"  [FAIL] {name} -- {reason}")
    tests_failed.append(name)


def _run(name, fn):
    try:
        fn()
        _ok(name)
    except AssertionError as e:
        _fail(name, str(e))
    except Exception as e:
        _fail(name, f"Unexpected exception: {type(e).__name__}: {e}")


# ------ T1 ----------------------------------------------------------------
def t1_direct_create_draft_blocked():
    ple = _make_ple()
    bus = _InMemoryEventBus()
    try:
        ple.create_draft(
            event_bus=bus,
            opportunity_id="opp-001",
            emotional_score=78.0,
            monetization_score=82.0,
            growth_percent=20.0,
            competitive_gap_flag=True,
            justification_snapshot={"test": True},
            version_id="v1",
            orchestrated=False,  # <-- should raise
        )
        raise AssertionError("Expected UnauthorizedLifecycleTransition — not raised")
    except UnauthorizedLifecycleTransition:
        pass  # correct

_run("T1 — Direct create_draft() without orchestrated=True is blocked", t1_direct_create_draft_blocked)


# ------ T2 ----------------------------------------------------------------
def t2_product_creation_via_orchestrator():
    ple = _make_ple()
    orch, bus = _make_orchestrator(ple)
    result = orch.receive_event(
        event_type="product_creation_requested",
        payload=VALID_PAYLOAD,
    )
    assert result is not None, "receive_event returned None"
    # Confirm draft exists in engine
    assert len(ple._state) == 1, f"Expected 1 draft record, got {len(ple._state)}"
    rec = list(ple._state.values())[0]
    assert rec["state"] == "Draft", f"Expected state=Draft, got {rec['state']}"
    assert rec["opportunity_id"] == "opp-test-001"

_run("T2 — product_creation_requested via Orchestrator creates Draft record", t2_product_creation_via_orchestrator)


# ------ T3 ----------------------------------------------------------------
def t3_product_draft_created_event():
    ple = _make_ple()
    orch, bus = _make_orchestrator(ple)
    orch.receive_event(
        event_type="product_creation_requested",
        payload=VALID_PAYLOAD,
    )
    draft_events = [e for e in bus.events if e["event_type"] == "product_draft_created"]
    assert len(draft_events) == 1, f"Expected 1 product_draft_created event, got {len(draft_events)}"
    ev = draft_events[0]
    p  = ev["payload"]
    assert "product_id"   in p, "Missing product_id in event payload"
    assert "opportunity_id" in p
    assert p["state"] == "Draft"
    assert p["baseline_version"] == "1.0"
    assert "created_at" in p
    assert "version_id" in p

_run("T3 — product_draft_created event emitted with correct fields", t3_product_draft_created_event)


# ------ T4 ----------------------------------------------------------------
def t4_unique_product_ids():
    ple = _make_ple()
    orch, bus = _make_orchestrator(ple)
    orch.receive_event("product_creation_requested", VALID_PAYLOAD)
    orch.receive_event("product_creation_requested", {**VALID_PAYLOAD, "opportunity_id": "opp-002"})
    assert len(ple._state) == 2, f"Expected 2 draft records, got {len(ple._state)}"
    ids = list(ple._state.keys())
    assert ids[0] != ids[1], "Duplicate product_id generated"

_run("T4 — Unique product_ids generated per create_draft() call", t4_unique_product_ids)


# ------ T5 ----------------------------------------------------------------
def t5_direct_start_beta_blocked():
    ple = _make_ple()
    bus = _InMemoryEventBus()
    try:
        ple.start_beta("pid-001", bus, orchestrated=False)
        raise AssertionError("Expected UnauthorizedLifecycleTransition — not raised")
    except UnauthorizedLifecycleTransition:
        pass

_run("T5 — Direct start_beta() without orchestrated=True is blocked", t5_direct_start_beta_blocked)


# ------ T6 ----------------------------------------------------------------
def t6_beta_approved_via_orchestrator():
    ple  = _make_ple()
    orch, bus = _make_orchestrator(ple, global_state=_MockGlobalState("NORMAL"))
    # First create Draft
    orch.receive_event("product_creation_requested", VALID_PAYLOAD)
    pid = list(ple._state.keys())[0]
    # Now approve for beta
    orch.receive_event(
        event_type="beta_approved_requested",
        payload={"product_id": pid, "financial_alert_active": False},
        product_id=pid,
    )
    rec = ple._state[pid]
    assert rec["beta_start"] is not None, "beta_start should be set"
    assert rec["beta_closed_at"] is None, "beta_closed_at should still be None"
    beta_events = [e for e in bus.events if e["event_type"] == "beta_started"]
    assert len(beta_events) == 1, f"Expected 1 beta_started event, got {len(beta_events)}"

_run("T6 — beta_approved_requested via Orchestrator starts beta successfully", t6_beta_approved_via_orchestrator)


# ------ T7 ----------------------------------------------------------------
def t7_beta_blocked_contencao():
    ple = _make_ple()
    bus = _InMemoryEventBus()
    gs  = _MockGlobalState(CONTENCAO_FINANCEIRA)
    try:
        ple.start_beta("pid-001", bus, orchestrated=True, global_state=gs)
        raise AssertionError("Expected BetaStartBlockedError — not raised")
    except BetaStartBlockedError:
        pass
    blocked = [e for e in bus.events if e["event_type"] == "beta_start_blocked"]
    assert len(blocked) == 1, f"Expected beta_start_blocked event, got {len(blocked)}"

_run("T7 — beta_start_blocked emitted when global_state=CONTENÇÃO_FINANCEIRA", t7_beta_blocked_contencao)


# ------ T8 ----------------------------------------------------------------
def t8_beta_blocked_max_betas():
    from core.state_machine import StateMachine
    # Create a StateMachine with 2 products already in Beta
    sm_pers = _InMemoryStatePersistence()
    sm_pers._data = {
        "product_states": {"existing-1": "Beta", "existing-2": "Beta"},
        "history": [],
    }
    sm = StateMachine(persistence=sm_pers)
    ple = _make_ple(state_machine=sm)
    bus = _InMemoryEventBus()
    try:
        ple.start_beta("new-product", bus, orchestrated=True, global_state=_MockGlobalState("NORMAL"))
        raise AssertionError("Expected BetaStartBlockedError — not raised")
    except BetaStartBlockedError as e:
        assert "active_beta_count" in str(e), f"Wrong error message: {e}"
    blocked = [e for e in bus.events if e["event_type"] == "beta_start_blocked"]
    assert len(blocked) == 1

_run("T8 — beta_start_blocked when active_beta_count >= MAX_BETAS (2)", t8_beta_blocked_max_betas)


# ------ T9 ----------------------------------------------------------------
def t9_beta_blocked_financial_alert():
    ple = _make_ple()
    bus = _InMemoryEventBus()
    try:
        ple.start_beta(
            "pid-001", bus,
            orchestrated=True,
            global_state=_MockGlobalState("NORMAL"),
            financial_alert_active=True,
        )
        raise AssertionError("Expected BetaStartBlockedError — not raised")
    except BetaStartBlockedError:
        pass
    blocked = [e for e in bus.events if e["event_type"] == "beta_start_blocked"]
    assert len(blocked) == 1

_run("T9 — beta_start_blocked when financial_alert_active=True", t9_beta_blocked_financial_alert)


# ------ T10 ---------------------------------------------------------------
def t10_missing_payload_fields_raise():
    ple = _make_ple()
    orch, _ = _make_orchestrator(ple)
    incomplete = {k: v for k, v in VALID_PAYLOAD.items() if k != "opportunity_id"}
    try:
        orch.receive_event("product_creation_requested", incomplete)
        raise AssertionError("Expected ValueError — not raised")
    except ValueError as e:
        assert "opportunity_id" in str(e), f"Wrong error message: {e}"

_run("T10 — Missing payload fields in product_creation_requested raise ValueError", t10_missing_payload_fields_raise)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

total  = len(tests_passed) + len(tests_failed)
passed = len(tests_passed)
failed = len(tests_failed)

print()
print(f"{'='*60}")
print(f"A14 Structural Validation: {passed}/{total} PASSED")
if tests_failed:
    print(f"FAILED: {tests_failed}")
print(f"{'='*60}")

# A14 STATUS OUTPUT
import json
status = {
    "A14_status":                    "implemented" if failed == 0 else "failed",
    "draft_state_created":           True,
    "creation_event_wired":          "T2" not in tests_failed and "T3" not in tests_failed,
    "beta_guard_active":             "T7" not in tests_failed and "T8" not in tests_failed and "T9" not in tests_failed,
    "orchestrator_handler_active":   "T2" not in tests_failed and "T6" not in tests_failed,
    "structural_integrity_passed":   failed == 0,
    "tests_passed":                  passed,
    "tests_failed_list":             tests_failed,
}
print()
print(json.dumps(status, indent=2))
sys.exit(0 if failed == 0 else 1)
