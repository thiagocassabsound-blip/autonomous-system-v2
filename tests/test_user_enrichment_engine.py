"""
tests/test_user_enrichment_engine.py — B4 / Bloco 28 Validation Suite

12 closure criteria:
  1.  lifetime_value calculado corretamente
  2.  refund_ratio correto
  3.  dominant_channel correto
  4.  device_profile registrado
  5.  risk_score calculado conforme regras
  6.  classification_tag gerada corretamente
  7.  export_signal_ready true quando elegível
  8.  export_signal_ready false quando não elegível
  9.  activity_recency calculado corretamente
 10.  nenhuma escrita fora do Orchestrator (DirectWriteError)
 11.  persistência append-only
 12.  execução direta do engine lança erro

Usage:
    py tests/test_user_enrichment_engine.py
"""
import sys
import os
import io
from datetime import datetime, timedelta, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus              import EventBus
from core.user_enrichment_engine import (
    UserEnrichmentEngine,
    UserEnrichmentDirectExecutionError,
    compute_lifetime_value,
    compute_refund_ratio,
    compute_dominant_channel,
    compute_dominant_device,
    compute_activity_recency,
    compute_risk_score,
    compute_classification_tags,
    compute_export_signal,
)
from core.state_manager          import StateManager, DirectWriteError


# ====================================================================
# In-memory stubs
# ====================================================================

class MemEnrichmentPersistence:
    def __init__(self):
        self._records = []
    def append_record(self, r):
        import copy; self._records.append(copy.deepcopy(r))
    def load_all(self):
        import copy; return copy.deepcopy(self._records)


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

def _make_engine(orchestrator=None, persistence=None):
    if orchestrator is None:
        orchestrator = MockOrchestrator(EventBus())
    return UserEnrichmentEngine(
        orchestrator=orchestrator,
        persistence=persistence or MemEnrichmentPersistence()
    )


NOW = datetime(2026, 2, 23, 21, 39, 30, tzinfo=timezone.utc)


def _update(engine, user_id="u1", **overrides):
    defaults = dict(
        user_id=user_id,
        payment_amounts=[100.0, 150.0, 200.0],
        refund_amounts=[],
        total_refunds=0,
        channel_counts={"organic": 2, "paid_social": 1},
        device_counts={"mobile": 3, "desktop": 1},
        last_purchase_ts=(NOW - timedelta(days=5)).isoformat(),
        avg_ltv_product=0.0,
    )
    defaults.update(overrides)
    return engine.update_user_profile(**defaults)


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

def t1_lifetime_value():
    """lifetime_value = Σ payments − Σ refunds."""
    ltv = compute_lifetime_value([100.0, 200.0, 50.0], [30.0])
    assert ltv == 320.0, f"Expected 320.0, got {ltv}"

    ltv2 = compute_lifetime_value([99.99], [99.99])
    assert ltv2 == 0.0, f"Fully refunded LTV should be 0, got {ltv2}"

    ltv3 = compute_lifetime_value([], [])
    assert ltv3 == 0.0, f"Empty LTV should be 0, got {ltv3}"


def t2_refund_ratio():
    """refund_ratio = refunds / purchases; 0 if no purchases."""
    assert compute_refund_ratio(1, 4) == 0.25
    assert compute_refund_ratio(0, 5) == 0.0
    assert compute_refund_ratio(3, 0) == 0.0   # guard: no purchases
    assert compute_refund_ratio(2, 2) == 1.0


def t3_dominant_channel():
    """dominant_channel = channel with highest purchase count."""
    assert compute_dominant_channel({"organic": 5, "paid": 3}) == "organic"
    assert compute_dominant_channel({"paid": 10, "organic": 2}) == "paid"
    assert compute_dominant_channel({}) is None


def t4_device_profile():
    """device_profile = device with highest usage count."""
    assert compute_dominant_device({"mobile": 7, "desktop": 2}) == "mobile"
    assert compute_dominant_device({"desktop": 5, "tablet": 5, "mobile": 1}) in ("desktop", "tablet")
    assert compute_dominant_device({}) is None

    # Verify it appears in full engine snapshot
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)
    snap = _update(
        eng,
        device_counts={"tablet": 10, "mobile": 1},
    )
    assert snap["metrics_snapshot"]["device_profile"] == "tablet"


def t5_risk_score():
    """risk_score calculated according to all rules."""
    # High refund ratio: +40 with 1 purchase (no repeat deduction)
    score = compute_risk_score(0.6, 1, 200.0, 30.0)
    assert score >= 40, f"High refund ratio (+40) + single purchase (+10) = 50, got {score}"

    # Medium refund ratio: +20 with 1 purchase (+10 single) = 30
    score2 = compute_risk_score(0.4, 1, 200.0, 30.0)
    assert 20 <= score2 <= 50, f"Medium refund ratio should add ~20-30, got {score2}"

    # High refund with repeat buyer: +40 -20 = +20
    score_rep = compute_risk_score(0.6, 5, 200.0, 30.0)
    assert score_rep >= 20, f"High refund + repeat buyer should yield >=20, got {score_rep}"

    # Single purchase: +10
    score3 = compute_risk_score(0.0, 1, 50.0, 10.0)
    assert score3 >= 10, f"Single purchase should add 10, got {score3}"

    # Activity recency > 90 days: +10
    score5 = compute_risk_score(0.0, 3, 200.0, 95.0)
    # -20 (repeat) + 10 (recency) = -10, clamped to 0
    assert score5 == 0, f"Expected 0 after clamping, got {score5}"

    # LTV above product average: -10
    score6 = compute_risk_score(0.0, 1, 500.0, 5.0, avg_ltv_product=100.0)
    # +10 (single) -10 (ltv above avg) = 0
    assert score6 == 0, f"Expected 0 (single+ltv bonus cancel), got {score6}"

    # All clamp: never below 0 or above 100
    score_low = compute_risk_score(0.0, 10, 1000.0, 0.0, avg_ltv_product=50.0)
    assert 0 <= score_low <= 100
    score_high = compute_risk_score(1.0, 1, 0.0, 200.0)
    assert 0 <= score_high <= 100


def t6_classification_tags():
    """classification_tag list generated correctly for each rule."""
    # high_value_user: LTV ≥ 100 AND refund_ratio ≤ 0.2
    tags = compute_classification_tags(200.0, 0.1, 5, 10.0, 10)
    assert "high_value_user" in tags, f"Expected high_value_user, got {tags}"
    assert "repeat_buyer"    in tags, f"Expected repeat_buyer, got {tags}"
    assert "stable_user"     in tags, f"Expected stable_user (risk=10), got {tags}"

    # high_refund_risk: refund_ratio > 0.5
    tags2 = compute_classification_tags(50.0, 0.6, 2, 10.0, 60)
    assert "high_refund_risk" in tags2

    # inactive_user: recency > 90
    tags3 = compute_classification_tags(50.0, 0.0, 2, 100.0, 20)
    assert "inactive_user" in tags3

    # stable_user: risk_score ≤ 30
    tags4 = compute_classification_tags(10.0, 0.0, 1, 10.0, 30)
    assert "stable_user" in tags4

    # No high_value_user if LTV < 100
    tags5 = compute_classification_tags(50.0, 0.0, 2, 5.0, 5)
    assert "high_value_user" not in tags5


def t7_export_signal_true():
    """export_signal_ready=True when high_value_user OR (repeat_buyer AND refund≤0.3)."""
    # Case 1: high_value_user
    assert compute_export_signal(["high_value_user", "stable_user"], 0.1) is True

    # Case 2: repeat_buyer + low refund
    assert compute_export_signal(["repeat_buyer", "stable_user"], 0.2) is True

    # Case 3: repeat_buyer exactly at boundary 0.3
    assert compute_export_signal(["repeat_buyer"], 0.3) is True

    # Verify via full engine call
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)
    snap = _update(
        eng,
        payment_amounts=[200.0, 300.0, 400.0],  # LTV=900, 3 purchases
        refund_amounts=[],
        total_refunds=0,
        avg_ltv_product=0.0,
    )
    assert snap["export_signal_ready"] is True

    types = [e["event_type"] for e in bus.get_events()]
    assert "user_export_signal_ready" in types


def t8_export_signal_false():
    """export_signal_ready=False when not eligible."""
    # repeat_buyer but refund > 0.3
    assert compute_export_signal(["repeat_buyer"], 0.35) is False

    # No qualifying tag
    assert compute_export_signal(["inactive_user", "high_refund_risk"], 0.1) is False
    assert compute_export_signal([], 0.0) is False

    # Verify via full engine call: single purchase, high refund
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)
    snap = _update(
        eng,
        payment_amounts=[50.0],
        refund_amounts=[50.0],
        total_refunds=1,
    )
    assert snap["export_signal_ready"] is False
    types = [e["event_type"] for e in bus.get_events()]
    assert "user_export_signal_ready" not in types


def t9_activity_recency():
    """activity_recency stored in days."""
    now = datetime(2026, 2, 23, tzinfo=timezone.utc)
    past = (now - timedelta(days=30)).isoformat()
    recency = compute_activity_recency(past, now)
    assert abs(recency - 30.0) < 0.01, f"Expected ~30 days, got {recency}"

    # None → inf
    assert compute_activity_recency(None, now) == float("inf")

    # Very recent: 1 day
    yesterday = (now - timedelta(days=1)).isoformat()
    r2 = compute_activity_recency(yesterday, now)
    assert abs(r2 - 1.0) < 0.01, f"Expected ~1 day, got {r2}"

    # Verify stored in snapshot
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orchestrator=orc)
    fixed_now = datetime(2026, 2, 23, tzinfo=timezone.utc)
    eng._now = lambda: fixed_now
    snap = _update(
        eng,
        last_purchase_ts=(fixed_now - timedelta(days=45)).isoformat(),
    )
    stored = snap["metrics_snapshot"]["activity_recency"]
    assert abs(stored - 45.0) < 0.1, f"Expected ~45 days, got {stored}"


def t10_direct_write_blocked():
    """StateManager.set() raises DirectWriteError — no writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("enrichment_bypass", {"inject": True})
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


def t11_persistence_append_only():
    """Records accumulate monotonically; count never decreases."""
    bus  = EventBus()
    orc  = MockOrchestrator(bus)
    pers = MemEnrichmentPersistence()
    eng  = _make_engine(orchestrator=orc, persistence=pers)
 
    count_0 = len(pers.load_all())
 
    _update(eng, user_id="u-a")
    count_1 = len(pers.load_all())
    assert count_1 > count_0, "First update should add a record"
 
    _update(eng, user_id="u-b")
    count_2 = len(pers.load_all())
    assert count_2 > count_1, "Second update should add another record"
 
    # A second update for the same user also adds (append-only)
    _update(eng, user_id="u-a", payment_amounts=[999.0], refund_amounts=[], total_refunds=0)
    count_3 = len(pers.load_all())
    assert count_3 > count_2, "Re-update for same user must still append a new record"

    # Monotonicity check
    counts = [count_0, count_1, count_2, count_3]
    for i in range(1, len(counts)):
        assert counts[i] >= counts[i - 1]


def t12_direct_execution_guard():
    """execute_directly() and execute_media_campaign() always raise."""
    # Static method
    raised_direct = False
    try:
        UserEnrichmentEngine.execute_directly()
    except UserEnrichmentDirectExecutionError:
        raised_direct = True
    assert raised_direct, "Expected UserEnrichmentDirectExecutionError from execute_directly()"

    # Instance method
    eng = _make_engine()
    raised_media = False
    try:
        eng.execute_media_campaign()
    except UserEnrichmentDirectExecutionError:
        raised_media = True
    assert raised_media, "Expected UserEnrichmentDirectExecutionError from execute_media_campaign()"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 66)
    print("  B4 / BLOCO 28 USER ENRICHMENT ENGINE — TEST SUITE")
    print("=" * 66)

    test("lifetime_value calculado corretamente",       t1_lifetime_value)
    test("refund_ratio correto",                        t2_refund_ratio)
    test("dominant_channel correto",                    t3_dominant_channel)
    test("device_profile registrado",                   t4_device_profile)
    test("risk_score calculado conforme regras",        t5_risk_score)
    test("classification_tag gerada corretamente",      t6_classification_tags)
    test("export_signal_ready true quando elegível",    t7_export_signal_true)
    test("export_signal_ready false quando não elig.",  t8_export_signal_false)
    test("activity_recency calculado corretamente",     t9_activity_recency)
    test("nenhuma escrita fora do Orchestrator",        t10_direct_write_blocked)
    test("persistência append-only",                    t11_persistence_append_only)
    test("execução direta do engine lança erro",        t12_direct_execution_guard)

    print("\n" + "=" * 66)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  B4 / BLOCO 28 USER ENRICHMENT ENGINE — VALID")
        print("  B4 LOCKED")
    else:
        print("  B4 — INVALID (see failures above)")
    print("=" * 66 + "\n")

    sys.exit(0 if passed == total else 1)
