"""
infra/system/health_monitor.py — System health monitoring for Etapa 2.6.

Tracks last-activity timestamps for 5 core service components.
Emits system_component_stalled_event when a component exceeds the timeout.

Constitutional guarantees:
  - No state.json access
  - No StateMachine calls
  - Events via orchestrator.receive_event()
  - Thread-safe
  - Never raises
"""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("infra.system.health_monitor")

# ── Configuration ─────────────────────────────────────────────────────────────
SERVICE_TIMEOUT_HOURS = float(os.getenv("SERVICE_TIMEOUT_HOURS", "12"))

# ── Monitored components ──────────────────────────────────────────────────────
MONITORED_COMPONENTS = (
    "radar",
    "llm",
    "webhook",
    "finance",
    "guardian",
)

# ── Module-level state ────────────────────────────────────────────────────────
# {component_name: datetime (UTC)}
_last_activity: dict[str, Optional[datetime]] = {c: None for c in MONITORED_COMPONENTS}
_lock = threading.Lock()


# ── Public API ────────────────────────────────────────────────────────────────

def update_component(name: str) -> None:
    """
    Record that a component is alive.

    Called by external modules (e.g., radar after a cycle, llm after a call).
    """
    if name not in _last_activity:
        logger.warning("[HealthMonitor] Unknown component '%s' — not tracked.", name)
        return
    with _lock:
        _last_activity[name] = datetime.now(timezone.utc)
    logger.debug("[HealthMonitor] Activity updated: component=%s", name)


def run_health_check(orchestrator) -> list[str]:
    """
    Check all monitored components for staleness.

    For each stalled component: emits system_component_stalled_event.

    Returns list of stalled component names.
    Never raises.
    """
    stalled = []
    now = datetime.now(timezone.utc)
    timeout_seconds = SERVICE_TIMEOUT_HOURS * 3600

    with _lock:
        snapshot = dict(_last_activity)

    for component, last in snapshot.items():
        if last is None:
            # Never updated — treat as stalled only if called after bootstrap grace period
            # (we don't stall on None so as not to trigger on fresh starts)
            logger.debug("[HealthMonitor] Component %s has no activity yet — skipping", component)
            continue

        elapsed_seconds = (now - last).total_seconds()
        elapsed_hours   = elapsed_seconds / 3600

        if elapsed_seconds > timeout_seconds:
            stalled.append(component)
            logger.warning(
                "[HealthMonitor] STALLED component=%s last_activity=%.1fh ago (threshold=%.1fh)",
                component, elapsed_hours, SERVICE_TIMEOUT_HOURS,
            )
            _emit_stalled(component, elapsed_hours, orchestrator)
        else:
            logger.debug(
                "[HealthMonitor] OK component=%s last_activity=%.1fh ago",
                component, elapsed_hours,
            )

    return stalled


def get_status() -> dict:
    """Return current health status for all components."""
    now = datetime.now(timezone.utc)
    status = {}
    with _lock:
        for comp, last in _last_activity.items():
            if last is None:
                status[comp] = {"last_activity": None, "elapsed_hours": None, "stalled": False}
            else:
                elapsed = (now - last).total_seconds() / 3600
                status[comp] = {
                    "last_activity": last.isoformat(),
                    "elapsed_hours": round(elapsed, 2),
                    "stalled":       elapsed > SERVICE_TIMEOUT_HOURS,
                }
    return status


def reset_for_testing() -> None:
    """Reset all activity records. ONLY for use in tests."""
    with _lock:
        for key in _last_activity:
            _last_activity[key] = None


def _emit_stalled(component: str, elapsed_hours: float, orchestrator) -> None:
    if orchestrator is None:
        return
    try:
        orchestrator.receive_event(
            event_type="system_component_stalled_event",
            payload={
                "component":     component,
                "elapsed_hours": round(elapsed_hours, 2),
                "threshold_hours": SERVICE_TIMEOUT_HOURS,
                "timestamp":     datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        logger.error("[HealthMonitor] Failed to emit stalled event for %s: %s",
                     component, exc)
