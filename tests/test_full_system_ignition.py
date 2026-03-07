"""
tests/test_full_system_ignition.py — B7 Ignition Full System Validation

Tests 114–120 covering all structural layers:
  • Bloco 26 (Radar / StrategicOpportunityEngine)
  • B2 (Confluence Gate — embedded in evaluate_opportunity)
  • B3 (Feedback Incentivado)
  • B4 (User Enrichment)
  • B5 (Macro Exposure Governance — Bloco 29)
  • B6 (Radar ↔ Governance Integration)
  • A8 (Version Manager — rollback / promotion)

AUTHORITY:   None. Test layer only.
PERSISTENCE: Read-only validation + append-only memory stubs.
EXECUTION:   No engine gains execution authority.

Usage:
    py tests/test_full_system_ignition.py
"""
import sys
import os
import io
import copy
import uuid
from datetime import datetime, timezone, timedelta

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus                        import EventBus
from core.strategic_opportunity_engine     import (
    StrategicOpportunityEngine,
    AutoExpansionForbiddenError,
    RadarExecutionOutsideOrchestratorError,
    ICE_BLOQUEADO, ICE_MODERADO, ICE_ALTO,
)
from core.macro_exposure_governance_engine import (
    MacroExposureGovernanceEngine,
    MacroExposureDirectExecutionError,
)
from core.feedback_incentive_engine        import (
    FeedbackIncentiveEngine,
    FeedbackProductConfig,
    FeedbackDirectExecutionError,
    FEEDBACK_MIN_CHARS,
)
from core.user_enrichment_engine           import (
    UserEnrichmentEngine,
    UserEnrichmentDirectExecutionError,
)
from core.version_manager                  import (
    VersionManager,
    NoPreviousBaselineError,
    VersionPromotionPreconditionError,
    VersionPromotionOutsideOrchestratorError,
)
from core.state_manager                    import StateManager, DirectWriteError


# =============================================================================
#  IN-MEMORY STUBS (append-only, no file I/O)
# =============================================================================

class MemPersistence:
    """Generic append-only in-memory persistence stub."""
    def __init__(self):
        self._records = []
    def append_record(self, r):
        self._records.append(copy.deepcopy(r))
    def load_all(self):
        return copy.deepcopy(self._records)
    def load(self):
        return {}
    def save(self, _data):
        pass
    def __len__(self):
        return len(self._records)


class MemVersionPersistence:
    """VersionManager-compatible in-memory persistence."""
    def __init__(self):
        self._data = {}
    def load(self):
        return copy.deepcopy(self._data)
    def save(self, data):
        self._data = copy.deepcopy(data)


# =============================================================================
#  FACTORY HELPERS
# =============================================================================

def _make_radar():
    return StrategicOpportunityEngine(persistence=MemPersistence())

def _make_macro():
    return MacroExposureGovernanceEngine(persistence=MemPersistence())

def _make_feedback():
    return FeedbackIncentiveEngine(persistence=MemPersistence())

def _make_enrichment():
    return UserEnrichmentEngine(persistence=MemPersistence())

def _make_version():
    return VersionManager(persistence=MemVersionPersistence())

# --  default safe kwargs for evaluate_opportunity  ---------------------------

_GOOD_RADAR_KWARGS = dict(
    product_id              = "prod-ignition",
    emotional_score         = 82.0,
    monetization_score      = 82.0,
    products_in_cluster     = 1,
    total_active_products   = 5,
    score_global            = 82.0,
    roas_avg                = 2.2,
    global_state            = "NORMAL",
    active_betas            = 1,
    macro_block             = False,
    positive_trend          = True,
    # B6 governance — healthy defaults
    financial_alert_active  = False,
    credit_low_warning      = False,
    credit_critical_warning = False,
    dias_restantes          = 60.0,
    buffer_minimo           = 7.0,
)

# --  default safe kwargs for validate_macro_exposure  -----------------------

_GOOD_MACRO_KWARGS = dict(
    product_id                 = "prod-macro",
    channel_id                 = "ch-web",
    requested_allocation       = 500.0,
    current_product_allocation = 0.05,   # 5% of capital → stays within 20% limit
    current_channel_allocation = 0.10,
    current_global_allocation  = 0.20,
    total_capital              = 100_000.0,
    roas_avg                   = 2.5,
    score_global               = 88.0,
    refund_ratio_avg           = 0.05,
    global_state               = "NORMAL",
    financial_alert_active     = False,
)


# =============================================================================
#  TEST RUNNER
# =============================================================================

results = []

def test(tid, name, fn):
    label = f"[TEST {tid}]"
    try:
        fn()
        results.append(("OK", tid, name))
        print(f"  [OK]  {label} {name}")
    except AssertionError as e:
        results.append(("FAIL", tid, name))
        print(f"  [FAIL] {label} {name} — AssertionError: {e}")
    except Exception as e:
        results.append(("FAIL", tid, name))
        print(f"  [FAIL] {label} {name} — {type(e).__name__}: {e}")


# =============================================================================
#  TEST 114 — END-TO-END EXPANSION FLOW
#  All layers healthy → expansion_recommendation_approved emitted.
#  No auto-creation, no capital allocation, no beta started.
# =============================================================================

def t114_end_to_end_expansion_flow():
    """
    Valid opportunity through all governance layers.
    Expect: expansion_recommendation_approved emitted.
    Expect: NO product_created, beta_start_requested, capital_allocated events.
    Expect: event log grows monotonically (append-only).
    """
    eng   = _make_radar()
    macro = _make_macro()
    bus   = EventBus()

    # The strategic engine's B6 layer calls macro.validate_macro_exposure internally
    # when macro_exposure_engine is injected.
    result = eng.evaluate_opportunity(
        event_bus               = bus,
        **_GOOD_RADAR_KWARGS,
        macro_exposure_engine       = macro,
        current_product_allocation  = 0.05,
        current_channel_allocation  = 0.10,
        current_global_allocation   = 0.20,
        total_capital               = 100_000.0,
        simulated_allocation        = 500.0,    # passes to macro as requested_allocation
        channel_id                  = "ch-web",
    )

    assert result["eligible"] is True,    f"Expected eligible=True, got {result}"
    assert result["ice"] == ICE_ALTO,     f"Expected ICE_ALTO, got {result['ice']}"

    types = [e["event_type"] for e in bus.get_events()]
    assert "expansion_recommendation_approved" in types, (
        f"expansion_recommendation_approved missing. Events: {types}"
    )

    # Forbidden autonomous actions must NOT appear
    forbidden = {"product_created", "beta_start_requested", "capital_allocated"}
    for fev in forbidden:
        assert fev not in types, (
            f"Forbidden autonomous event '{fev}' was emitted. Events: {types}"
        )

    # Signal-only note in the approval payload
    approved_event = next(
        e for e in bus.get_events()
        if e["event_type"] == "expansion_recommendation_approved"
    )
    note = approved_event["payload"].get("note", "")
    assert "SIGNAL ONLY" in note, f"Approval event must carry SIGNAL ONLY note. Got: {note}"

    # Append-only: a second evaluation grows the event log
    count_before = len(bus.get_events())
    eng.evaluate_opportunity(event_bus=bus, **_GOOD_RADAR_KWARGS)
    count_after = len(bus.get_events())
    assert count_after > count_before, "Event log must grow monotonically (append-only)."


# =============================================================================
#  TEST 115 — PRECEDENCE VALIDATION
#  Each blocking layer fires independently; higher-precedence rule fires first.
# =============================================================================

def t115_precedence_validation():
    """
    Scenario A: CONTENÇÃO  → radar_blocked_global_state only.
    Scenario B: financial  → radar_blocked_financial_risk only.
    Scenario C: macro over limit → radar_blocked_macro_exposure only.
    Scenario D: active_betas > 2 → radar_blocked_beta_limit only.
    """
    # ---- Scenario A: CONTENÇÃO (highest precedence) ----
    bus_a = EventBus()
    res_a = _make_radar().evaluate_opportunity(
        event_bus=bus_a,
        **{**_GOOD_RADAR_KWARGS, "global_state": "CONTENÇÃO_FINANCEIRA"},
    )
    types_a = [e["event_type"] for e in bus_a.get_events()]
    assert res_a["eligible"] is False
    assert "radar_blocked_global_state" in types_a, f"Scenario A events: {types_a}"
    # Downstream financial block must NOT fire after CONTENÇÃO block
    assert "radar_blocked_financial_risk" not in types_a, (
        "Scenario A: financial block must not fire after CONTENÇÃO"
    )

    # ---- Scenario B: financial alert (second precedence) ----
    bus_b = EventBus()
    res_b = _make_radar().evaluate_opportunity(
        event_bus=bus_b,
        **{**_GOOD_RADAR_KWARGS, "financial_alert_active": True},
    )
    types_b = [e["event_type"] for e in bus_b.get_events()]
    assert res_b["eligible"] is False
    assert "radar_blocked_financial_risk" in types_b, f"Scenario B events: {types_b}"
    # Macro block must not fire after financial block
    assert "radar_blocked_macro_exposure" not in types_b, (
        "Scenario B: macro block must not fire after financial block"
    )

    # ---- Scenario C: macro exposure over product limit (third precedence) ----
    macro_c = _make_macro()
    bus_c   = EventBus()
    # product = 22% > base limit 20%, all other conditions are normal
    res_c = _make_radar().evaluate_opportunity(
        event_bus                   = bus_c,
        **_GOOD_RADAR_KWARGS,
        macro_exposure_engine       = macro_c,
        current_product_allocation  = 0.22 * 100_000.0,  # absolute value
        current_channel_allocation  = 0.10 * 100_000.0,
        current_global_allocation   = 0.20 * 100_000.0,
        total_capital               = 100_000.0,
        simulated_allocation        = 1.0,   # tiny extra triggers violation
        channel_id                  = "ch-web",
    )
    types_c = [e["event_type"] for e in bus_c.get_events()]
    assert res_c["eligible"] is False, (
        f"Macro over limit must block. result={res_c}"
    )
    assert "radar_blocked_macro_exposure" in types_c, f"Scenario C events: {types_c}"
    assert "radar_blocked_beta_limit" not in types_c, (
        "Scenario C: beta limit block must not fire after macro block"
    )

    # ---- Scenario D: active_betas > 2 (fourth precedence) ----
    bus_d = EventBus()
    res_d = _make_radar().evaluate_opportunity(
        event_bus=bus_d,
        **{**_GOOD_RADAR_KWARGS, "active_betas": 3},
    )
    types_d = [e["event_type"] for e in bus_d.get_events()]
    assert res_d["eligible"] is False
    assert "radar_blocked_beta_limit" in types_d, f"Scenario D events: {types_d}"
    assert "expansion_recommendation_approved" not in types_d, (
        "Scenario D: approval must not appear when betas > 2"
    )


# =============================================================================
#  TEST 116 — ROLLBACK INTEGRITY
#  promote v1.0 → promote v2.0 → rollback → baseline restored to v1.0.
# =============================================================================

def t116_rollback_integrity():
    """
    1. Create + promote first candidate (v1.0) → sets baseline.
    2. Create + promote second candidate (v2.0) → advances baseline.
    3. Rollback → baseline restored to v1.0, snapshot restored to snap-001.
    4. version_history is preserved (append-only), event emitted.
    """
    vm  = _make_version()
    bus = EventBus()
    pid = "prod-rollback"

    # Step 1: first candidate + promote → baseline=v1.0
    vm.create_candidate(pid, version_id="v1.0", snapshot_id="snap-001", event_bus=bus)
    vm.promote_candidate(pid, snapshot_id="snap-001", event_bus=bus, orchestrated=True)

    assert vm.get_baseline(pid) == "v1.0", (
        f"Expected baseline v1.0, got {vm.get_baseline(pid)}"
    )

    # Step 2: second candidate + promote → baseline=v2.0
    vm.create_candidate(pid, version_id="v2.0", snapshot_id="snap-002", event_bus=bus)
    vm.promote_candidate(pid, snapshot_id="snap-002", event_bus=bus, orchestrated=True)

    assert vm.get_baseline(pid) == "v2.0", (
        f"Expected baseline v2.0, got {vm.get_baseline(pid)}"
    )

    events_before = len(bus.get_events())
    assert events_before >= 4, f"Expected ≥4 events before rollback, got {events_before}"

    # Step 3: rollback
    vm.rollback_to_previous_baseline(pid, event_bus=bus, orchestrated=True)

    # Step 4: assertions
    assert vm.get_baseline(pid) == "v1.0", (
        f"Rollback should restore v1.0, got {vm.get_baseline(pid)}"
    )
    state = vm.get_record(pid)
    assert state["baseline_metrics_snapshot_id"] == "snap-001", (
        f"Snapshot not restored: {state['baseline_metrics_snapshot_id']}"
    )
    assert state["candidate_version"] is None, (
        "Candidate should be cleared after rollback"
    )
    assert len(state["version_history"]) >= 4, (
        f"Version history corrupted: {len(state['version_history'])} entries"
    )

    # Append-only: event log grew
    events_after = len(bus.get_events())
    assert events_after > events_before, "Event log must grow after rollback."

    types = [e["event_type"] for e in bus.get_events()]
    assert "version_rollback_executed" in types, (
        f"version_rollback_executed event missing. Got: {types}"
    )


# =============================================================================
#  TEST 117 — GLOBAL STATE CONSISTENCY
#  credit_critical_warning → blocks. Remove → approves. StateManager guard intact.
# =============================================================================

def t117_global_state_consistency():
    """
    1. credit_critical_warning=True → B6 financial block fires.
    2. credit_critical_warning=False, all clear → B6 approves.
    3. StateManager.set() raises DirectWriteError (illegal transition guard).
    """
    # Defensive: credit critical warning active
    bus_crit = EventBus()
    res_crit = _make_radar().evaluate_opportunity(
        event_bus=bus_crit,
        **{**_GOOD_RADAR_KWARGS, "credit_critical_warning": True},
    )
    assert res_crit["eligible"] is False, (
        "credit_critical_warning=True must block expansion"
    )
    types_crit = [e["event_type"] for e in bus_crit.get_events()]
    assert "radar_blocked_financial_risk" in types_crit, (
        f"Financial risk event missing for critical credit: {types_crit}"
    )

    # Recovery: remove warning → normal
    bus_ok = EventBus()
    res_ok = _make_radar().evaluate_opportunity(
        event_bus=bus_ok,
        **_GOOD_RADAR_KWARGS,
    )
    assert res_ok["eligible"] is True, (
        "All-clear conditions must allow expansion"
    )
    types_ok = [e["event_type"] for e in bus_ok.get_events()]
    assert "expansion_recommendation_approved" in types_ok, (
        f"Approval missing after removing warnings: {types_ok}"
    )
    assert "radar_blocked_financial_risk" not in types_ok, (
        "Financial risk block must NOT appear when all clear"
    )

    # StateManager write-lock: illegal state transition guard
    sm     = StateManager()
    raised = False
    try:
        sm.set("global_state", "CONTENÇÃO_FINANCEIRA")
    except DirectWriteError:
        raised = True
    assert raised, "StateManager.set() must raise DirectWriteError outside Orchestrator"


# =============================================================================
#  TEST 118 — MACRO BLOCK ENFORCEMENT
#  Adaptive vs base limits, both enforced correctly.
# =============================================================================

def t118_macro_block_enforcement():
    """
    Scenario A: adaptive mode (all criteria), allocation = 32% product → BLOCK
                (adaptive product limit = 30%).
    Scenario B: base mode, allocation = 22% product → BLOCK
                (base product limit = 20%).
    Scenario C: adaptive mode, allocation = 28% product → ALLOW
                (adaptive product limit = 30%).
    Direct execution guard: modify_allocation() always raises.
    """
    total_capital = 100_000.0

    # Scenario A: adaptive + exceed 30% product limit
    macro_a = _make_macro()
    bus_a   = EventBus()
    res_a = macro_a.validate_macro_exposure(
        product_id                 = "prod-A",
        channel_id                 = "ch-A",
        requested_allocation       = 0.0,   # only current matters here
        current_product_allocation = 32_000.0,   # 32% of 100k
        current_channel_allocation = 10_000.0,
        current_global_allocation  = 20_000.0,
        total_capital              = total_capital,
        roas_avg                   = 2.5,    # adaptive eligible
        score_global               = 88.0,
        refund_ratio_avg           = 0.05,
        global_state               = "NORMAL",
        financial_alert_active     = False,
        event_bus                  = bus_a,
    )
    assert res_a["allowed"] is False, (
        f"32% > adaptive 30% must block. Got: {res_a}"
    )
    assert any("product_exposure" in v for v in res_a.get("violations", [])), (
        f"Expected product_exposure violation. Got: {res_a.get('violations')}"
    )

    # Scenario B: base mode + exceed 20% limit
    macro_b = _make_macro()
    bus_b   = EventBus()
    res_b = macro_b.validate_macro_exposure(
        product_id                 = "prod-B",
        channel_id                 = "ch-B",
        requested_allocation       = 0.0,
        current_product_allocation = 22_000.0,   # 22% > base 20%
        current_channel_allocation = 10_000.0,
        current_global_allocation  = 20_000.0,
        total_capital              = total_capital,
        roas_avg                   = 1.0,    # NOT adaptive eligible
        score_global               = 75.0,
        refund_ratio_avg           = 0.20,
        global_state               = "NORMAL",
        financial_alert_active     = False,
        event_bus                  = bus_b,
    )
    assert res_b["allowed"] is False, (
        f"22% > base 20% must block. Got: {res_b}"
    )

    # Scenario C: adaptive mode + within 30% limit → ALLOW
    macro_c = _make_macro()
    bus_c   = EventBus()
    res_c = macro_c.validate_macro_exposure(
        product_id                 = "prod-C",
        channel_id                 = "ch-C",
        requested_allocation       = 0.0,
        current_product_allocation = 28_000.0,   # 28% < adaptive 30%
        current_channel_allocation = 10_000.0,
        current_global_allocation  = 20_000.0,
        total_capital              = total_capital,
        roas_avg                   = 2.5,
        score_global               = 88.0,
        refund_ratio_avg           = 0.05,
        global_state               = "NORMAL",
        financial_alert_active     = False,
        event_bus                  = bus_c,
    )
    assert res_c["allowed"] is True, (
        f"28% < adaptive 30% must allow. Got: {res_c}"
    )

    # Execution guard: modify_allocation always raises
    raised = False
    try:
        macro_c.modify_allocation("exploit")
    except MacroExposureDirectExecutionError:
        raised = True
    assert raised, "modify_allocation() must always raise MacroExposureDirectExecutionError"

    # Event buses must all have grown (append-only)
    assert len(bus_a.get_events()) >= 1
    assert len(bus_b.get_events()) >= 1
    assert len(bus_c.get_events()) >= 1


# =============================================================================
#  TEST 119 — FEEDBACK INTEGRATION
#  Engage → validate → grant → refund → revoke.
# =============================================================================

def t119_feedback_integration():
    """
    1. engagement >= 30% → feedback_requested.
    2. Short feedback (<50 chars) → rejected.
    3. Long feedback (>=50 chars) → validated.
    4. Grant lifetime upgrade → lifetime_upgrade_granted.
    5. Refund → revoke → lifetime_upgrade_revoked + access_revoked.
    6. Append-only: both grant and revoke records persist.
    """
    eng = _make_feedback()
    bus = EventBus()
    pid = "prod-fb"
    uid = "user-001"

    cfg = FeedbackProductConfig(
        product_id              = pid,
        engagement_metric_type  = "module_progress",
        engagement_metric_total = 100.0,
        engagement_threshold    = 0.30,
    )

    # 1. Engagement 35% >= 30% → trigger
    res_eng = eng.evaluate_engagement(
        config           = cfg,
        user_id          = uid,
        engagement_value = 35.0,
        event_bus        = bus,
    )
    assert res_eng["triggered"] is True, (
        f"35% must trigger feedback request. Got: {res_eng}"
    )
    types = [e["event_type"] for e in bus.get_events()]
    assert "feedback_requested" in types

    # 2. Short feedback → rejected
    short = "Too short"
    assert len(short.strip()) < FEEDBACK_MIN_CHARS
    res_short = eng.submit_feedback(
        user_id=uid, product_id=pid, feedback_text=short, event_bus=bus,
    )
    assert res_short["valid"] is False, "Short feedback must be rejected"
    types2 = [e["event_type"] for e in bus.get_events()]
    assert "feedback_rejected_invalid" in types2

    # 3. Long feedback → validated
    long_text = "A" * 60   # safe beyond 50 chars
    res_long = eng.submit_feedback(
        user_id=uid, product_id=pid, feedback_text=long_text, event_bus=bus,
    )
    assert res_long["valid"] is True, "Long feedback must be validated"
    types3 = [e["event_type"] for e in bus.get_events()]
    assert "feedback_validated" in types3

    # 4. Grant lifetime upgrade
    eng.grant_lifetime_upgrade(user_id=uid, product_id=pid, event_bus=bus)
    assert eng.has_lifetime_grant(uid, pid)
    types4 = [e["event_type"] for e in bus.get_events()]
    assert "lifetime_upgrade_granted" in types4

    # 5. Refund → revoke
    revoked = eng.revoke_lifetime_upgrade(
        user_id=uid, product_id=pid, event_bus=bus, reason="refund_completed",
    )
    assert revoked is True
    assert not eng.has_lifetime_grant(uid, pid), "Grant should be cleared after revoke"
    types5 = [e["event_type"] for e in bus.get_events()]
    assert "lifetime_upgrade_revoked" in types5
    assert "access_revoked"           in types5

    # 6. Append-only: grant record still exists even after revoke
    all_records = eng.get_all_records(user_id=uid, product_id=pid)
    event_types = {r["event_type"] for r in all_records}
    assert "lifetime_upgrade_granted" in event_types, (
        "Grant record must persist (append-only)"
    )
    assert "lifetime_upgrade_revoked" in event_types

    # Execution guard
    raised = False
    try:
        FeedbackIncentiveEngine.execute_directly()
    except FeedbackDirectExecutionError:
        raised = True
    assert raised, "execute_directly() must raise FeedbackDirectExecutionError"


# =============================================================================
#  TEST 120 — USER ENRICHMENT CONSISTENCY
#  Multi-purchase, refund, channel/device distribution → all metrics correct.
# =============================================================================

def t120_user_enrichment_consistency():
    """
    Profile:
      payments  = [200, 150, 100]  → LTV = 400 (450 - 50)
      refunds   = [50]
      refund_ratio = 1/3 ≈ 0.333
      channels: email×2, web×1 → dominant = email
      devices:  mobile×2, desktop×1 → dominant = mobile
      risk_score: 3 purchases → -20; refund_ratio 0.333 > 0.3 → +20 → net ~0
      tags: repeat_buyer (3 purchases)
      NOT high_value_user (refund_ratio 0.333 > 0.2)
      export_signal_ready: repeat_buyer BUT refund_ratio > 0.3 → False

    second profile: 3 purchases, 0 refunds, LTV=1000 → export_signal_ready=True
    """
    eng = _make_enrichment()
    bus = EventBus()
    uid = "user-01"
    now_iso = datetime.now(timezone.utc).isoformat()

    snap = eng.update_user_profile(
        user_id          = uid,
        payment_amounts  = [200.0, 150.0, 100.0],
        refund_amounts   = [50.0],
        total_refunds    = 1,
        channel_counts   = {"email": 2, "web": 1},
        device_counts    = {"mobile": 2, "desktop": 1},
        last_purchase_ts = now_iso,
        avg_ltv_product  = 0.0,
        event_bus        = bus,
    )
    m = snap["metrics_snapshot"]

    expected_ltv = round(450.0 - 50.0, 4)
    assert abs(m["lifetime_value"] - expected_ltv) < 0.001, (
        f"LTV: {m['lifetime_value']} vs {expected_ltv}"
    )

    expected_ratio = round(1 / 3, 6)
    assert abs(m["refund_ratio"] - expected_ratio) < 0.0001, (
        f"refund_ratio: {m['refund_ratio']} vs {expected_ratio}"
    )

    assert m["dominant_channel"] == "email", (
        f"dominant_channel: {m['dominant_channel']}"
    )
    assert m["device_profile"] == "mobile", (
        f"device_profile: {m['device_profile']}"
    )
    assert 0 <= m["risk_score"] <= 100, (
        f"risk_score out of range: {m['risk_score']}"
    )

    tags = snap["classification_tag"]
    assert "repeat_buyer" in tags, f"repeat_buyer missing: {tags}"
    assert "high_value_user" not in tags, (
        f"high_value_user must NOT appear with high refund_ratio: {tags}"
    )
    assert snap["export_signal_ready"] is False, (
        "export_signal_ready must be False (refund_ratio > 0.3)"
    )

    # Zero-refund, high-LTV user IS export-ready
    snap2 = eng.update_user_profile(
        user_id          = "user-02",
        payment_amounts  = [500.0, 300.0, 200.0],
        refund_amounts   = [],
        total_refunds    = 0,
        channel_counts   = {"organic": 3},
        device_counts    = {"desktop": 3},
        last_purchase_ts = now_iso,
        avg_ltv_product  = 0.0,
        event_bus        = bus,
    )
    assert snap2["export_signal_ready"] is True, (
        "Zero-refund, high-LTV user should have export_signal_ready=True"
    )

    # Append-only: two profiles stored
    all_snaps = eng.get_all_snapshots()
    assert len(all_snaps) == 2, f"Expected 2 snapshots, found {len(all_snaps)}"

    # Execution guard
    raised = False
    try:
        UserEnrichmentEngine.execute_directly()
    except UserEnrichmentDirectExecutionError:
        raised = True
    assert raised, "execute_directly() must raise UserEnrichmentDirectExecutionError"


# =============================================================================
#  GLOBAL ASSERTIONS — post-suite structural guarantees
# =============================================================================

def _global_assertions():
    """
    ✔ No engine gained execution authority
    ✔ No write outside Orchestrator
    ✔ No bypass of macro governance
    ✔ StateManager write-lock intact
    ✔ VersionManager rollback guard on non-existent product
    """
    # 1. All engine execute guards raise
    def _check(fn, exc_type, label):
        raised = False
        try:
            fn()
        except exc_type:
            raised = True
        assert raised, f"{label} execute guard is missing"

    _check(
        StrategicOpportunityEngine.execute_directly,
        RadarExecutionOutsideOrchestratorError,
        "StrategicOpportunityEngine",
    )
    _check(
        FeedbackIncentiveEngine.execute_directly,
        FeedbackDirectExecutionError,
        "FeedbackIncentiveEngine",
    )
    _check(
        UserEnrichmentEngine.execute_directly,
        UserEnrichmentDirectExecutionError,
        "UserEnrichmentEngine",
    )
    _check(
        MacroExposureGovernanceEngine.execute_directly,
        MacroExposureDirectExecutionError,
        "MacroExposureGovernanceEngine",
    )

    # 2. Radar auto-expansion guards
    radar = _make_radar()
    _check(radar.create_product_automatically, AutoExpansionForbiddenError, "create_product_automatically")
    _check(radar.launch_beta_automatically,    AutoExpansionForbiddenError, "launch_beta_automatically")

    # 3. StateManager write-lock
    sm = StateManager()
    raised = False
    try:
        sm.set("bypass", "ILLEGAL")
    except DirectWriteError:
        raised = True
    assert raised, "StateManager must block all direct writes"

    # 4. VersionManager rollback without previous baseline
    #    orchestrated=True is required to reach NoPreviousBaselineError
    #    (orchestrator guard fires first otherwise)
    vm_new = _make_version()
    raised = False
    try:
        vm_new.rollback_to_previous_baseline("no-such-product", orchestrated=True)
    except NoPreviousBaselineError:
        raised = True
    assert raised, "VersionManager must raise NoPreviousBaselineError on missing history"

    print("\n  [GLOBAL] All architecture guards confirmed intact.")


# =============================================================================
#  RUNNER
# =============================================================================

if __name__ == "__main__":
    print("\n" + "=" * 68)
    print("  B7 — IGNITION FULL SYSTEM VALIDATION — TEST SUITE")
    print("=" * 68)

    test(114, "End-to-end expansion flow (all layers healthy)",         t114_end_to_end_expansion_flow)
    test(115, "Precedence validation (4 blocking scenarios A–D)",       t115_precedence_validation)
    test(116, "Rollback integrity (promote v1→v2 → rollback → v1)",    t116_rollback_integrity)
    test(117, "Global state consistency (credit warning + guard)",      t117_global_state_consistency)
    test(118, "Macro block enforcement (adaptive vs base limits)",      t118_macro_block_enforcement)
    test(119, "Feedback integration (engage→validate→grant→revoke)",    t119_feedback_integration)
    test(120, "User enrichment consistency (multi-purchase/refund)",    t120_user_enrichment_consistency)

    try:
        _global_assertions()
        results.append(("OK", "G", "Global architecture guards"))
        print("  [OK]  [GLOBAL] Architecture guards")
    except AssertionError as e:
        results.append(("FAIL", "G", "Global architecture guards"))
        print(f"  [FAIL] [GLOBAL] Architecture guards — {e}")

    passed = sum(1 for r in results if r[0] == "OK")
    total  = len(results)

    print("\n" + "=" * 68)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  B7 — IGNITION FULL SYSTEM VALIDATION — VALID")
        print("  B7 LOCKED")
    else:
        print("  B7 — INVALID (see failures above)")
    print("=" * 68 + "\n")

    sys.exit(0 if passed == total else 1)
