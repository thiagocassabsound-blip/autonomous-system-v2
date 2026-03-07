"""
infra/finance/finance_signals.py — Signal type definitions and builders.

Signals are pure data structures — no logic, no side-effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# Severity levels (ordered low → high)
Severity = Literal["info", "warning", "critical"]

# Signal type identifiers
SignalType = Literal[
    "NORMAL",
    "LIQUIDITY_CRITICAL",
    "NEGATIVE_BALANCE",
    "ABRUPT_DROP",
    "OUTFLOW_SPIKE",
]


@dataclass(frozen=True)
class FinanceSignal:
    """Immutable signal emitted by the Finance Engine."""
    type:     SignalType
    severity: Severity
    detail:   str = ""

    def to_dict(self) -> dict:
        return {
            "type":     self.type,
            "severity": self.severity,
            "detail":   self.detail,
        }


# ---------------------------------------------------------------------------
# Signal constructors
# ---------------------------------------------------------------------------

def signal_normal() -> FinanceSignal:
    return FinanceSignal(type="NORMAL", severity="info",
                         detail="Balance within normal parameters.")


def signal_liquidity_critical(available: float, threshold: float) -> FinanceSignal:
    return FinanceSignal(
        type="LIQUIDITY_CRITICAL", severity="critical",
        detail=f"Available balance {available:.2f} below threshold {threshold:.2f}.",
    )


def signal_negative_balance(available: float) -> FinanceSignal:
    return FinanceSignal(
        type="NEGATIVE_BALANCE", severity="critical",
        detail=f"Available balance is negative: {available:.2f}.",
    )


def signal_abrupt_drop(drop_pct: float, threshold_pct: float) -> FinanceSignal:
    return FinanceSignal(
        type="ABRUPT_DROP", severity="warning",
        detail=(
            f"Balance dropped {drop_pct:.1f}% which exceeds "
            f"threshold {threshold_pct:.1f}%."
        ),
    )


def signal_outflow_spike(spike_ratio: float, threshold: float) -> FinanceSignal:
    return FinanceSignal(
        type="OUTFLOW_SPIKE", severity="warning",
        detail=(
            f"Outflow spike ratio {spike_ratio:.2f}x "
            f"exceeds threshold {threshold:.2f}x."
        ),
    )
