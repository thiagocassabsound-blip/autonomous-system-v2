"""
infra/guardian/guardian_engine.py — Isolated Guardian Evaluation Engine.

Constitutional guarantees:
  • Never modifies input signals list
  • Never raises unhandled exceptions
  • Never calls Orchestrator
  • Never writes to any file or state
  • No Radar / LLM / Finance dependency (consumes their signals as plain dicts)
  • Thread-safe (pure functions, no shared mutable state)
  • Deterministic: same input → same output
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone

from infra.guardian.guardian_rules import SignalCounts, apply_rules

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"

_VALID_SEVERITIES = frozenset({"info", "warning", "critical"})


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime(_ISO_FMT)


def _normalize_severity(raw: object) -> str:
    """Coerce any severity value to a known level. Unknown → 'info'."""
    s = str(raw).lower().strip() if raw is not None else ""
    return s if s in _VALID_SEVERITIES else "info"


def _count_signals(signals: list[dict]) -> SignalCounts:
    critical = warning = info = 0
    for sig in signals:
        sev = _normalize_severity(sig.get("severity"))
        if sev == "critical":
            critical += 1
        elif sev == "warning":
            warning += 1
        else:
            info += 1
    return SignalCounts(
        total=len(signals),
        critical=critical,
        warning=warning,
        info=info,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(signals: list[dict]) -> dict:
    """
    Evaluate a list of risk signals and return a structured Guardian decision.

    Args:
        signals: list of dicts, each with at least:
            type      : str
            severity  : "info" | "warning" | "critical"
            source    : str (e.g. "finance", "radar", "llm", "external")
            timestamp : str (ISO-8601)

    Returns:
        {
          status               : "normal" | "monitor" | "block_soft" | "block_hard",
          aggregated_severity  : "low" | "medium" | "high",
          signals_analyzed     : int,
          decision_reason      : str,
          timestamp            : str (ISO-8601 UTC),
        }

    Never raises. Never mutates the input list.
    """
    try:
        # Defensive: work on a deep copy so we never touch caller's data
        safe_signals: list[dict] = copy.deepcopy(signals) if signals else []
        if not isinstance(safe_signals, list):
            safe_signals = []

        counts   = _count_signals(safe_signals)
        decision = apply_rules(counts)

        return {
            **decision.to_dict(),
            "timestamp": _now_utc(),
        }

    except Exception as exc:
        # Last-resort safety net
        return {
            "status":              "block_hard",
            "aggregated_severity": "high",
            "signals_analyzed":    0,
            "decision_reason":     f"Guardian evaluation error: {exc}",
            "timestamp":           _now_utc(),
        }
