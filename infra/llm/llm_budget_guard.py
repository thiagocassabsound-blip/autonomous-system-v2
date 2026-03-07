"""
infra/llm/llm_budget_guard.py — Daily LLM budget enforcement for Etapa 2.6.

Tracks per-day call count and estimated cost.
Blocks LLM execution when daily limits are exceeded.

Persistence (Etapa 2.6 fix):
  State is saved to infra/llm/llm_budget_state.json after every register_call().
  On restart, counters are restored from disk if the date still matches today.
  This prevents the daily limit from being bypassed by restarting the system.

Constitutional guarantees:
  - No state.json access
  - No StateMachine calls
  - Emits llm_budget_exceeded_event via receive_event() when blocking
  - Thread-safe — module-level lock
  - Never raises — returns structured dict
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger("infra.llm.budget_guard")

# ── Configuration (env-configurable) ─────────────────────────────────────────
MAX_LLM_CALLS_PER_DAY = int(os.getenv("MAX_LLM_CALLS_PER_DAY", "100"))
MAX_LLM_COST_PER_DAY  = float(os.getenv("MAX_LLM_COST_PER_DAY", "5.0"))

# Estimated cost per call (USD) — conservative fallback when not provided by caller
_DEFAULT_COST_PER_CALL_USD = 0.01

# ── Persistence path ──────────────────────────────────────────────────────────
_STATE_PATH = Path(__file__).resolve().parent / "llm_budget_state.json"

# ── Module-level state ────────────────────────────────────────────────────────
_lock       = threading.Lock()
_calls_today: int   = 0
_cost_today:  float = 0.0
_day_key:     str   = ""   # "YYYY-MM-DD"
_state_loaded: bool = False  # load from disk at most once per process


def _load_state() -> None:
    """
    Load persisted counters from disk (called under lock, once per process).
    If the stored date matches today, restores _calls_today and _cost_today.
    If the date differs, counters stay at 0 (new day).
    Never raises.
    """
    global _calls_today, _cost_today, _day_key, _state_loaded
    if _state_loaded:
        return
    _state_loaded = True
    try:
        if _STATE_PATH.exists():
            data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            stored_date = data.get("date", "")
            today = date.today().isoformat()
            if stored_date == today:
                _calls_today = int(data.get("calls_today", 0))
                _cost_today  = float(data.get("cost_today", 0.0))
                _day_key     = today
                logger.info(
                    "[LLMBudget] State restored from disk: date=%s calls=%d cost=%.4f",
                    today, _calls_today, _cost_today,
                )
            else:
                # Persisted state is from a previous day — discard
                _day_key = today
                logger.info("[LLMBudget] Persisted state is from %s — resetting for %s",
                            stored_date, today)
    except Exception as exc:
        logger.warning("[LLMBudget] Could not load persisted state (non-fatal): %s", exc)


def _save_state() -> None:
    """
    Persist current counters to disk (called under lock after register_call).
    Never raises.
    """
    try:
        _STATE_PATH.write_text(
            json.dumps({
                "date":        _day_key,
                "calls_today": _calls_today,
                "cost_today":  round(_cost_today, 6),
            }, indent=2),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning("[LLMBudget] Could not save state to disk (non-fatal): %s", exc)


def _reset_if_new_day() -> None:
    """Reset counters if the calendar day has changed (called under lock)."""
    global _calls_today, _cost_today, _day_key
    _load_state()  # no-op after first call
    today = date.today().isoformat()
    if _day_key != today:
        _calls_today = 0
        _cost_today  = 0.0
        _day_key     = today
        logger.info("[LLMBudget] Daily counters reset for %s", today)


# ── Public API ────────────────────────────────────────────────────────────────

def check_budget(orchestrator=None) -> dict:
    """
    Check whether a new LLM call is within daily budget.

    Returns:
      {"allowed": True,  "reason": ""}                  — call may proceed
      {"allowed": False, "reason": str}                 — call blocked

    Emits llm_budget_exceeded_event via orchestrator.receive_event() when blocking.
    Never raises.
    """
    with _lock:
        _reset_if_new_day()
        calls = _calls_today
        cost  = _cost_today

    # Check call count
    if calls >= MAX_LLM_CALLS_PER_DAY:
        reason = (
            f"Daily call limit reached: {calls}/{MAX_LLM_CALLS_PER_DAY} calls"
        )
        logger.warning("[LLMBudget] BLOCKED calls=%d limit=%d",
                       calls, MAX_LLM_CALLS_PER_DAY)
        _emit_exceeded(reason, calls, cost, orchestrator)
        return {"allowed": False, "reason": reason}

    # Check cost
    if cost >= MAX_LLM_COST_PER_DAY:
        reason = (
            f"Daily cost limit reached: ${cost:.4f}/${MAX_LLM_COST_PER_DAY:.2f}"
        )
        logger.warning("[LLMBudget] BLOCKED cost=%.4f limit=%.2f", cost, MAX_LLM_COST_PER_DAY)
        _emit_exceeded(reason, calls, cost, orchestrator)
        return {"allowed": False, "reason": reason}

    logger.debug("[LLMBudget] Allowed. calls=%d cost=%.4f", calls, cost)
    return {"allowed": True, "reason": ""}


def register_call(cost_usd: float = _DEFAULT_COST_PER_CALL_USD) -> None:
    """
    Register a completed LLM call.
    Increments daily counters and persists state to disk.
    Handles day rollover automatically.
    """
    global _calls_today, _cost_today
    with _lock:
        _reset_if_new_day()
        _calls_today += 1
        _cost_today  += cost_usd
        _save_state()  # persist after every call (Etapa 2.6 fix)
    logger.debug("[LLMBudget] Registered call. calls_today=%d cost_today=%.4f",
                 _calls_today, _cost_today)


def get_status() -> dict:
    """Return current budget status (for monitoring/health checks)."""
    with _lock:
        _reset_if_new_day()
        return {
            "day":                 _day_key,
            "calls_today":         _calls_today,
            "cost_today_usd":      round(_cost_today, 4),
            "max_calls_per_day":   MAX_LLM_CALLS_PER_DAY,
            "max_cost_per_day_usd":MAX_LLM_COST_PER_DAY,
            "calls_remaining":     max(0, MAX_LLM_CALLS_PER_DAY - _calls_today),
            "cost_remaining_usd":  round(max(0.0, MAX_LLM_COST_PER_DAY - _cost_today), 4),
        }


def reset_for_testing() -> None:
    """Reset all counters AND persisted state. ONLY for use in tests."""
    global _calls_today, _cost_today, _day_key, _state_loaded
    with _lock:
        _calls_today  = 0
        _cost_today   = 0.0
        _day_key      = ""
        _state_loaded = False  # allow reload on next check
        # Delete persisted state so tests start clean
        try:
            if _STATE_PATH.exists():
                _STATE_PATH.unlink()
        except Exception:
            pass


def _emit_exceeded(reason: str, calls: int, cost: float, orchestrator) -> None:
    if orchestrator is None:
        return
    try:
        orchestrator.receive_event(
            event_type="llm_budget_exceeded_event",
            payload={
                "reason":           reason,
                "calls_today":      calls,
                "cost_today_usd":   round(cost, 4),
                "limit_calls":      MAX_LLM_CALLS_PER_DAY,
                "limit_cost_usd":   MAX_LLM_COST_PER_DAY,
                "timestamp":        datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        logger.error("[LLMBudget] Failed to emit budget_exceeded event: %s", exc)
