"""
tests/test_feedback_incentive_engine.py — B3 / Bloco 27 Validation Suite

10 closure criteria:
  1.  engagement < 30% → não dispara
  2.  usage_time < 300s → não dispara
  3.  texto < 50 → rejeita
  4.  texto ≥ 50 → valida
  5.  validação concede lifetime
  6.  refund revoga lifetime
  7.  nenhuma escrita fora do Orchestrator (DirectWriteError)
  8.  engine não promove versão (FeedbackEngineVersionPromotionError)
  9.  persistência é append-only
 10.  execução direta do engine lança erro (FeedbackDirectExecutionError)

Usage:
    py tests/test_feedback_incentive_engine.py
"""
import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus                    import EventBus
from core.feedback_incentive_engine    import (
    FeedbackIncentiveEngine,
    FeedbackProductConfig,
    FeedbackDirectExecutionError,
    FeedbackEngineVersionPromotionError,
)
from core.state_manager                import StateManager, DirectWriteError


# ====================================================================
# In-memory stubs
# ====================================================================

class MemFeedbackPersistence:
    def __init__(self):
        self._records = []
    def append_record(self, r):
        import copy; self._records.append(copy.deepcopy(r))
    def load_all(self):
        import copy; return copy.deepcopy(self._records)


def _make_engine(persistence=None):
    return FeedbackIncentiveEngine(
        persistence=persistence or MemFeedbackPersistence()
    )


def _make_config(metric_type="module_progress", total=100.0, threshold=0.30):
    return FeedbackProductConfig(
        product_id="prod-1",
        engagement_metric_type=metric_type,
        engagement_metric_total=total,
        engagement_threshold=threshold,
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

def t1_engagement_below_threshold():
    """engagement < 30% → não dispara feedback_requested."""
    eng = _make_engine()
    bus = EventBus()
    cfg = _make_config()

    result = eng.evaluate_engagement(
        config=cfg,
        user_id="user-1",
        engagement_value=20.0,   # 20/100 = 20% < 30%
        event_bus=bus,
    )

    assert result["triggered"] is False
    types = [e["event_type"] for e in bus.get_events()]
    assert "feedback_requested" not in types, (
        "feedback_requested must NOT be emitted below threshold"
    )
    assert "engagement_evaluated" in types


def t2_usage_time_blindagem():
    """usage_time: ratio ≥ 30% but tempo_real < 300s → não dispara."""
    eng = _make_engine()
    bus = EventBus()
    cfg = _make_config(metric_type="usage_time", total=100.0)

    # ratio = 50% (above threshold) but tempo_real = 200s (below 300)
    result = eng.evaluate_engagement(
        config=cfg,
        user_id="user-1",
        engagement_value=50.0,
        tempo_real=200.0,       # < 300
        event_bus=bus,
    )

    assert result["triggered"] is False, (
        "usage_time trigger must not fire when tempo_real < 300s"
    )
    types = [e["event_type"] for e in bus.get_events()]
    assert "feedback_requested" not in types

    # Verify: with tempo_real ≥ 300 it does fire
    bus2 = EventBus()
    result2 = eng.evaluate_engagement(
        config=cfg,
        user_id="user-1",
        engagement_value=50.0,
        tempo_real=310.0,       # ≥ 300
        event_bus=bus2,
    )
    assert result2["triggered"] is True
    types2 = [e["event_type"] for e in bus2.get_events()]
    assert "feedback_requested" in types2


def t3_feedback_text_too_short():
    """texto < 50 chars → feedback_rejected_invalid."""
    eng = _make_engine()
    bus = EventBus()

    result = eng.submit_feedback(
        user_id="user-1",
        product_id="prod-1",
        feedback_text="Short text",   # < 50 chars
        event_bus=bus,
    )

    assert result["valid"] is False
    types = [e["event_type"] for e in bus.get_events()]
    assert "feedback_rejected_invalid" in types
    assert "feedback_validated"        not in types


def t4_feedback_text_valid():
    """texto ≥ 50 chars → feedback_submitted + feedback_validated."""
    eng = _make_engine()
    bus = EventBus()

    long_text = "A" * 55   # exactly 55 chars ≥ 50
    result = eng.submit_feedback(
        user_id="user-1",
        product_id="prod-1",
        feedback_text=long_text,
        event_bus=bus,
    )

    assert result["valid"] is True
    types = [e["event_type"] for e in bus.get_events()]
    assert "feedback_submitted"         in types
    assert "feedback_validated"         in types
    assert "feedback_rejected_invalid"  not in types


def t5_lifetime_grant_after_feedback():
    """Após feedback_validated → lifetime_upgrade_granted emitido e registrado."""
    eng = _make_engine()
    bus = EventBus()

    # Validate feedback first
    eng.submit_feedback(
        user_id="user-1",
        product_id="prod-1",
        feedback_text="B" * 60,
        event_bus=bus,
    )

    # Grant lifetime (Orchestrator would call this after feedback_validated)
    bus2 = EventBus()
    grant = eng.grant_lifetime_upgrade(
        user_id="user-1",
        product_id="prod-1",
        metadata={"source": "feedback_validated"},
        event_bus=bus2,
    )

    types = [e["event_type"] for e in bus2.get_events()]
    assert "lifetime_upgrade_granted" in types

    # Verify in-memory index
    assert eng.has_lifetime_grant("user-1", "prod-1") is True

    # Verify grant record has required fields
    for field in ["event_id", "timestamp", "user_id", "product_id", "event_type"]:
        assert field in grant, f"Missing field '{field}' in grant record"


def t6_refund_revokes_lifetime():
    """refund_completed → lifetime_upgrade_revoked + access_revoked."""
    eng = _make_engine()
    bus = EventBus()

    # Grant first
    eng.grant_lifetime_upgrade(
        user_id="user-1",
        product_id="prod-1",
        event_bus=bus,
    )
    assert eng.has_lifetime_grant("user-1", "prod-1") is True

    # Simulate A10 refund_completed → Orchestrator calls revoke
    bus2 = EventBus()
    revoked = eng.revoke_lifetime_upgrade(
        user_id="user-1",
        product_id="prod-1",
        reason="refund_completed",
        event_bus=bus2,
    )

    assert revoked is True
    assert eng.has_lifetime_grant("user-1", "prod-1") is False

    types = [e["event_type"] for e in bus2.get_events()]
    assert "lifetime_upgrade_revoked" in types
    assert "access_revoked"           in types

    # Second revoke with no active grant returns False (idempotent)
    bus3 = EventBus()
    revoked2 = eng.revoke_lifetime_upgrade(
        user_id="user-1",
        product_id="prod-1",
        reason="refund_completed",
        event_bus=bus3,
    )
    assert revoked2 is False


def t7_direct_write_blocked():
    """StateManager.set() raises DirectWriteError — no writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("feedback_bypass", {"inject": True})
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


def t8_version_promotion_forbidden():
    """promote_version_directly() always raises FeedbackEngineVersionPromotionError."""
    eng = _make_engine()
    raised = False
    try:
        eng.promote_version_directly()
    except FeedbackEngineVersionPromotionError:
        raised = True
    assert raised, "Expected FeedbackEngineVersionPromotionError"


def t9_persistence_is_append_only():
    """
    Records written by the engine accumulate monotonically.
    Count should increase with each write, never decrease.
    """
    pers = MemFeedbackPersistence()
    eng  = _make_engine(persistence=pers)
    bus  = EventBus()
    cfg  = _make_config()

    count_0 = len(pers.load_all())

    eng.evaluate_engagement(
        config=cfg, user_id="u1", engagement_value=80.0, event_bus=bus
    )
    count_1 = len(pers.load_all())
    assert count_1 > count_0, "Records should accumulate after engagement eval"

    eng.submit_feedback(
        user_id="u1", product_id="prod-1", feedback_text="Z" * 60, event_bus=bus
    )
    count_2 = len(pers.load_all())
    assert count_2 > count_1, "Records should accumulate after feedback submit"

    eng.grant_lifetime_upgrade(
        user_id="u1", product_id="prod-1", event_bus=bus
    )
    count_3 = len(pers.load_all())
    assert count_3 > count_2, "Records should accumulate after lifetime grant"

    eng.revoke_lifetime_upgrade(
        user_id="u1", product_id="prod-1", event_bus=bus
    )
    count_4 = len(pers.load_all())
    assert count_4 > count_3, "Records should accumulate after revocation"

    # Monotonicity: count should never decrease
    counts = [count_0, count_1, count_2, count_3, count_4]
    for i in range(1, len(counts)):
        assert counts[i] >= counts[i - 1], (
            f"Record count decreased: {counts[i - 1]} → {counts[i]}"
        )


def t10_direct_execution_guard():
    """execute_directly() always raises FeedbackDirectExecutionError."""
    raised = False
    try:
        FeedbackIncentiveEngine.execute_directly()
    except FeedbackDirectExecutionError:
        raised = True
    assert raised, "Expected FeedbackDirectExecutionError from execute_directly()"

    # Also verify engagement_ratio threshold exactly at boundary
    eng = _make_engine()
    bus = EventBus()
    cfg = _make_config(total=100.0, threshold=0.30)

    # Exactly at threshold → triggers
    result = eng.evaluate_engagement(
        config=cfg, user_id="u-exact", engagement_value=30.0, event_bus=bus
    )
    assert result["triggered"] is True, "ratio == threshold should trigger"

    # One unit below → does not trigger
    bus2 = EventBus()
    result2 = eng.evaluate_engagement(
        config=cfg, user_id="u-below", engagement_value=29.99, event_bus=bus2
    )
    assert result2["triggered"] is False


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 66)
    print("  B3 / BLOCO 27 FEEDBACK INCENTIVADO ENGINE — TEST SUITE")
    print("=" * 66)

    test("engagement < 30% → não dispara",               t1_engagement_below_threshold)
    test("usage_time < 300s → não dispara",              t2_usage_time_blindagem)
    test("texto < 50 → rejeita",                         t3_feedback_text_too_short)
    test("texto ≥ 50 → valida",                         t4_feedback_text_valid)
    test("validação concede lifetime",                    t5_lifetime_grant_after_feedback)
    test("refund revoga lifetime",                        t6_refund_revokes_lifetime)
    test("nenhuma escrita fora do Orchestrator",          t7_direct_write_blocked)
    test("engine não promove versão",                     t8_version_promotion_forbidden)
    test("persistência é append-only",                    t9_persistence_is_append_only)
    test("execução direta do engine lança erro",          t10_direct_execution_guard)

    print("\n" + "=" * 66)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  B3 / BLOCO 27 FEEDBACK INCENTIVADO ENGINE — VALID")
        print("  B3 LOCKED")
    else:
        print("  B3 — INVALID (see failures above)")
    print("=" * 66 + "\n")

    sys.exit(0 if passed == total else 1)
