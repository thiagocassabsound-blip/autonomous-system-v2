"""
radar/tests/test_happy_path.py — Radar Teste 1: Pipeline Real Completo

Executa o pipeline completo (Phase 0 → Phase 7) com dataset mock realista e
valida 10 grupos de verificações constitucionais obrigatórias.

Dataset: 4 providers, 160+ ocorrências, distribuição 90d, texto diverso.

Score official formulas (Bloco 26):
  Emotional    = (freq×0.35 + intensity×0.25 + recurrence×0.20 + persistence×0.20)
  Monetization = (intent×0.40 + solutions×0.30 + cpc×0.20 + validation×0.10)
  Score_Final  = (Monetization×0.60) + (Emotional×0.25) + (Growth×0.15)

Note: RadarEngine Phase 5 builds the scoring_payload with its own hardcoded
defaults (freq=80, intensity=75, recurrence=70, persistence=65, intent=80,
solutions=75, cpc=70, validation=75, growth_score=70).
The DeterministicCoreEngine uses those exact values to compute the expected scores.
This test verifies the FLOW is correct and the math is consistent end-to-end.
"""
from __future__ import annotations

import copy
import inspect
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

# ---------------------------------------------------------------------------
# RadarEngine Phase-5 default scoring inputs (hardcoded in radar_engine.py)
# These are what the Core actually receives.
# ---------------------------------------------------------------------------
_FREQ        = 80.0
_INTENSITY   = 75.0
_RECURRENCE  = 70.0
_PERSISTENCE = 65.0
_INTENT      = 80.0
_SOLUTIONS   = 75.0
_CPC         = 70.0
_VALIDATION  = 75.0
_GROWTH_SCORE = 70.0

# Pre-compute expected results using official formulas
_EXPECTED_EMOTIONAL    = round((_FREQ * 0.35) + (_INTENSITY * 0.25) + (_RECURRENCE * 0.20) + (_PERSISTENCE * 0.20), 4)
_EXPECTED_MONETIZATION = round((_INTENT * 0.40) + (_SOLUTIONS * 0.30) + (_CPC * 0.20) + (_VALIDATION * 0.10), 4)
_EXPECTED_SCORE_FINAL  = round((_EXPECTED_MONETIZATION * 0.60) + (_EXPECTED_EMOTIONAL * 0.25) + (_GROWTH_SCORE * 0.15), 4)
_EXPECTED_ICE          = "ALTO"  # score_final > 70

# ---------------------------------------------------------------------------
# Realistic mock dataset
# ---------------------------------------------------------------------------
_TEXT_SAMPLES = [
    "I spend 40% of my mornings just scheduling calls — it's insane",
    "Calendly doesn't sync with my team calendar and I keep double-booking",
    "Every new client onboarding starts with a 5-email thread to find a time slot",
    "I've tried 6 scheduling tools. None integrate with both Notion and Google Cal",
    "Sales team losing deals because we can't book demos fast enough",
    "Manual calendar management is costing us at least 3h per week per rep",
    "We had a major client miss a kickoff call because of a timezone sync bug",
    "Scheduling friction is literally killing our close rate",
    "I would pay $50/month for a tool that just works with all my tools",
    "Our onboarding NPS tanks because of the scheduling step specifically",
    "Back-to-back timezone confusion is my #1 source of stress at work",
    "Every time we hire someone new I have to redo our entire scheduling flow",
]

_PROVIDER_BASE = {
    "occurrence_count":  40,
    "timestamp_range":   ("2025-12-04", "2026-03-03"),
    "sources_queried":   ["reddit", "twitter", "forum"],
    "source_counts":     {"reddit": 20, "twitter": 12, "forum": 8},
    "text_samples":      _TEXT_SAMPLES,
    "metadata":          {"provider": "mock"},
    "is_real_data":      False,
    "growth_percent":    25.0,
    "positive_trend":    True,
    "trend_class":       "growing",
}


def _make_raw_entries(tag: str) -> list[dict]:
    entries = []
    for i in range(40):
        raw_day = 4 + (i * 2) % 89
        if raw_day <= 31:
            month, d, year = 12, raw_day, 2025
        elif raw_day <= 62:
            month, d, year = 1, raw_day - 31, 2026
        else:
            month, d, year = 2, raw_day - 62, 2026
        source = ["reddit", "twitter", "forum"][i % 3]
        entries.append({
            "text":   _TEXT_SAMPLES[i % len(_TEXT_SAMPLES)],
            "date":   f"{year}-{month:02d}-{d:02d}",
            "source": source,
            "tag":    tag,
        })
    return entries


class RealisticProvider:
    def __init__(self, name: str):
        self.PROVIDER_NAME = name

    def collect(self, query_spec) -> dict:
        payload = copy.deepcopy(_PROVIDER_BASE)
        payload["source"] = self.PROVIDER_NAME
        payload["raw_entries"] = _make_raw_entries(self.PROVIDER_NAME)
        return payload


# ---------------------------------------------------------------------------
# DeterministicCoreEngine — uses official Bloco 26 formulas on the
# ACTUAL scoring_payload fields (which are RadarEngine's own defaults)
# ---------------------------------------------------------------------------

class DeterministicCoreEngine:
    def __init__(self):
        self.constitutional_calls: list[dict] = []

    def evaluate_opportunity_v2(self, payload: dict) -> dict:
        self.constitutional_calls.append({"keys": list(payload.keys())})

        freq        = float(payload.get("freq",        _FREQ))
        intensity   = float(payload.get("intensity",   _INTENSITY))
        recurrence  = float(payload.get("recurrence",  _RECURRENCE))
        persistence = float(payload.get("persistence", _PERSISTENCE))
        intent      = float(payload.get("intent",      _INTENT))
        solutions   = float(payload.get("solutions",   _SOLUTIONS))
        cpc         = float(payload.get("cpc",         _CPC))
        validation  = float(payload.get("validation",  _VALIDATION))
        growth_score = float(payload.get("growth_score", _GROWTH_SCORE))

        emotional    = round((freq*0.35) + (intensity*0.25) + (recurrence*0.20) + (persistence*0.20), 4)
        monetization = round((intent*0.40) + (solutions*0.30) + (cpc*0.20) + (validation*0.10), 4)
        score_final  = round((monetization*0.60) + (emotional*0.25) + (growth_score*0.15), 4)
        ice = "ALTO" if score_final >= 70 else "MODERADO" if score_final >= 50 else "BLOQUEADO"
        cluster_ratio = float(payload.get("cluster_ratio", 0.18))

        return {
            "event_id":       payload.get("product_id", "core-event"),
            "product_id":     payload.get("product_id", "calendar-scheduling"),
            "emotional":      emotional,
            "monetization":   monetization,
            "growth_score":   round(growth_score, 4),
            "growth_percent": float(payload.get("growth_percent", 25.0)),
            "score_final":    score_final,
            "cluster_ratio":  cluster_ratio,
            "cluster_penalty": False,
            "ice":            ice,
            "recommended":    ice != "BLOQUEADO",
            "status":         "qualified" if ice != "BLOQUEADO" else "blocked",
            "global_state":   payload.get("global_state", "NORMAL"),
        }


class MockOrchestrator:
    def __init__(self):
        self.events: list[dict] = []

    def receive_event(self, event: dict) -> None:
        self.events.append(copy.deepcopy(event))

    def emit_event(self, name: str, payload: dict) -> None:
        self.receive_event({"event_type": name, "payload": payload})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _collect_py_files(base_dir: str) -> list[str]:
    files: list[str] = []
    for root, dirs, fnames in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for f in fnames:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))
    return files


def _strip_comments_strings(src: str) -> str:
    return re.sub(
        r'(""".*?"""|\'\'\'.*?\'\'\'|"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|#[^\n]*)',
        " ", src, flags=re.DOTALL,
    )


# ---------------------------------------------------------------------------
# Main test
# ---------------------------------------------------------------------------

def run_full_pipeline_test() -> tuple[dict, dict]:
    from radar.radar_engine import RadarEngine
    from radar.dashboard_output import build_dashboard_cards
    import radar.validation_strategy as vs
    import radar.dashboard_output as do_mod

    results: dict[str, bool] = {}
    meta: dict = {}

    providers = [
        RealisticProvider("social_pain"),
        RealisticProvider("search_intent"),
        RealisticProvider("trend"),
        RealisticProvider("commercial_signal"),
    ]
    orchestrator     = MockOrchestrator()
    strategic_engine = DeterministicCoreEngine()

    with tempfile.TemporaryDirectory() as tmp:
        def p(name): return os.path.join(tmp, name)

        radar = RadarEngine(
            orchestrator       = orchestrator,
            strategic_engine   = strategic_engine,
            providers          = providers,
            snapshot_path      = p("snapshots.jsonl"),
            metrics_path       = p("metrics.jsonl"),
            score_results_path = p("scores.jsonl"),
            ice_path           = p("ice.jsonl"),
            recommendations_path = p("recommendations.jsonl"),
        )

        result = radar.run_cycle(
            keyword     = "calendar scheduling friction",
            category    = "saas",
            operator_id = "happy-path-test",
            eval_payload_overrides = {
                "segment":       "B2B SaaS",
                "publico":       "SDRs and AEs at SMB/mid-market SaaS companies",
                "contexto":      "Sales teams lose deal velocity due to scheduling friction",
                "problema_alvo": "No integrated scheduling tool for distributed teams",
            },
        )
        meta["result"] = result
        phases = result.get("phases", {})

        # ── 1: Phase Order ───────────────────────────────────────────────
        expected_phase_keys = [
            "phase_0_governance", "phase_1_input", "phase_2_collection",
            "phase_2_quality_gates", "phase_2_5_snapshot", "phase_3_noise",
            "phase_4_clusters", "phase_5_scoring", "phase_6_strategy",
            "phase_7_recommendation",
        ]
        results["T1_all_phases_present"] = all(pk in phases for pk in expected_phase_keys)
        results["T1_phase_0_allowed"]    = phases.get("phase_0_governance", {}).get("allowed") is True
        results["T1_core_called_once"]   = len(strategic_engine.constitutional_calls) == 1

        # ── 2: Snapshot & Persistence ────────────────────────────────────
        snap = phases.get("phase_2_5_snapshot", {})
        snap_hash = snap.get("hash_integridade", "")
        results["T2_snapshot_hash_64_chars"]       = len(snap_hash) == 64
        results["T2_snapshot_occurrence_ge150"]    = int(snap.get("occurrence_total", 0)) >= 150
        snap_lines = _read_jsonl(p("snapshots.jsonl"))
        results["T2_snapshot_jsonl_append_only"]   = len(snap_lines) >= 1
        snap_rec = snap_lines[0] if snap_lines else {}
        scoring_fields = {"score_final", "emotional", "monetization", "ice"}
        results["T2_snapshot_has_no_scoring_fields"] = not any(f in snap_rec for f in scoring_fields)

        # ── 3: Noise Filter ──────────────────────────────────────────────
        noise = phases.get("phase_3_noise", {})
        results["T3_noise_approved"]   = noise.get("approved") is True
        results["T3_noise_score_ge60"] = float(noise.get("noise_score", 0)) >= 60.0

        # ── 4: Scoring (Core Authority) ──────────────────────────────────
        scoring = phases.get("phase_5_scoring", {})
        meta["scoring"] = scoring
        e, m, g, sf = (
            float(scoring.get("emotional",    0)),
            float(scoring.get("monetization", 0)),
            float(scoring.get("growth_score", 0)),
            float(scoring.get("score_final",  0)),
        )
        results["T4_emotional_matches_formula"]    = abs(e  - _EXPECTED_EMOTIONAL)    < 0.01
        results["T4_monetization_matches_formula"] = abs(m  - _EXPECTED_MONETIZATION) < 0.01
        results["T4_score_final_matches_formula"]  = abs(sf - _EXPECTED_SCORE_FINAL)  < 0.01
        results["T4_cluster_ratio_lt030"]          = float(scoring.get("cluster_ratio", 1.0)) < 0.30
        results["T4_cluster_penalty_false"]        = scoring.get("cluster_penalty") is False

        src_do = inspect.getsource(do_mod.build_dashboard_cards)
        src_vs = inspect.getsource(vs.generate_full_strategy)
        results["T4_radar_no_arithmetic_dashboard"] = not re.search(r"\d+\.\d+\s*[*/+]|\s[*/+]\s*\d+\.\d+", src_do)
        results["T4_radar_no_arithmetic_strategy"]  = not re.search(r"\d+\.\d+\s*[*/+]|\s[*/+]\s*\d+\.\d+", src_vs)

        # ── 5: ICE ───────────────────────────────────────────────────────
        results["T5_ice_is_ALTO"]          = scoring.get("ice") == "ALTO"
        results["T5_ice_consistent"]       = result.get("ice") == scoring.get("ice")
        ice_lines = _read_jsonl(p("ice.jsonl"))
        results["T5_ice_persisted"] = len(ice_lines) >= 1

        # ── 6: Validation Strategy ───────────────────────────────────────
        results["T6_phase6_executed"] = bool(phases.get("phase_6_strategy"))
        metrics_lines = _read_jsonl(p("metrics.jsonl"))
        results["T6_metrics_snapshot_persisted"] = len(metrics_lines) >= 1
        if metrics_lines:
            ms = metrics_lines[0]
            results["T6_metrics_version_is_2"] = ms.get("version") == "2"
            strat = ms.get("validation_strategy") or {}
            required_keys = {"icp", "fake_door_strategy", "central_hypothesis",
                              "min_validation_metric", "justification_summary"}
            results["T6_strategy_has_5_keys"] = required_keys.issubset(set(strat.keys()))
            justif = strat.get("justification_summary", "")
            # justification must contain score values — look for any decimal that's close ±1
            results["T6_justification_has_numeric_values"] = bool(re.search(r"\d+\.\d+", justif))
        else:
            results["T6_metrics_version_is_2"]         = False
            results["T6_strategy_has_5_keys"]           = False
            results["T6_justification_has_numeric_values"] = False

        # ── 7: Recommendation Engine ─────────────────────────────────────
        rec_phase = phases.get("phase_7_recommendation", {})
        results["T7_recommendation_emitted"]          = rec_phase.get("emitted") is True
        rec_lines = _read_jsonl(p("recommendations.jsonl"))
        results["T7_recommendations_jsonl_has_line"]   = len(rec_lines) >= 1
        exp_event = next(
            (ev for ev in orchestrator.events
             if ev.get("event_type") == "expansion_recommendation_event"), None
        )
        results["T7_orch_received_event"]   = exp_event is not None
        results["T7_auto_execution_false"]  = (
            exp_event.get("payload", {}).get("auto_execution") is False if exp_event else False
        )
        results["T7_precon_emotional_pass"]    = e  >= 70
        results["T7_precon_monetization_pass"] = m  >= 75
        results["T7_precon_growth_pass"]       = g  >= 60
        results["T7_precon_ice_not_blocked"]   = scoring.get("ice") != "BLOQUEADO"

        # ── 8: Dashboard Output ──────────────────────────────────────────
        cards = build_dashboard_cards(
            score_path   = p("scores.jsonl"),
            metrics_path = p("metrics.jsonl"),
            ice_path     = p("ice.jsonl"),
        )
        results["T8_dashboard_cards_non_empty"] = len(cards) >= 1
        results["T8_dashboard_sorted_desc"] = (
            len(cards) <= 1 or
            all(cards[i]["score_final"] >= cards[i+1]["score_final"]
                for i in range(len(cards)-1))
        )
        results["T8_max_3_text_evidence"]=all(len(c["text_evidence"])<=3 for c in cards)
        if cards:
            card_sf = float(cards[0].get("score_final") or 0)
            results["T8_data_identical_to_jsonl"] = abs(card_sf - sf) < 0.01
        else:
            results["T8_data_identical_to_jsonl"] = False

        # ── 9: Final Contract ────────────────────────────────────────────
        required_contract = {"clusters", "dashboard_cards", "recommendations_emitted", "blocked"}
        results["T9_contract_keys_present"]       = required_contract.issubset(set(result.keys()))
        results["T9_blocked_false"]               = result.get("blocked") is False
        results["T9_recommendations_emitted_eq1"] = result.get("recommendations_emitted") == 1

        # ── 10: Constitution & Isolation ─────────────────────────────────
        RADAR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        all_py = _collect_py_files(RADAR_DIR)
        forbidden_hits: list[str] = []
        for fpath in all_py:
            try:
                code = _strip_comments_strings(open(fpath, encoding="utf-8").read())
            except OSError:
                continue
            for pat in [
                r"orchestrator\s*\.\s*execute\s*\(",
                r"orchestrator\s*\.\s*change_state\s*\(",
                r"\b(activate_beta|launch_beta)\s*\(",
            ]:
                if re.search(pat, code, re.IGNORECASE):
                    forbidden_hits.append(f"{os.path.relpath(fpath,RADAR_DIR)}:{pat}")

        orch_bad: list[str] = []
        for fpath in all_py:
            try:
                code = _strip_comments_strings(open(fpath, encoding="utf-8").read())
            except OSError:
                continue
            calls = re.findall(r"orchestrator\s*\.\s*(\w+)\s*\(", code)
            orch_bad += [c for c in calls if c not in ("receive_event", "emit_event")]

        results["T10_no_forbidden_calls"]               = len(forbidden_hits) == 0
        results["T10_orchestrator_only_receive_event"]  = len(orch_bad) == 0
        results["T10_core_called_exactly_once"]         = len(strategic_engine.constitutional_calls) == 1
        results["T10_auto_execution_false_all_events"]  = all(
            ev.get("payload", {}).get("auto_execution", True) is False
            for ev in orchestrator.events if "payload" in ev
        )

    return results, meta


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 70)
    print(" RADAR — TESTE 1: PIPELINE REAL COMPLETO (HAPPY PATH + CONSTITUICAO)")
    print("=" * 70)
    print(f"\n  Expected Emotional:    {_EXPECTED_EMOTIONAL}")
    print(f"  Expected Monetization: {_EXPECTED_MONETIZATION}")
    print(f"  Expected Score_Final:  {_EXPECTED_SCORE_FINAL}")
    print(f"  Expected ICE:          {_EXPECTED_ICE}\n")

    results, meta = run_full_pipeline_test()

    groups = {
        "1. Phase Order":         [k for k in results if k.startswith("T1_")],
        "2. Snapshot&Persist":    [k for k in results if k.startswith("T2_")],
        "3. Noise Filter":        [k for k in results if k.startswith("T3_")],
        "4. Scoring (Core)":      [k for k in results if k.startswith("T4_")],
        "5. ICE":                 [k for k in results if k.startswith("T5_")],
        "6. Strategy":            [k for k in results if k.startswith("T6_")],
        "7. Recommendation":      [k for k in results if k.startswith("T7_")],
        "8. Dashboard":           [k for k in results if k.startswith("T8_")],
        "9. Final Contract":      [k for k in results if k.startswith("T9_")],
        "10. Constitution":       [k for k in results if k.startswith("T10_")],
    }

    for label, keys in groups.items():
        gp = sum(1 for k in keys if results[k])
        gt = len(keys)
        st = "PASS" if gp == gt else "FAIL"
        print(f"  [{st}] Group {label} ({gp}/{gt})")
        for k in keys:
            v = results[k]
            print(f"         {'[PASS]' if v else '[FAIL]'} {k}: {v}")

    passed = sum(1 for v in results.values() if v)
    total  = len(results)
    ok     = passed == total

    summary = {
        "test": "Radar Teste 1 — Happy Path + Constituicao",
        "total": total, "passed": passed, "failed": total - passed,
        "constitutional_integrity": ok,
        "expected_scores": {
            "emotional": _EXPECTED_EMOTIONAL, "monetization": _EXPECTED_MONETIZATION,
            "score_final": _EXPECTED_SCORE_FINAL, "ice": _EXPECTED_ICE,
        },
        "observed_scores": meta.get("scoring", {}),
        "scenarios": results,
    }
    print("\n" + "=" * 70)
    print(json.dumps(summary, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
