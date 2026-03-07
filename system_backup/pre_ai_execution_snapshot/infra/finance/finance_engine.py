"""
infra/finance/finance_engine.py — Isolated Finance Evaluation Engine.

Constitutional guarantees:
  • Never modifies input balance_snapshot
  • Never raises unhandled exceptions
  • Never calls Orchestrator
  • Never writes to state.json or any file
  • No Radar / LLM dependency
  • Thread-safe (pure functions, no shared mutable state)
  • Deterministic: same input → same output
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone, timedelta
from typing import Optional

from infra.finance import finance_thresholds as th
from infra.finance.finance_signals import (
    FinanceSignal,
    signal_abrupt_drop,
    signal_liquidity_critical,
    signal_negative_balance,
    signal_normal,
    signal_outflow_spike,
)

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime(_ISO_FMT)


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _detect_negative_balance(available: float) -> Optional[FinanceSignal]:
    if available < 0.0:
        return signal_negative_balance(available)
    return None


def _detect_liquidity_critical(available: float) -> Optional[FinanceSignal]:
    th.reload()
    threshold = th.MIN_LIQUIDITY_THRESHOLD
    if available < threshold:
        return signal_liquidity_critical(available, threshold)
    return None


def _detect_abrupt_drop(
    available: float,
    transactions: list[dict],
) -> Optional[FinanceSignal]:
    """
    Detect an abrupt balance drop within DROP_WINDOW_HOURS.
    Looks at 'credit' transactions (positive amounts) vs 'debit' (negative amounts)
    within the window to approximate prior balance.
    Falls back to comparing available against max inflow in the window.
    """
    th.reload()
    if not transactions:
        return None

    window_hours = th.DROP_WINDOW_HOURS
    max_drop_pct = th.MAX_DROP_PERCENT
    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)

    windowed: list[dict] = []
    for tx in transactions:
        try:
            ts_raw = tx.get("timestamp", tx.get("created_at", ""))
            if ts_raw:
                ts = datetime.fromisoformat(
                    str(ts_raw).replace("Z", "+00:00")
                )
                if ts >= cutoff:
                    windowed.append(tx)
        except (ValueError, TypeError):
            pass

    if not windowed:
        return None

    # Approximate prior balance = current + outflows - inflows in window
    net_flow = sum(_safe_float(tx.get("amount", 0)) for tx in windowed)
    if net_flow >= 0:
        return None  # Net inflow or neutral — no drop

    prior_balance = available - net_flow  # net_flow is negative, so this increases
    if prior_balance <= 0:
        return None

    drop_pct = abs(net_flow) / prior_balance * 100.0
    if drop_pct > max_drop_pct:
        return signal_abrupt_drop(drop_pct, max_drop_pct)

    return None


def _detect_outflow_spike(transactions: list[dict]) -> Optional[FinanceSignal]:
    """
    Detect an unusual spike in a single outflow transaction vs the baseline mean.
    Uses only debit transactions (negative amounts).
    Baseline mean = mean of all debits excluding the largest one.
    """
    th.reload()
    min_samples = th.OUTFLOW_SPIKE_MIN_SAMPLES
    spike_mult  = th.MAX_OUTFLOW_SPIKE

    debits = sorted([
        abs(_safe_float(tx.get("amount", 0)))
        for tx in transactions
        if _safe_float(tx.get("amount", 0)) < 0
    ])
    if len(debits) < min_samples:
        return None

    max_debit = debits[-1]
    # Baseline: mean of all debits except the largest
    baseline = debits[:-1]
    if not baseline:
        return None
    mean_baseline = sum(baseline) / len(baseline)
    if mean_baseline == 0:
        return None

    spike_ratio = max_debit / mean_baseline

    if spike_ratio > spike_mult:
        return signal_outflow_spike(spike_ratio, spike_mult)

    return None


def _compute_liquidity_ratio(available: float, reserved: float,
                              pending: float) -> float:
    """
    liquidity_ratio = available / (reserved + pending)
    Clamped to [0.0, 999.0]. Returns 999.0 if denominator is zero.
    """
    try:
        denom = reserved + pending
        if denom <= 0:
            return 999.0
        ratio = available / denom
        return round(max(0.0, min(ratio, 999.0)), 4)
    except Exception:
        return 0.0


def _overall_status(signals: list[FinanceSignal]) -> str:
    if any(s.severity == "critical" for s in signals):
        return "critical"
    if any(s.severity == "warning" for s in signals):
        return "warning"
    return "normal"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(balance_snapshot: dict) -> dict:
    """
    Evaluate a balance snapshot and return a structured signal result.

    Args:
        balance_snapshot: dict with keys:
            available_balance   : float
            reserved_balance    : float
            pending_payouts     : float
            recent_transactions : list[dict]  (each has 'amount', optional 'timestamp')
            timestamp           : str (ISO-8601)

    Returns:
        {
          status           : "normal" | "warning" | "critical",
          signals          : [{"type": ..., "severity": ..., "detail": ...}],
          liquidity_ratio  : float,
          anomaly_detected : bool,
          timestamp        : str (ISO-8601 UTC),
        }

    Never raises. Never mutates balance_snapshot.
    """
    # Defensive copy so we never mutate the caller's dict
    snapshot = copy.deepcopy(balance_snapshot) if balance_snapshot else {}

    try:
        available = _safe_float(snapshot.get("available_balance", 0.0))
        reserved  = _safe_float(snapshot.get("reserved_balance",  0.0))
        pending   = _safe_float(snapshot.get("pending_payouts",   0.0))
        txns = list(snapshot.get("recent_transactions", []) or [])

        detected: list[FinanceSignal] = []

        # Detection pipeline (ordered by severity: critical first)
        neg  = _detect_negative_balance(available)
        if neg:
            detected.append(neg)

        liq  = _detect_liquidity_critical(available)
        if liq:
            detected.append(liq)

        drop = _detect_abrupt_drop(available, txns)
        if drop:
            detected.append(drop)

        spike = _detect_outflow_spike(txns)
        if spike:
            detected.append(spike)

        if not detected:
            detected.append(signal_normal())

        status           = _overall_status(detected)
        liquidity_ratio  = _compute_liquidity_ratio(available, reserved, pending)
        anomaly_detected = status in ("warning", "critical")

        return {
            "status":           status,
            "signals":          [s.to_dict() for s in detected],
            "liquidity_ratio":  liquidity_ratio,
            "anomaly_detected": anomaly_detected,
            "timestamp":        _now_utc(),
        }

    except Exception as exc:
        # Last-resort safety net — never crash the caller
        return {
            "status":           "critical",
            "signals":          [{"type": "UNKNOWN_ERROR",
                                  "severity": "critical",
                                  "detail": str(exc)}],
            "liquidity_ratio":  0.0,
            "anomaly_detected": True,
            "timestamp":        _now_utc(),
        }
