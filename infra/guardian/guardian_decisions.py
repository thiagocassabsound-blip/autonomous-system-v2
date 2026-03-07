"""
infra/guardian/guardian_decisions.py — Decision type definitions and builders.

Decisions are pure immutable data. No logic, no side-effects.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Decision levels (from safest to most restrictive)
DecisionStatus = Literal["normal", "monitor", "block_soft", "block_hard"]

# Aggregated severity bands
AggregatedSeverity = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class GuardianDecision:
    """Immutable decision emitted by the Guardian engine."""
    status:               DecisionStatus
    aggregated_severity:  AggregatedSeverity
    signals_analyzed:     int
    decision_reason:      str

    def to_dict(self) -> dict:
        return {
            "status":              self.status,
            "aggregated_severity": self.aggregated_severity,
            "signals_analyzed":    self.signals_analyzed,
            "decision_reason":     self.decision_reason,
        }


# ---------------------------------------------------------------------------
# Decision constructors
# ---------------------------------------------------------------------------

def decision_normal(n: int) -> GuardianDecision:
    return GuardianDecision(
        status="normal",
        aggregated_severity="low",
        signals_analyzed=n,
        decision_reason="No warnings or critical signals detected. System operating normally.",
    )


def decision_monitor(n: int) -> GuardianDecision:
    return GuardianDecision(
        status="monitor",
        aggregated_severity="medium",
        signals_analyzed=n,
        decision_reason="Warning and info signals present. Monitoring elevated; no action required.",
    )


def decision_block_soft(n: int, warning_count: int) -> GuardianDecision:
    return GuardianDecision(
        status="block_soft",
        aggregated_severity="medium",
        signals_analyzed=n,
        decision_reason=(
            f"{warning_count} warning signal(s) detected. "
            "Soft block applied: non-critical operations suspended."
        ),
    )


def decision_block_hard(n: int, critical_count: int) -> GuardianDecision:
    return GuardianDecision(
        status="block_hard",
        aggregated_severity="high",
        signals_analyzed=n,
        decision_reason=(
            f"{critical_count} critical signal(s) detected. "
            "Hard block applied: all operations suspended pending resolution."
        ),
    )
