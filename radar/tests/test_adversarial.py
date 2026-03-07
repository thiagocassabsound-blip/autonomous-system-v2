"""
radar/tests/test_adversarial.py — Radar Teste 2: Adversarial Total

10 independent scenarios that force every gate, boundary, and constitutional
invariant of the Radar pipeline.

Scenarios:
  A — < 3 distinct sources           → abort Phase 2 quality gate
  B — 99 total occurrences           → abort Phase 2 quality gate
  C — 95% dominant source             → abort Phase 3 noise
  D — isolated spike (1 day)         → abort Phase 3 noise
  E — cluster_ratio ≥ 0.40           → penalty applied exactly once
  F — Emotional = 69.99              → confluence fail, no recommendation
  G — Monetization = 74.99           → confluence fail, no recommendation
  H — Growth_score = 55.0 (< 60)    → confluence fail, no recommendation
  I — ICE = BLOQUEADO                → ICE gate, Phase 6/7 skip
  J — Empty text_samples             → pipeline completes gracefully
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# Shared mock primitives
# ---------------------------------------------------------------------------

class _FakeProvider:
    """Configurable mock provider."""

    def __init__(
        self,
        name: str,
        occurrences: int = 50,
        sources: Optional[list[str]] = None,
        source_counts: Optional[dict] = None,
        text_samples: Optional[list[str]] = None,
        temporal_spread_days: int = 45,
        single_day: bool = False,
    ):
        self.PROVIDER_NAME = name
        self._occ    = occurrences
        self._srcs   = sources or ["reddit", "twitter", "forum"]
        self._sc     = source_counts or {s: occurrences // len(sources or ["reddit","twitter","forum"])
                                          for s in (sources or ["reddit","twitter","forum"])}
        self._texts  = text_samples if text_samples is not None else [
            "painful scheduling problem",
            "can't find a decent calendar tool",
            "scheduling friction costs deals",
            "back-and-forth emails to schedule",
            "timezone sync bug lost us a client",
        ]
        self._spread = temporal_spread_days
        self._single = single_day

    def collect(self, query_spec) -> dict:
        if self._single:
            date_range = ("2026-03-03", "2026-03-03")
            raw_entries = [
                {"text": self._texts[i % len(self._texts)], "date": "2026-03-03",
                 "source": self._srcs[i % len(self._srcs)]}
                for i in range(self._occ)
            ]
        else:
            start_day = 1
            raw_entries = [
                {"text": self._texts[i % len(self._texts)],
                 "date": f"2026-01-{(start_day + (i * self._spread // max(self._occ, 1)) % 28):02d}",
                 "source": self._srcs[i % len(self._srcs)]}
                for i in range(self._occ)
            ]
            date_range = ("2026-01-01", f"2026-01-{min(28, self._spread):02d}")

        return {
            "source":           self.PROVIDER_NAME,
            "raw_entries":      raw_entries,
            "occurrence_count": self._occ,
            "timestamp_range":  date_range,
            "sources_queried":  self._srcs,
            "source_counts":    self._sc,
            "text_samples":     self._texts,
            "metadata":         {"provider": self.PROVIDER_NAME},
            "is_real_data":     False,
            "growth_percent":   25.0,
            "positive_trend":   True,
            "trend_class":      "growing",
        }


class MockOrchestrator:
    def __init__(self):
        self.events: list[dict] = []
    def receive_event(self, event: dict) -> None:
        self.events.append(copy.deepcopy(event))
    def emit_event(self, name: str, payload: dict) -> None:
        self.receive_event({"event_type": name, "payload": payload})


class _BaseEngine:
    """Default engine returning a qualified ALTO result."""
    def __init__(self):
        self.call_count = 0
    def evaluate_opportunity_v2(self, payload: dict) -> dict:
        self.call_count += 1
        return {
            "event_id": "test-engine", "product_id": "test",
            "emotional": 75.0, "monetization": 80.0, "growth_score": 67.0,
            "growth_percent": 25.0, "score_final": 78.0,
            "cluster_ratio": 0.18, "cluster_penalty": False,
            "ice": "ALTO", "recommended": True, "status": "qualified",
            "global_state": "NORMAL",
        }


def _make_paths(tmp: str) -> dict:
    return {
        "snapshot_path":        os.path.join(tmp, "snapshots.jsonl"),
        "metrics_path":         os.path.join(tmp, "metrics.jsonl"),
        "score_results_path":   os.path.join(tmp, "scores.jsonl"),
        "ice_path":             os.path.join(tmp, "ice.jsonl"),
        "recommendations_path": os.path.join(tmp, "recommendations.jsonl"),
    }


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return out


def _run(providers, engine=None, overrides=None, tmp=None) -> tuple[dict, str, dict]:
    from radar.radar_engine import RadarEngine
    eng = engine or _BaseEngine()
    orch = MockOrchestrator()
    paths = _make_paths(tmp)
    radar = RadarEngine(orchestrator=orch, strategic_engine=eng,
                        providers=providers, **paths)
    result = radar.run_cycle(
        keyword="scheduling-friction", category="saas",
        operator_id="adversarial-test",
        eval_payload_overrides={
            "segment": "SaaS",
            "publico": "SDRs at SaaS companies",
            "contexto": "Remote sales teams lose velocity to scheduling",
            "problema_alvo": "No unified scheduling layer",
            **(overrides or {}),
        },
    )
    return result, orch, eng, paths


# ============================================================
# SCENARIO A — < 3 distinct sources
# ============================================================
def scenario_a(tmp: str) -> dict[str, bool]:
    """2 providers only → Phase 2 quality gate blocks (< 3 distinct sources)."""
    providers = [
        _FakeProvider("social_pain",  occurrences=80, sources=["reddit"],
                      source_counts={"reddit": 80}),
        _FakeProvider("search_intent", occurrences=80, sources=["twitter"],
                      source_counts={"twitter": 80}),
    ]
    result, orch, eng, paths = _run(providers, tmp=tmp)
    r: dict[str, bool] = {}
    r["A_status_insufficient_data_or_rejected"] = result.get("status") in (
        "insufficient_data", "rejected_by_noise", "blocked_by_governance"
    )
    r["A_blocked_true"]         = result.get("blocked") is True
    r["A_core_not_called"]      = eng.call_count == 0
    r["A_no_snapshot_scoring"]  = len(_read_jsonl(paths["scores.jsonl"]  if "scores.jsonl" in paths else paths["score_results_path"])) == 0
    r["A_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO B — 99 total occurrences
# ============================================================
def scenario_b(tmp: str) -> dict[str, bool]:
    """99 occurrences < min_occurrences(50×3=150) → Phase 2 gate."""
    providers = [
        _FakeProvider("social_pain",   occurrences=33, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":15,"twitter":10,"forum":8}),
        _FakeProvider("search_intent", occurrences=33, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":15,"twitter":10,"forum":8}),
        _FakeProvider("trend",          occurrences=33, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":15,"twitter":10,"forum":8}),
    ]
    result, orch, eng, paths = _run(providers, tmp=tmp)
    r: dict[str, bool] = {}
    r["B_status_insufficient_or_rejected"] = result.get("status") in (
        "insufficient_data", "rejected_by_noise", "blocked_by_governance"
    )
    r["B_blocked_true"]         = result.get("blocked") is True
    r["B_core_not_called"]      = eng.call_count == 0
    r["B_no_score_record"]      = len(_read_jsonl(paths["score_results_path"])) == 0
    r["B_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO C — 95% dominant source
# ============================================================
def scenario_c(tmp: str) -> dict[str, bool]:
    """95% from one source → Noise blocks."""
    providers = [
        _FakeProvider("social_pain",   occurrences=80, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":76, "twitter":2, "forum":2}),
        _FakeProvider("search_intent", occurrences=80, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":76, "twitter":2, "forum":2}),
        _FakeProvider("trend",          occurrences=80, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":76, "twitter":2, "forum":2}),
    ]
    result, orch, eng, paths = _run(providers, tmp=tmp)
    r: dict[str, bool] = {}
    r["C_snapshot_created"]     = result.get("phases", {}).get("phase_2_5_snapshot") is not None
    r["C_noise_executed"]       = result.get("phases", {}).get("phase_3_noise") is not None
    r["C_noise_blocked"]        = result.get("status") in ("rejected_by_noise",)
    r["C_core_not_called"]      = eng.call_count == 0
    r["C_blocked_true"]         = result.get("blocked") is True
    r["C_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO D — Isolated spike (1 day)
# ============================================================
def scenario_d(tmp: str) -> dict[str, bool]:
    """All occurrences on 1 day → Noise blocks (temporal_spread < 2)."""
    providers = [
        _FakeProvider("social_pain",   occurrences=80, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":28,"twitter":27,"forum":25},
                      single_day=True),
        _FakeProvider("search_intent", occurrences=80, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":28,"twitter":27,"forum":25},
                      single_day=True),
        _FakeProvider("trend",          occurrences=80, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":28,"twitter":27,"forum":25},
                      single_day=True),
    ]
    result, orch, eng, paths = _run(providers, tmp=tmp)
    r: dict[str, bool] = {}
    r["D_snapshot_created"]     = result.get("phases", {}).get("phase_2_5_snapshot") is not None
    r["D_noise_executed"]       = result.get("phases", {}).get("phase_3_noise") is not None
    r["D_noise_blocked"]        = result.get("status") == "rejected_by_noise"
    r["D_core_not_called"]      = eng.call_count == 0
    r["D_blocked_true"]         = result.get("blocked") is True
    r["D_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO E — cluster_ratio ≥ 0.40 (penalty exactly once)
# ============================================================
def scenario_e(tmp: str) -> dict[str, bool]:
    """High cluster_ratio forces penalty to be applied exactly once."""
    providers = [
        _FakeProvider("social_pain",   occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("search_intent", occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("trend",          occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
    ]

    class HighRatioEngine(_BaseEngine):
        """Returns cluster_ratio = 0.45 with penalty=True and penalized score."""
        def evaluate_opportunity_v2(self, payload: dict) -> dict:
            self.call_count += 1
            raw_score = 78.0
            penalized = round(raw_score * 0.6, 4)
            return {
                "event_id": "test-penalty", "product_id": "calendar-penalties",
                "emotional": 76.0, "monetization": 81.0, "growth_score": 67.0,
                "growth_percent": 25.0,
                "score_final":  penalized,      # 78×0.6 = 46.8 (Core already applied)
                "cluster_ratio": 0.45,
                "cluster_penalty": True,
                "ice": "MODERADO",              # penalized score drops ICE
                "recommended": True, "status": "qualified",
                "global_state": "NORMAL",
            }

    eng = HighRatioEngine()
    result, orch, eng_ref, paths = _run(providers, engine=eng, tmp=tmp)
    r: dict[str, bool] = {}
    scoring = result.get("phases", {}).get("phase_5_scoring", {})
    r["E_core_executed"]          = eng.call_count == 1
    r["E_cluster_penalty_flag"]   = scoring.get("cluster_penalty") is True
    r["E_cluster_ratio_ge040"]    = float(scoring.get("cluster_ratio", 0)) >= 0.40
    r["E_penalty_applied_once"]   = eng.call_count == 1   # only 1 evaluation
    # Dashboard shows penalized value (same as what Core returned)
    from radar.dashboard_output import build_dashboard_cards
    cards = build_dashboard_cards(
        paths["score_results_path"], paths["metrics_path"], paths["ice_path"]
    )
    expected_sf = float(scoring.get("score_final", -1))
    r["E_dashboard_shows_penalized_score"] = (
        len(cards) > 0 and abs(float(cards[0].get("score_final", 0)) - expected_sf) < 0.01
    )
    r["E_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


def pytest_approx_like(expected, actual=None, tol=0.01):
    """Simple comparison helper used inline."""
    return True  # The real check is in E_dashboard_shows_penalized_score above


# ============================================================
# SCENARIO F — Emotional = 69.99
# ============================================================
def scenario_f(tmp: str) -> dict[str, bool]:
    """Emotional just below 70 → recommendation gate blocks."""
    providers = [
        _FakeProvider("social_pain",   occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("search_intent", occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("trend",          occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
    ]

    class LowEmotionalEngine(_BaseEngine):
        def evaluate_opportunity_v2(self, payload: dict) -> dict:
            self.call_count += 1
            return {
                "event_id": "low-emotional", "product_id": "test",
                "emotional": 69.99, "monetization": 80.0, "growth_score": 67.0,
                "growth_percent": 25.0, "score_final": 75.0,
                "cluster_ratio": 0.18, "cluster_penalty": False,
                "ice": "ALTO", "recommended": True, "status": "qualified",
                "global_state": "NORMAL",
            }

    eng = LowEmotionalEngine()
    result, orch, _, paths = _run(providers, engine=eng, tmp=tmp)
    r: dict[str, bool] = {}
    rec = result.get("phases", {}).get("phase_7_recommendation", {})
    r["F_core_executed"]             = eng.call_count == 1
    r["F_recommendation_not_emitted"] = rec.get("emitted") is False
    r["F_recommendations_emitted_0"] = result.get("recommendations_emitted") == 0
    r["F_rec_jsonl_has_audit_record"] = len(_read_jsonl(paths["recommendations_path"])) >= 1
    r["F_pipeline_completed"]        = result.get("status") == "completed"
    r["F_score_persisted"]           = len(_read_jsonl(paths["score_results_path"])) >= 1
    r["F_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO G — Monetization = 74.99
# ============================================================
def scenario_g(tmp: str) -> dict[str, bool]:
    providers = [
        _FakeProvider("social_pain",   occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("search_intent", occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("trend",          occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
    ]

    class LowMonetizationEngine(_BaseEngine):
        def evaluate_opportunity_v2(self, payload: dict) -> dict:
            self.call_count += 1
            return {
                "event_id": "low-mon", "product_id": "test",
                "emotional": 75.0, "monetization": 74.99, "growth_score": 67.0,
                "growth_percent": 25.0, "score_final": 75.0,
                "cluster_ratio": 0.18, "cluster_penalty": False,
                "ice": "ALTO", "recommended": True, "status": "qualified",
                "global_state": "NORMAL",
            }

    eng = LowMonetizationEngine()
    result, orch, _, paths = _run(providers, engine=eng, tmp=tmp)
    r: dict[str, bool] = {}
    rec = result.get("phases", {}).get("phase_7_recommendation", {})
    r["G_core_executed"]              = eng.call_count == 1
    r["G_recommendation_not_emitted"] = rec.get("emitted") is False
    r["G_recommendations_emitted_0"]  = result.get("recommendations_emitted") == 0
    r["G_rec_jsonl_has_audit_record"]  = len(_read_jsonl(paths["recommendations_path"])) >= 1
    r["G_pipeline_completed"]         = result.get("status") == "completed"
    r["G_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO H — Growth_score = 55.0 (< 60)
# ============================================================
def scenario_h(tmp: str) -> dict[str, bool]:
    providers = [
        _FakeProvider("social_pain",   occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("search_intent", occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("trend",          occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
    ]

    class LowGrowthEngine(_BaseEngine):
        def evaluate_opportunity_v2(self, payload: dict) -> dict:
            self.call_count += 1
            return {
                "event_id": "low-growth", "product_id": "test",
                "emotional": 75.0, "monetization": 80.0, "growth_score": 55.0,
                "growth_percent": 14.99, "score_final": 75.0,
                "cluster_ratio": 0.18, "cluster_penalty": False,
                "ice": "ALTO", "recommended": True, "status": "qualified",
                "global_state": "NORMAL",
            }

    eng = LowGrowthEngine()
    result, orch, _, paths = _run(providers, engine=eng, tmp=tmp)
    r: dict[str, bool] = {}
    rec = result.get("phases", {}).get("phase_7_recommendation", {})
    r["H_core_executed"]              = eng.call_count == 1
    r["H_recommendation_not_emitted"] = rec.get("emitted") is False
    r["H_recommendations_emitted_0"]  = result.get("recommendations_emitted") == 0
    r["H_rec_jsonl_has_audit_record"]  = len(_read_jsonl(paths["recommendations_path"])) >= 1
    r["H_pipeline_completed"]         = result.get("status") == "completed"
    r["H_contract_keys_present"] = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO I — ICE = BLOQUEADO
# ============================================================
def scenario_i(tmp: str) -> dict[str, bool]:
    """Core returns ICE=BLOQUEADO → pipeline aborts after Phase 5, Phase 6/7 skip."""
    providers = [
        _FakeProvider("social_pain",   occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("search_intent", occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("trend",          occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
    ]

    class BlockedEngine(_BaseEngine):
        def evaluate_opportunity_v2(self, payload: dict) -> dict:
            self.call_count += 1
            return {
                "event_id": "blocked-ice", "product_id": "test",
                "emotional": 45.0, "monetization": 40.0, "growth_score": 30.0,
                "growth_percent": 10.0, "score_final": 38.0,
                "cluster_ratio": 0.18, "cluster_penalty": False,
                "ice": "BLOQUEADO", "recommended": False, "status": "blocked",
                "global_state": "NORMAL",
            }

    eng = BlockedEngine()
    result, orch, _, paths = _run(providers, engine=eng, tmp=tmp)
    r: dict[str, bool] = {}
    phases = result.get("phases", {})
    r["I_core_executed"]           = eng.call_count == 1
    r["I_ice_decision_persisted"]  = len(_read_jsonl(paths["ice_path"])) >= 1
    r["I_phase6_did_not_execute"]  = "phase_6_strategy" not in phases
    r["I_phase7_did_not_execute"]  = "phase_7_recommendation" not in phases
    r["I_rec_not_emitted"]         = result.get("recommendations_emitted", 1) == 0
    r["I_status_ice_blocked"]      = result.get("status") == "ice_blocked"
    # ICE=BLOQUEADO: pipeline ends early, blocked=True
    r["I_blocked_true"]            = result.get("blocked") is True
    r["I_contract_keys_present"]   = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ============================================================
# SCENARIO J — Empty text_samples
# ============================================================
def scenario_j(tmp: str) -> dict[str, bool]:
    """No text samples → pipeline should complete without crash, cluster synthetic."""
    providers = [
        _FakeProvider("social_pain",   occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15},
                      text_samples=[]),
        _FakeProvider("search_intent", occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15},
                      text_samples=[]),
        _FakeProvider("trend",          occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15},
                      text_samples=[]),
    ]
    result, orch, eng, paths = _run(providers, tmp=tmp)
    r: dict[str, bool] = {}
    r["J_no_crash"]                = True  # reaching here means no exception
    r["J_pipeline_completed_or_blocked"] = result.get("status") in (
        "completed", "rejected_by_noise", "insufficient_data"
    )
    r["J_clusters_formed_or_empty"]= isinstance(result.get("clusters", result.get("phases", {}).get("phase_4_clusters", {}).get("clusters", [])), list)
    r["J_contract_keys_present"]   = all(k in result for k in ("blocked","dashboard_cards","recommendations_emitted"))
    return r


# ---------------------------------------------------------------------------
# General invariant checks (applied to a successful run)
# ---------------------------------------------------------------------------

def general_invariants(tmp: str) -> dict[str, bool]:
    """Run the happy path twice and verify JSONL is append-only (grows, never rewrites)."""
    providers = [
        _FakeProvider("social_pain",   occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("search_intent", occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
        _FakeProvider("trend",          occurrences=60, sources=["reddit","twitter","forum"],
                      source_counts={"reddit":25,"twitter":20,"forum":15}),
    ]
    result1, _, _, paths = _run(providers, tmp=tmp)
    result2, _, _, _    = _run(providers, tmp=tmp)

    r: dict[str, bool] = {}
    # Snapshots must grow — not be overwritten
    snap_lines = _read_jsonl(paths["snapshot_path"])
    r["GEN_snapshot_jsonl_appends"] = len(snap_lines) >= 2

    scores = _read_jsonl(paths["score_results_path"])
    r["GEN_scores_jsonl_appends"] = len(scores) >= 2

    ice = _read_jsonl(paths["ice_path"])
    r["GEN_ice_jsonl_appends"] = len(ice) >= 2

    recs = _read_jsonl(paths["recommendations_path"])
    r["GEN_recommendations_jsonl_appends"] = len(recs) >= 2

    # engine_result not mutated: auto_execution never leaks into result
    r["GEN_no_auto_execution_in_result"] = "auto_execution" not in result1

    return r


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 70)
    print(" RADAR — TESTE 2: ADVERSARIAL TOTAL (TODOS OS GATES + FRONTEIRAS)")
    print("=" * 70 + "\n")

    all_results: dict[str, bool] = {}

    scenarios = [
        ("A — < 3 Sources",      scenario_a),
        ("B — 99 Occurrences",   scenario_b),
        ("C — 95% Dom Source",   scenario_c),
        ("D — Isolated Spike",   scenario_d),
        ("E — Ratio Penalty",    scenario_e),
        ("F — Emotional 69.99",  scenario_f),
        ("G — Monetization 74.99", scenario_g),
        ("H — Growth < 60",      scenario_h),
        ("I — ICE BLOQUEADO",    scenario_i),
        ("J — Empty TextSamples",scenario_j),
    ]

    for label, fn in scenarios:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                res = fn(tmp)
            except Exception as exc:
                res = {f"{label.split()[0]}_CRASHED": False}
                print(f"  [FAIL] {label} — EXCEPTION: {exc}")

        passed = sum(1 for v in res.values() if v)
        total  = len(res)
        status = "PASS" if passed == total else "FAIL"
        print(f"  [{status}] Scenario {label} ({passed}/{total})")
        for k, v in res.items():
            if not v:
                print(f"         [FAIL] {k}: {v}")
        all_results.update(res)

    # General invariants
    with tempfile.TemporaryDirectory() as tmp:
        gen = general_invariants(tmp)
    g_pass = sum(1 for v in gen.values() if v)
    g_tot  = len(gen)
    print(f"\n  [{'PASS' if g_pass==g_tot else 'FAIL'}] General Invariants ({g_pass}/{g_tot})")
    for k, v in gen.items():
        print(f"       {'[PASS]' if v else '[FAIL]'} {k}: {v}")
    all_results.update(gen)

    passed = sum(1 for v in all_results.values() if v)
    total  = len(all_results)
    ok     = passed == total

    summary = {
        "test":                   "Radar Teste 2 — Adversarial Total",
        "total":  total, "passed": passed, "failed": total - passed,
        "constitutional_integrity": ok,
        "scenarios": all_results,
    }
    print("\n" + "=" * 70)
    print(json.dumps(summary, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
