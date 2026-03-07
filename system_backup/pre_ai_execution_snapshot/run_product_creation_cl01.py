"""
run_product_creation_cl01.py
────────────────────────────────────────────────────────────────────
Routes the product_creation_requested event (CL-01 / C1_v2_hardened)
through the A14-hardened Orchestrator.

Payload normalization:
  - justification_metrics  → justification_snapshot  (handler expects snake_case _snapshot)
  - algorithm_version      → version_id              (handler field name)
  - pain_summary injected into justification_snapshot for full auditability

Execution: python run_product_creation_cl01.py
"""

import sys
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── path bootstrap ───────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.orchestrator         import Orchestrator
from core.product_life_engine  import ProductLifeEngine
from infrastructure.logger     import get_logger

logger = get_logger("ProductCreationRunner")

# ──────────────────────────────────────────────────────────────────────────────
# Minimal stubs (no real persistence or bus needed for this runner)
# ──────────────────────────────────────────────────────────────────────────────

class _InMemoryPersistence:
    def __init__(self):  self._data = {}
    def load(self):       return dict(self._data)
    def save(self, d):    self._data = dict(d)

class _InMemoryBus:
    def __init__(self):  self.events = []
    def append_event(self, ev): self.events.append(ev)
    def get_events(self):        return list(self.events)

# ──────────────────────────────────────────────────────────────────────────────
# Raw payload from C1_v2_hardened pipeline
# ──────────────────────────────────────────────────────────────────────────────

RAW_PAYLOAD = {
    "opportunity_id":    "CL-01",
    "pain_summary": (
        "Solopreneurs waste 10-40% of productive time on repetitive operational tasks "
        "without affordable, role-specific automation kits."
    ),
    "justification_metrics": {
        "growth_percent_30d":     38.0,
        "growth_percent_90d":     26.0,
        "intensity_score":        82,
        "emotional_score":        82.0,
        "ticket_viability_score": 81,
        "gap_strength_score":     82,
        "monetization_score":     84.6,
        "score_global":           78.76,
        "anti_hype_penalty_applied":            False,
        "competitive_density_penalty_applied":  False,
        "volatility_penalty_applied":           False,
        "cluster_ratio":                        0.0,
        "all_hard_thresholds_passed":           True,
        "algorithm_version":                    "C1_v2_hardened",
    },
    "score_global":          78.76,
    "growth_percent":        38.0,
    "competitive_gap_flag":  True,
    "algorithm_version":     "C1_v2_hardened",
}

# ──────────────────────────────────────────────────────────────────────────────
# Normalize to Orchestrator handler schema
# ──────────────────────────────────────────────────────────────────────────────

def normalize_payload(raw: dict) -> dict:
    """
    Map C1-pipeline field names → Orchestrator handler field names.
    
    Handler requires:
        opportunity_id, emotional_score, monetization_score,
        growth_percent, competitive_gap_flag,
        justification_snapshot (dict), version_id (str)
    """
    jm = raw.get("justification_metrics", {})

    return {
        "opportunity_id":   raw["opportunity_id"],
        # Scores extracted from justification_metrics
        "emotional_score":      float(jm.get("emotional_score",    raw.get("emotional_score",    0))),
        "monetization_score":   float(jm.get("monetization_score", raw.get("monetization_score", 0))),
        "growth_percent":       float(raw.get("growth_percent", 0)),
        "competitive_gap_flag": bool(raw.get("competitive_gap_flag", False)),
        # justification_metrics → justification_snapshot (full dict for audit)
        "justification_snapshot": {
            **jm,
            "pain_summary":     raw.get("pain_summary", ""),
            "score_global":     raw.get("score_global", 0),
        },
        # algorithm_version → version_id
        "version_id": raw.get("algorithm_version", jm.get("algorithm_version", "unknown")),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

class _NullStateManager:
    """Minimal stub — product_creation_requested does not write to state_manager."""
    def get(self, *a, **kw):   return None
    def set(self, *a, **kw):   pass
    def save(self, *a, **kw):  pass
    def load(self, *a, **kw):  return {}

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    ts = "2026-02-24T14:00:11-03:00"
    print("=" * 66)
    print("  A14 CONSTITUTIONAL PRODUCT CREATION -- ORCHESTRATOR ROUTING")
    print(f"  Timestamp : {ts}")
    print(f"  Event     : product_creation_requested")
    print(f"  Source    : C1_v2_hardened / opportunity_id=CL-01")
    print("=" * 66)

    # -- Wire up services ---------------------------------------------------
    bus  = _InMemoryBus()
    pers = _InMemoryPersistence()
    ple  = ProductLifeEngine(persistence=pers)
    sm   = _NullStateManager()

    orch = Orchestrator(event_bus=bus, state_manager=sm)
    orch.register_service("product_life", ple)

    # ── Normalize payload ────────────────────────────────────────────────
    payload = normalize_payload(RAW_PAYLOAD)

    print("\n[RUNNER] Normalized payload:")
    for k, v in payload.items():
        if k == "justification_snapshot":
            print(f"  justification_snapshot: {{ ... {len(v)} fields }}")
        else:
            print(f"  {k}: {v}")

    # ── Route through Orchestrator ────────────────────────────────────────
    print("\n[RUNNER] Calling Orchestrator.receive_event('product_creation_requested', payload)")
    print("-" * 66)

    orch.receive_event(
        event_type="product_creation_requested",
        payload=payload,
        source="C1_v2_hardened",
    )

    # ── Inspect emitted events ────────────────────────────────────────────
    emitted = bus.get_events()
    draft_event = next(
        (e for e in emitted if e.get("event_type") == "product_draft_created"),
        None
    )

    print("-" * 66)
    if draft_event:
        pid = draft_event["payload"]["product_id"]
        print(f"\n[RUNNER] Draft product created successfully.")
        print(f"  product_id       : {pid}")
        print(f"  state            : {draft_event['payload']['state']}")
        print(f"  opportunity_id   : {draft_event['payload']['opportunity_id']}")
        print(f"  baseline_version : {draft_event['payload']['baseline_version']}")
        print(f"  emotional_score  : {draft_event['payload']['emotional_score']}")
        print(f"  monetization_score: {draft_event['payload']['monetization_score']}")
        print(f"  growth_percent   : {draft_event['payload']['growth_percent']}")
        print(f"  created_at       : {draft_event['payload']['created_at']}")

        # Check lifecycle record
        ple_state = pers.load()
        rec = ple_state.get(pid, {})

        print(f"\n[RUNNER] Lifecycle record persisted:")
        print(f"  record_keys: {list(rec.keys())}")

        result_json = {
            "status":          "success",
            "event_type":      "product_draft_created",
            "product_id":      pid,
            "opportunity_id":  "CL-01",
            "state":           "Draft",
            "baseline_version": "1.0",
            "score_global":    78.76,
            "created_at":      draft_event["payload"]["created_at"],
            "orchestrator_confirmed": True,
            "events_emitted":  [e["event_type"] for e in emitted],
            "next_step":       "await beta_approved_requested for product_id=" + pid,
        }

        print("\n" + "=" * 66)
        print("  RESULT JSON")
        print("=" * 66)
        print(json.dumps(result_json, indent=2, ensure_ascii=False))

    else:
        print("\n[RUNNER] ERROR: product_draft_created event NOT found in bus.")
        print(f"  Events emitted: {[e.get('event_type') for e in emitted]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
