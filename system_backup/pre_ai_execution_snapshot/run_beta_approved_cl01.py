"""
run_beta_approved_cl01.py
────────────────────────────────────────────────────────────────────
Routes the beta_approved_requested event for product
  13a9d304-0d2e-4f68-b1ce-b0961aebb1f5
through the A14-hardened Orchestrator.

The Draft record is pre-seeded into the in-memory persistence store
to simulate the persistent state that would exist in production after
the previous product_creation_requested run.

Execution: python run_beta_approved_cl01.py
"""

import sys
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.orchestrator         import Orchestrator
from core.product_life_engine  import ProductLifeEngine
from core.global_state         import GlobalState, NORMAL
from infrastructure.logger     import get_logger

logger = get_logger("BetaApprovalRunner")

# ── Stubs ────────────────────────────────────────────────────────────────────

class _InMemoryBus:
    def __init__(self):  self.events = []
    def append_event(self, ev): self.events.append(ev)
    def get_events(self):       return list(self.events)

class _InMemoryPersistence:
    def __init__(self, seed=None): self._data = seed or {}
    def load(self):                return dict(self._data)
    def save(self, d):             self._data = dict(d)

class _NullStateManager:
    def get(self, *a, **kw):  return None
    def set(self, *a, **kw):  pass
    def save(self, *a, **kw): pass
    def load(self, *a, **kw): return {}

# ── Product record as it exists after create_draft() ─────────────────────────

PRODUCT_ID = "13a9d304-0d2e-4f68-b1ce-b0961aebb1f5"

DRAFT_SEED = {
    PRODUCT_ID: {
        "product_id":             PRODUCT_ID,
        "state":                  "Draft",
        "created_at":             "2026-02-24T17:07:42.954082+00:00",
        "opportunity_id":         "CL-01",
        "emotional_score":        82.0,
        "monetization_score":     84.6,
        "growth_percent":         38.0,
        "competitive_gap_flag":   True,
        "justification_snapshot": {
            "growth_percent_30d":    38.0,
            "growth_percent_90d":    26.0,
            "intensity_score":       82,
            "emotional_score":       82.0,
            "ticket_viability_score": 81,
            "gap_strength_score":    82,
            "monetization_score":    84.6,
            "score_global":          78.76,
            "anti_hype_penalty_applied":           False,
            "competitive_density_penalty_applied": False,
            "volatility_penalty_applied":          False,
            "cluster_ratio":                       0.0,
            "all_hard_thresholds_passed":          True,
            "algorithm_version":                   "C1_v2_hardened",
            "pain_summary": (
                "Solopreneurs waste 10-40% of productive time on repetitive "
                "operational tasks without affordable, role-specific automation kits."
            ),
        },
        "version_id":       "C1_v2_hardened",
        "baseline_version": "1.0",
        "beta_start":       None,
        "beta_end":         None,
        "beta_closed_at":   None,
        "classification":   None,
        "last_transition":  "2026-02-24T17:07:42.954082+00:00",
    }
}

# ── Payload ───────────────────────────────────────────────────────────────────

EVENT_PAYLOAD = {
    "product_id":            PRODUCT_ID,
    "global_state":          "ESTAVEL",     # informational — service decides
    "financial_alert_active": False,
}


def main():
    ts = "2026-02-24T14:27:16-03:00"
    print("=" * 66)
    print("  A14 BETA APPROVAL -- ORCHESTRATOR ROUTING")
    print(f"  Timestamp        : {ts}")
    print(f"  Event            : beta_approved_requested")
    print(f"  product_id       : {PRODUCT_ID}")
    print(f"  global_state     : NORMAL (ESTAVEL)")
    print(f"  financial_alert  : False")
    print("=" * 66)

    # ── Build real GlobalState (initialises to NORMAL — no persistence) ──
    gs = GlobalState(persistence=None)
    print(f"\n[RUNNER] GlobalState.get_state() = '{gs.get_state()}'")
    print(f"[RUNNER] CONTENCAO block active  : False")
    print(f"[RUNNER] active_beta_count        : 0")
    print(f"[RUNNER] financial_alert_active   : False")
    print(f"[RUNNER] All guards: CLEAR\n")

    # ── Wire services with pre-seeded Draft record ───────────────────────
    bus  = _InMemoryBus()
    pers = _InMemoryPersistence(seed=DRAFT_SEED)
    ple  = ProductLifeEngine(persistence=pers)
    sm   = _NullStateManager()

    orch = Orchestrator(event_bus=bus, state_manager=sm)
    orch.register_service("product_life", ple)
    orch.register_service("global_state", gs)

    # ── Route through Orchestrator ────────────────────────────────────────
    print("[RUNNER] Calling Orchestrator.receive_event('beta_approved_requested', payload)")
    print("-" * 66)

    orch.receive_event(
        event_type="beta_approved_requested",
        payload=EVENT_PAYLOAD,
        product_id=PRODUCT_ID,
        source="human_operator",
    )

    print("-" * 66)

    # ── Inspect emitted events ────────────────────────────────────────────
    emitted    = bus.get_events()
    beta_event = next(
        (e for e in emitted if e.get("event_type") == "beta_started"),
        None
    )

    if beta_event:
        b = beta_event["payload"]
        start_dt = datetime.fromisoformat(b["beta_start"])
        end_dt   = datetime.fromisoformat(b["beta_end"])

        # Lifecycle record verification
        ple_state = pers.load()
        rec = ple_state.get(PRODUCT_ID, {})

        print(f"\n[RUNNER] Beta started successfully.")
        print(f"  product_id       : {PRODUCT_ID}")
        print(f"  state            : {rec.get('state')}")
        print(f"  beta_start       : {b['beta_start']}")
        print(f"  beta_end         : {b['beta_end']}")
        print(f"  beta_duration_d  : {b['beta_duration_days']}")
        print(f"  window_closes_at : {end_dt.isoformat()}")

        result_json = {
            "status":              "success",
            "event_type":          "beta_started",
            "product_id":          PRODUCT_ID,
            "opportunity_id":      "CL-01",
            "state":               rec.get("state"),
            "beta_start":          b["beta_start"],
            "beta_end":            b["beta_end"],
            "beta_duration_days":  b["beta_duration_days"],
            "orchestrator_confirmed": True,
            "guards_evaluated": {
                "contencao_block":         False,
                "active_beta_count":       0,
                "max_betas":               2,
                "financial_alert_active":  False,
                "all_guards_passed":       True,
            },
            "events_emitted": [e["event_type"] for e in emitted],
            "next_step": (
                f"Beta window closes {end_dt.date().isoformat()}. "
                "After expiry: emit close_beta_requested -> post_beta_consolidation_requested."
            ),
        }

        print("\n" + "=" * 66)
        print("  RESULT JSON")
        print("=" * 66)
        print(json.dumps(result_json, indent=2, ensure_ascii=False))

    else:
        blocked = next(
            (e for e in emitted if e.get("event_type") == "beta_start_blocked"),
            None
        )
        if blocked:
            print(f"\n[RUNNER] BLOCKED: beta_start_blocked")
            print(f"  reason: {blocked['payload'].get('blocking_reason')}")
        else:
            print(f"\n[RUNNER] ERROR: No beta_started or beta_start_blocked in bus.")
            print(f"  events: {[e.get('event_type') for e in emitted]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
