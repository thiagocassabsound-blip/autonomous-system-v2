"""
infra/guardian/tests/test_guardian.py — Guardian Engine Test Suite

Scenarios:
  A — Empty signals list
  B — Only info signals
  C — 1 warning signal
  D — 2 warning signals
  E — 1 critical signal
  F — Warning + critical mixed
  G — 10 mixed signals
  H — 100 sequential evaluations (stress + determinism)
  I — 10 simultaneous evaluations (thread-safety)
  + Constitutional checks (isolation)

Zero side-effects. No file writes. Thread-safe validation included.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
import threading
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from infra.guardian.guardian_engine import evaluate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "status", "aggregated_severity",
    "signals_analyzed", "decision_reason", "timestamp",
}
_VALID_STATUSES    = {"normal", "monitor", "block_soft", "block_hard"}
_VALID_SEVERITIES  = {"low", "medium", "high"}
_NOW_ISO           = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_schema(r: dict) -> bool:
    return (
        _REQUIRED_KEYS.issubset(set(r.keys())) and
        r["status"] in _VALID_STATUSES and
        r["aggregated_severity"] in _VALID_SEVERITIES and
        isinstance(r["signals_analyzed"], int) and r["signals_analyzed"] >= 0 and
        isinstance(r["decision_reason"], str) and len(r["decision_reason"]) > 0 and
        isinstance(r["timestamp"], str) and r["timestamp"].endswith("Z")
    )


def _sig(severity: str, source: str = "finance", sig_type: str = "TEST") -> dict:
    return {
        "type":      sig_type,
        "severity":  severity,
        "source":    source,
        "timestamp": _NOW_ISO,
    }


# ---------------------------------------------------------------------------
# Scenario A — Empty list
# ---------------------------------------------------------------------------

def scenario_a() -> dict[str, bool]:
    r: dict[str, bool] = {}
    for empty in [[], None]:
        result = evaluate(empty)
        r[f"A_no_crash_{empty}"]        = True
        r[f"A_status_normal_{empty}"]   = result["status"] == "normal"
        r[f"A_valid_schema_{empty}"]    = _valid_schema(result)
        r[f"A_signals_eq0_{empty}"]     = result["signals_analyzed"] == 0
    return r


# ---------------------------------------------------------------------------
# Scenario B — Only info signals
# ---------------------------------------------------------------------------

def scenario_b() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals  = [_sig("info") for _ in range(3)]
    original = copy.deepcopy(signals)
    result   = evaluate(signals)

    r["B_status_normal"]      = result["status"] == "normal"
    r["B_severity_low"]       = result["aggregated_severity"] == "low"
    r["B_signals_analyzed_3"] = result["signals_analyzed"] == 3
    r["B_valid_schema"]       = _valid_schema(result)
    r["B_input_not_mutated"]  = signals == original
    return r


# ---------------------------------------------------------------------------
# Scenario C — 1 warning
# ---------------------------------------------------------------------------

def scenario_c() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals  = [_sig("warning"), _sig("info")]
    original = copy.deepcopy(signals)
    result   = evaluate(signals)

    r["C_status_monitor"]    = result["status"] == "monitor"
    r["C_no_hard_block"]     = result["status"] != "block_hard"
    r["C_valid_schema"]      = _valid_schema(result)
    r["C_input_not_mutated"] = signals == original
    return r


# ---------------------------------------------------------------------------
# Scenario D — 2 warnings → block_soft
# ---------------------------------------------------------------------------

def scenario_d() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals  = [_sig("warning"), _sig("warning")]
    original = copy.deepcopy(signals)
    result   = evaluate(signals)

    r["D_status_block_soft"]  = result["status"] == "block_soft"
    r["D_severity_medium"]    = result["aggregated_severity"] == "medium"
    r["D_signals_2"]          = result["signals_analyzed"] == 2
    r["D_valid_schema"]       = _valid_schema(result)
    r["D_input_not_mutated"]  = signals == original
    return r


# ---------------------------------------------------------------------------
# Scenario E — 1 critical → block_hard
# ---------------------------------------------------------------------------

def scenario_e() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals  = [_sig("critical", source="finance", sig_type="LIQUIDITY_CRITICAL")]
    original = copy.deepcopy(signals)
    result   = evaluate(signals)

    r["E_status_block_hard"]  = result["status"] == "block_hard"
    r["E_severity_high"]      = result["aggregated_severity"] == "high"
    r["E_signals_1"]          = result["signals_analyzed"] == 1
    r["E_valid_schema"]       = _valid_schema(result)
    r["E_input_not_mutated"]  = signals == original
    return r


# ---------------------------------------------------------------------------
# Scenario F — warning + critical → block_hard (critical takes priority)
# ---------------------------------------------------------------------------

def scenario_f() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals  = [_sig("warning"), _sig("critical")]
    original = copy.deepcopy(signals)
    result   = evaluate(signals)

    r["F_status_block_hard"]  = result["status"] == "block_hard"
    r["F_severity_high"]      = result["aggregated_severity"] == "high"
    r["F_valid_schema"]       = _valid_schema(result)
    r["F_input_not_mutated"]  = signals == original
    return r


# ---------------------------------------------------------------------------
# Scenario G — 10 mixed signals
# ---------------------------------------------------------------------------

def scenario_g() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals = (
        [_sig("info")]     * 4 +
        [_sig("warning")]  * 3 +
        [_sig("critical")] * 3
    )
    original = copy.deepcopy(signals)
    result   = evaluate(signals)

    r["G_status_block_hard"]   = result["status"] == "block_hard"    # critical takes priority
    r["G_signals_analyzed_10"] = result["signals_analyzed"] == 10
    r["G_valid_schema"]        = _valid_schema(result)
    r["G_input_not_mutated"]   = signals == original
    r["G_no_crash"]            = True
    return r


# ---------------------------------------------------------------------------
# Scenario H — 100 sequential evaluations (stress + determinism)
# ---------------------------------------------------------------------------

def scenario_h() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals = [_sig("warning"), _sig("info")]

    results = [evaluate(copy.deepcopy(signals)) for _ in range(100)]

    r["H_100_results"]       = len(results) == 100
    r["H_all_schemas_valid"] = all(_valid_schema(res) for res in results)
    r["H_all_same_status"]   = len({res["status"] for res in results}) == 1
    r["H_deterministic"]     = len({res["aggregated_severity"] for res in results}) == 1
    r["H_no_crash"]          = True
    return r


# ---------------------------------------------------------------------------
# Scenario I — 10 simultaneous evaluations (thread-safety)
# ---------------------------------------------------------------------------

def scenario_i() -> dict[str, bool]:
    r: dict[str, bool] = {}
    signals = [_sig("warning"), _sig("critical")]
    results: list[dict] = []
    errors:  list[Exception] = []
    lock = threading.Lock()

    def _eval():
        try:
            res = evaluate(copy.deepcopy(signals))
            with lock:
                results.append(res)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_eval) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    r["I_10_results"]        = len(results) == 10
    r["I_no_errors"]         = len(errors) == 0
    r["I_all_schemas_valid"] = all(_valid_schema(res) for res in results)
    r["I_all_same_status"]   = len({res["status"] for res in results}) == 1
    r["I_no_crash"]          = True
    return r


# ---------------------------------------------------------------------------
# Constitutional checks
# ---------------------------------------------------------------------------

def constitutional_checks() -> dict[str, bool]:
    r: dict[str, bool] = {}
    GUARDIAN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    files = []
    for root, dirs, fnames in os.walk(GUARDIAN_DIR):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in fnames:
            if f.endswith(".py"):
                files.append(os.path.join(root, f))

    def _clean(src: str) -> str:
        return re.sub(
            r'(""".*?"""|\'\'\'.*?\'\'\'|"[^"\\]*(?:\\.[^"\\]*)*"|\'[^\'\\]*(?:\\.[^\'\\]*)*\'|#[^\n]*)',
            " ", src, flags=re.DOTALL,
        )

    forbidden: list[str] = []
    for fpath in files:
        try:
            src = _clean(open(fpath, encoding="utf-8").read())
        except OSError:
            continue
        for pat, label in [
            (r"\borchestrator\b",            "orchestrator"),
            (r"\bradar_engine\b",            "radar_engine"),
            (r"\bllm_client\b",              "llm_client"),
            (r"\bfinance_engine\b",          "finance_engine_import"),
            (r'open\s*\([^)]*["\']w["\']',  "file_write"),
            (r'\bglobal_state\s*=\s*[^=]',  "global_state_mutation"),
        ]:
            if re.search(pat, src, re.IGNORECASE):
                forbidden.append(f"{os.path.relpath(fpath, GUARDIAN_DIR)}:{label}")

    r["CONST_no_orchestrator"]      = not any("orchestrator"        in h for h in forbidden)
    r["CONST_no_radar"]             = not any("radar_engine"        in h for h in forbidden)
    r["CONST_no_llm_client"]        = not any("llm_client"          in h for h in forbidden)
    r["CONST_no_finance_import"]    = not any("finance_engine_import" in h for h in forbidden)
    r["CONST_no_file_writes"]       = not any("file_write"          in h for h in forbidden)
    r["CONST_no_global_mutation"]   = not any("global_state_mutation" in h for h in forbidden)

    # evaluate() must not mutate its input
    for fpath in files:
        if "guardian_engine" not in fpath:
            continue
        try:
            src = _clean(open(fpath, encoding="utf-8").read())
        except OSError:
            continue
        r["CONST_no_input_mutation"] = (
            "signals[" not in src and
            "signals.append" not in src and
            "signals.pop" not in src
        )
        break
    else:
        r["CONST_no_input_mutation"] = True

    return r


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 70)
    print(" RADAR — GUARDIAN REAGINDO A ALERTA (INFRA ISOLADA)")
    print("=" * 70 + "\n")

    all_results: dict[str, bool] = {}

    scenarios = [
        ("A — Empty signals",              scenario_a),
        ("B — Only info",                  scenario_b),
        ("C — 1 warning",                  scenario_c),
        ("D — 2 warnings → block_soft",    scenario_d),
        ("E — 1 critical → block_hard",    scenario_e),
        ("F — Warning + critical",         scenario_f),
        ("G — 10 mixed signals",           scenario_g),
        ("H — 100 sequential (stress)",    scenario_h),
        ("I — 10 simultaneous",            scenario_i),
        ("Constitutional",                 constitutional_checks),
    ]

    for label, fn in scenarios:
        try:
            res = fn()
        except Exception as exc:
            res = {f"{label[:1]}_CRASHED": False}
            print(f"  [FAIL] {label} — EXCEPTION: {exc}")
        passed = sum(1 for v in res.values() if v)
        total  = len(res)
        status = "PASS" if passed == total else "FAIL"
        print(f"  [{status}] {label} ({passed}/{total})")
        for k, v in res.items():
            if not v:
                print(f"       [FAIL] {k}")
        all_results.update(res)

    passed = sum(1 for v in all_results.values() if v)
    total  = len(all_results)
    ok     = passed == total

    print("\n" + "=" * 70)
    print(json.dumps({
        "test":                   "Guardian Engine — Etapa 2",
        "total":  total, "passed": passed, "failed": total - passed,
        "constitutional_integrity": ok,
        "scenarios": all_results,
    }, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
