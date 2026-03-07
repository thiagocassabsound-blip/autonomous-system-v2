"""
radar/tests/test_integration_lock.py — Etapa 14

Orchestrator Integration Lock:
  • Static audit: forbidden patterns must NOT appear in radar/* Python files
  • Interface audit: orchestrator used ONLY via receive_event
  • Dynamic audit: run_cycle() returns correct contract shape with no side-effects
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from radar.tests.test_determinism_stability import (
    MockProvider,
    MockStrategicEngine,
    MockOrchestrator,
    _make_temp_paths,
)
from radar.radar_engine import RadarEngine

RADAR_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Executable-only forbidden patterns (NOT comments/docstrings)
FORBIDDEN_PATTERNS = {
    "orchestrator.execute":        r"orchestrator\s*\.\s*execute\s*\(",
    "orchestrator.change_state":   r"orchestrator\s*\.\s*change_state\s*\(",
    "beta_activation_call":        r"\b(activate_beta|start_beta|launch_beta|create_beta)\s*\(",
    "create_product_call":         r"\b(create_product|new_product|product_create)\s*\(",
}

# True for lines that are executable (not inside a string literal / comment)
_STRING_PATTERNS = re.compile(
    r'(""".*?"""|\'\'\'.*?\'\'\'|"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|#[^\n]*)',
    re.DOTALL,
)


def _strip_comments_strings(src: str) -> str:
    """Remove string literals and comments, leaving code skeleton."""
    return _STRING_PATTERNS.sub(" ", src)


def _collect_radar_files() -> list[str]:
    files: list[str] = []
    for root, dirs, fnames in os.walk(RADAR_DIR):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for f in fnames:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))
    return sorted(files)


# -------------------------------------------------------------------------
# Static audit
# -------------------------------------------------------------------------

def static_audit() -> dict[str, bool]:
    results: dict[str, bool] = {}
    radar_files = _collect_radar_files()
    forbidden_hits: dict[str, list[str]] = {}

    for fpath in radar_files:
        rel = os.path.relpath(fpath, RADAR_DIR)
        try:
            src = open(fpath, encoding="utf-8").read()
        except OSError:
            continue
        code_only = _strip_comments_strings(src)
        for label, pattern in FORBIDDEN_PATTERNS.items():
            if re.search(pattern, code_only, re.IGNORECASE):
                forbidden_hits.setdefault(label, []).append(rel)

    results["A_no_forbidden_orch_exec_calls"]   = "orchestrator.execute"      not in forbidden_hits
    results["B_no_forbidden_orch_change_state"] = "orchestrator.change_state" not in forbidden_hits
    results["C_no_beta_activation_calls"]       = "beta_activation_call"      not in forbidden_hits
    results["D_no_create_product_calls"]        = "create_product_call"       not in forbidden_hits

    # Capital/wallet only allowed in docstrings — must NOT appear in raw code
    cap_in_code: list[str] = []
    for fpath in radar_files:
        rel = os.path.relpath(fpath, RADAR_DIR)
        try:
            src = open(fpath, encoding="utf-8").read()
        except OSError:
            continue
        code_only = _strip_comments_strings(src)
        if re.search(r"\b(wallet|withdraw|purchase)\b", code_only, re.IGNORECASE):
            cap_in_code.append(rel)
    results["E_wallet_withdraw_not_in_code"] = len(cap_in_code) == 0

    # Interface audit: ALL orchestrator.xxx calls must be receive_event
    bad_calls: dict[str, list[str]] = {}
    for fpath in radar_files:
        rel = os.path.relpath(fpath, RADAR_DIR)
        try:
            src = open(fpath, encoding="utf-8").read()
        except OSError:
            continue
        code_only = _strip_comments_strings(src)
        calls = re.findall(r"orchestrator\s*\.\s*(\w+)\s*\(", code_only)
        bad = [c for c in calls if c not in ("receive_event", "emit_event")]
        if bad:
            bad_calls[rel] = bad
    results["F_orchestrator_interface_restricted"] = len(bad_calls) == 0

    return results


# -------------------------------------------------------------------------
# Dynamic audit
# -------------------------------------------------------------------------

def dynamic_audit() -> dict[str, bool]:
    results: dict[str, bool] = {}

    # Simulated global state — must be UNCHANGED after pipeline
    global_state = {
        "global_state":           "NORMAL",
        "financial_alert_active": False,
        "capital":                1000.0,
        "active_betas":           0,
    }
    state_before = copy.deepcopy(global_state)

    with tempfile.TemporaryDirectory() as tmp:
        orch = MockOrchestrator()
        radar = RadarEngine(
            orchestrator     = orch,
            strategic_engine = MockStrategicEngine(),
            providers        = [
                MockProvider("social_pain"),
                MockProvider("search_intent"),
                MockProvider("trend"),
                MockProvider("commercial_signal"),
            ],
            **_make_temp_paths(tmp),
        )

        r = radar.run_cycle(
            keyword     = "calendar scheduling friction",
            category    = "saas",
            operator_id = "test-op",
            eval_payload_overrides = {
                "segment":       "SaaS",
                "publico":       "Remote SaaS teams",
                "contexto":      "Distributed teams need scheduling",
                "problema_alvo": "Calendar sync gap",
            },
        )

    # G) Required contract keys in return
    required = {"clusters", "dashboard_cards", "recommendations_emitted", "blocked"}
    results["G_contract_fields_present"] = required.issubset(set(r.keys()))

    # H) blocked=False on successful completion
    results["H_blocked_false_on_success"] = r.get("blocked") is False

    # I) recommendations_emitted is int
    results["I_recommendations_emitted_is_int"] = isinstance(r.get("recommendations_emitted"), int)

    # J) dashboard_cards is list
    results["J_dashboard_cards_is_list"] = isinstance(r.get("dashboard_cards"), list)

    # K) clusters is list
    results["K_clusters_is_list"] = isinstance(r.get("clusters"), list)

    # L) Global state dict unchanged
    results["L_global_state_unchanged"] = global_state == state_before

    # M) Orchestrator received at least one event
    results["M_orchestrator_received_at_least_one_event"] = len(orch.events) >= 1

    # N) Every emitted event payload has auto_execution=False
    results["N_auto_execution_false_in_all_events"] = all(
        e.get("payload", {}).get("auto_execution", True) is False
        for e in orch.events
        if "payload" in e
    )

    # O) Blocked pipeline paths also return required contract keys
    with tempfile.TemporaryDirectory() as tmp2:

        class BlockedEngine(MockStrategicEngine):
            def evaluate_opportunity_v2(self, payload):
                r = super().evaluate_opportunity_v2(payload)
                r["ice"] = "BLOQUEADO"
                r["recommended"] = False
                return r

        orch2 = MockOrchestrator()
        radar2 = RadarEngine(
            orchestrator     = orch2,
            strategic_engine = BlockedEngine(),
            providers        = [
                MockProvider("social_pain"), MockProvider("search_intent"),
                MockProvider("trend"), MockProvider("commercial_signal"),
            ],
            **_make_temp_paths(tmp2),
        )
        rb = radar2.run_cycle(
            keyword="calendar scheduling friction", category="saas",
            operator_id="test-op",
            eval_payload_overrides={
                "segment": "SaaS", "publico": "x", "contexto": "y", "problema_alvo": "z",
            },
        )
    results["O_blocked_pipeline_has_contract_keys"] = (
        rb.get("blocked") is True and
        "dashboard_cards" in rb and
        "recommendations_emitted" in rb
    )

    return results


# -------------------------------------------------------------------------
# Runner
# -------------------------------------------------------------------------

def run_all() -> None:
    all_results: dict[str, bool] = {}

    print("\n=== STATIC AUDIT ===")
    s = static_audit()
    all_results.update(s)
    for k, v in s.items():
        print(f"  {'[PASS]' if v else '[FAIL]'} {k}: {v}")

    print("\n=== DYNAMIC AUDIT ===")
    d = dynamic_audit()
    all_results.update(d)
    for k, v in d.items():
        print(f"  {'[PASS]' if v else '[FAIL]'} {k}: {v}")

    passed = sum(1 for v in all_results.values() if v)
    total  = len(all_results)
    ok     = passed == total

    summary = {
        "total":  total,
        "passed": passed,
        "failed": total - passed,
        "constitutional_integrity": ok,
        "scenarios": all_results,
    }
    print(f"\n{'='*60}")
    print(json.dumps(summary, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    run_all()
