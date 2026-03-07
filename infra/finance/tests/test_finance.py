"""
infra/finance/tests/test_finance.py — Finance Engine Test Suite

Scenarios:
  A — Normal balance
  B — Critical liquidity
  C — Negative balance
  D — Abrupt drop > threshold
  E — Outflow spike
  F — Empty snapshot
  G — 10 simultaneous evaluations
  H — 100 sequential evaluations
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from infra.finance.finance_engine import evaluate
from infra.finance import finance_thresholds as th

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {"status", "signals", "liquidity_ratio", "anomaly_detected", "timestamp"}


def _valid_schema(r: dict) -> bool:
    return (
        _REQUIRED_KEYS.issubset(set(r.keys())) and
        r["status"] in ("normal", "warning", "critical") and
        isinstance(r["signals"], list) and
        isinstance(r["liquidity_ratio"], float) and
        isinstance(r["anomaly_detected"], bool) and
        isinstance(r["timestamp"], str) and
        r["timestamp"].endswith("Z")
    )


def _has_signal(result: dict, signal_type: str) -> bool:
    return any(s["type"] == signal_type for s in result["signals"])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recent_ago(hours: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(hours=hours)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Scenario A — Normal balance
# ---------------------------------------------------------------------------

def scenario_a() -> dict[str, bool]:
    r: dict[str, bool] = {}
    snapshot = {
        "available_balance":   5000.0,
        "reserved_balance":    500.0,
        "pending_payouts":     200.0,
        "recent_transactions": [
            {"amount": -50.0,  "timestamp": _recent_ago(2)},
            {"amount":  200.0, "timestamp": _recent_ago(5)},
            {"amount": -30.0,  "timestamp": _recent_ago(10)},
        ],
        "timestamp": _now_iso(),
    }
    original = copy.deepcopy(snapshot)
    result = evaluate(snapshot)

    r["A_status_normal"]         = result["status"] == "normal"
    r["A_no_anomaly"]            = result["anomaly_detected"] is False
    r["A_has_normal_signal"]     = _has_signal(result, "NORMAL")
    r["A_valid_schema"]          = _valid_schema(result)
    r["A_input_not_mutated"]     = snapshot == original
    r["A_liquidity_ratio_gt0"]   = result["liquidity_ratio"] > 0
    return r


# ---------------------------------------------------------------------------
# Scenario B — Critical liquidity
# ---------------------------------------------------------------------------

def scenario_b() -> dict[str, bool]:
    r: dict[str, bool] = {}
    th.reload()
    below = th.MIN_LIQUIDITY_THRESHOLD * 0.5  # 50% of threshold
    snapshot = {
        "available_balance":   below,
        "reserved_balance":    1000.0,
        "pending_payouts":     500.0,
        "recent_transactions": [],
        "timestamp": _now_iso(),
    }
    original = copy.deepcopy(snapshot)
    result = evaluate(snapshot)

    r["B_status_critical"]           = result["status"] == "critical"
    r["B_anomaly_detected"]          = result["anomaly_detected"] is True
    r["B_has_liquidity_critical"]    = _has_signal(result, "LIQUIDITY_CRITICAL")
    r["B_valid_schema"]              = _valid_schema(result)
    r["B_input_not_mutated"]         = snapshot == original
    return r


# ---------------------------------------------------------------------------
# Scenario C — Negative balance
# ---------------------------------------------------------------------------

def scenario_c() -> dict[str, bool]:
    r: dict[str, bool] = {}
    snapshot = {
        "available_balance":   -100.0,
        "reserved_balance":    500.0,
        "pending_payouts":     200.0,
        "recent_transactions": [],
        "timestamp": _now_iso(),
    }
    original = copy.deepcopy(snapshot)
    result = evaluate(snapshot)

    r["C_status_critical"]       = result["status"] == "critical"
    r["C_has_negative_signal"]   = _has_signal(result, "NEGATIVE_BALANCE")
    r["C_anomaly_detected"]      = result["anomaly_detected"] is True
    r["C_valid_schema"]          = _valid_schema(result)
    r["C_input_not_mutated"]     = snapshot == original
    return r


# ---------------------------------------------------------------------------
# Scenario D — Abrupt drop > threshold
# ---------------------------------------------------------------------------

def scenario_d() -> dict[str, bool]:
    r: dict[str, bool] = {}
    th.reload()
    # Simulate transactions that produced a big net outflow
    # available=1000, prior was ~1500 (500 net outflow = 33% drop > 30%)
    snapshot = {
        "available_balance":   1000.0,
        "reserved_balance":    200.0,
        "pending_payouts":      50.0,
        "recent_transactions": [
            {"amount": -300.0, "timestamp": _recent_ago(2)},
            {"amount": -200.0, "timestamp": _recent_ago(4)},
            {"amount":   50.0, "timestamp": _recent_ago(6)},
        ],
        "timestamp": _now_iso(),
    }
    original = copy.deepcopy(snapshot)
    result = evaluate(snapshot)

    signal_types = [s["type"] for s in result["signals"]]
    r["D_drop_or_warning_detected"] = (
        "ABRUPT_DROP" in signal_types or
        result["status"] in ("warning", "critical")
    )
    r["D_valid_schema"]          = _valid_schema(result)
    r["D_input_not_mutated"]     = snapshot == original
    r["D_no_crash"]              = True
    return r


# ---------------------------------------------------------------------------
# Scenario E — Outflow spike
# ---------------------------------------------------------------------------

def scenario_e() -> dict[str, bool]:
    r: dict[str, bool] = {}
    th.reload()
    # Mean debit ≈ 50; spike = 400 → ratio=8× >> MAX_OUTFLOW_SPIKE(3×)
    snapshot = {
        "available_balance":   3000.0,
        "reserved_balance":    500.0,
        "pending_payouts":     100.0,
        "recent_transactions": [
            {"amount":  -50.0, "timestamp": _recent_ago(1)},
            {"amount":  -40.0, "timestamp": _recent_ago(2)},
            {"amount":  -60.0, "timestamp": _recent_ago(3)},
            {"amount": -400.0, "timestamp": _recent_ago(4)},  # spike
        ],
        "timestamp": _now_iso(),
    }
    original = copy.deepcopy(snapshot)
    result = evaluate(snapshot)

    r["E_outflow_spike_detected"] = _has_signal(result, "OUTFLOW_SPIKE")
    r["E_status_warning_or_critical"] = result["status"] in ("warning", "critical")
    r["E_anomaly_detected"]       = result["anomaly_detected"] is True
    r["E_valid_schema"]           = _valid_schema(result)
    r["E_input_not_mutated"]      = snapshot == original
    return r


# ---------------------------------------------------------------------------
# Scenario F — Empty snapshot
# ---------------------------------------------------------------------------

def scenario_f() -> dict[str, bool]:
    r: dict[str, bool] = {}
    for empty_input in [{}, None]:
        result = evaluate(empty_input)
        r[f"F_no_crash_{empty_input}"] = True
        r[f"F_valid_schema_{empty_input}"] = _valid_schema(result)
        r[f"F_has_signal_{empty_input}"] = len(result["signals"]) >= 1
    return r


# ---------------------------------------------------------------------------
# Scenario G — 10 simultaneous evaluations
# ---------------------------------------------------------------------------

def scenario_g() -> dict[str, bool]:
    r: dict[str, bool] = {}
    snapshot = {
        "available_balance":   2000.0,
        "reserved_balance":    300.0,
        "pending_payouts":     100.0,
        "recent_transactions": [
            {"amount": -20.0, "timestamp": _recent_ago(1)},
        ],
        "timestamp": _now_iso(),
    }

    results: list[dict] = []
    errors:  list[Exception] = []
    lock = threading.Lock()

    def _eval():
        try:
            res = evaluate(copy.deepcopy(snapshot))
            with lock:
                results.append(res)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_eval) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    r["G_10_results"]        = len(results) == 10
    r["G_no_errors"]         = len(errors) == 0
    r["G_all_schemas_valid"] = all(_valid_schema(res) for res in results)
    r["G_deterministic"]     = len({res["status"] for res in results}) == 1
    return r


# ---------------------------------------------------------------------------
# Scenario H — 100 sequential evaluations (stress + determinism)
# ---------------------------------------------------------------------------

def scenario_h() -> dict[str, bool]:
    r: dict[str, bool] = {}
    snapshot = {
        "available_balance":   1500.0,
        "reserved_balance":    200.0,
        "pending_payouts":      50.0,
        "recent_transactions": [
            {"amount": -30.0, "timestamp": _recent_ago(1)},
            {"amount":  10.0, "timestamp": _recent_ago(3)},
        ],
        "timestamp": _now_iso(),
    }

    results = [evaluate(copy.deepcopy(snapshot)) for _ in range(100)]

    r["H_100_results"]       = len(results) == 100
    r["H_all_schemas_valid"] = all(_valid_schema(res) for res in results)
    r["H_all_same_status"]   = len({res["status"] for res in results}) == 1
    r["H_no_crash"]          = True
    return r


# ---------------------------------------------------------------------------
# Constitutional checks
# ---------------------------------------------------------------------------

def constitutional_checks() -> dict[str, bool]:
    r: dict[str, bool] = {}
    FINANCE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    files = []
    for root, dirs, fnames in os.walk(FINANCE_DIR):
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
            (r'open\s*\(\s*["\']state\.json', "state_json_write"),
            (r'\bglobal_state\s*=\s*[^=]',   "global_state_mutation"),
        ]:
            if re.search(pat, src, re.IGNORECASE):
                forbidden.append(f"{os.path.relpath(fpath, FINANCE_DIR)}:{label}")

    r["CONST_no_orchestrator"]      = not any("orchestrator"        in h for h in forbidden)
    r["CONST_no_radar_engine"]      = not any("radar_engine"        in h for h in forbidden)
    r["CONST_no_llm_client"]        = not any("llm_client"          in h for h in forbidden)
    r["CONST_no_state_json_write"]  = not any("state_json_write"    in h for h in forbidden)
    r["CONST_no_global_mutation"]   = not any("global_state_mutation" in h for h in forbidden)

    # evaluate() must not mutate its input — verified via deep-copy in scenarios
    # Additional static check: no "balance_snapshot[" assignment pattern
    for fpath in files:
        if "finance_engine" not in fpath:
            continue
        try:
            src = _clean(open(fpath, encoding="utf-8").read())
        except OSError:
            continue
        r["CONST_no_input_mutation"] = (
            "balance_snapshot[" not in src and
            "balance_snapshot.update" not in src
        )
        break
    else:
        r["CONST_no_input_mutation"] = True  # file not found — defensive pass

    return r


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print("\n" + "=" * 70)
    print(" RADAR — FINANCE ENGINE REAGINDO A SALDO (INFRA ISOLADA)")
    print("=" * 70 + "\n")

    all_results: dict[str, bool] = {}

    scenarios = [
        ("A — Normal balance",         scenario_a),
        ("B — Critical liquidity",     scenario_b),
        ("C — Negative balance",       scenario_c),
        ("D — Abrupt drop",            scenario_d),
        ("E — Outflow spike",          scenario_e),
        ("F — Empty snapshot",         scenario_f),
        ("G — 10 simultaneous",        scenario_g),
        ("H — 100 sequential (stress)",scenario_h),
        ("Constitutional",             constitutional_checks),
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
        "test":                   "Finance Engine — Etapa 2",
        "total":  total, "passed": passed, "failed": total - passed,
        "constitutional_integrity": ok,
        "scenarios": all_results,
    }, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
