"""
infra/guardian/guardian_rules.py — Rule definitions for the Guardian engine.

Rules are pure functions: (signal_counts) -> GuardianDecision.
Engine applies rules in priority order; first match wins.
No business logic lives in the engine itself.

Rule priority (highest → lowest):
  1. BLOCK_HARD  — any critical signal
  2. BLOCK_SOFT  — ≥2 warnings, no critical
  3. MONITOR     — ≥1 warning + ≥1 info, no critical
  4. NORMAL      — only info or empty
"""
from __future__ import annotations

from typing import NamedTuple

from infra.guardian.guardian_decisions import (
    GuardianDecision,
    decision_block_hard,
    decision_block_soft,
    decision_monitor,
    decision_normal,
)


class SignalCounts(NamedTuple):
    total:    int
    critical: int
    warning:  int
    info:     int


def apply_rules(counts: SignalCounts) -> GuardianDecision:
    """
    Apply guardian rules in priority order and return the first matching decision.

    Rules:
      A) ≥1 critical                         → BLOCK_HARD
      B) ≥2 warnings (no critical)           → BLOCK_SOFT
      C) ≥1 warning AND ≥1 info (no critical)→ MONITOR
      D) ≥1 warning alone (no critical)      → MONITOR  (single warning = monitor)
      E) only info signals or empty           → NORMAL
    """
    n = counts.total

    # Rule A: any critical → hard block
    if counts.critical >= 1:
        return decision_block_hard(n, counts.critical)

    # Rule B: two or more warnings → soft block
    if counts.warning >= 2:
        return decision_block_soft(n, counts.warning)

    # Rule C/D: any warning (+ possibly info) → monitor
    if counts.warning >= 1:
        return decision_monitor(n)

    # Rule E: only info or empty → normal
    return decision_normal(n)
