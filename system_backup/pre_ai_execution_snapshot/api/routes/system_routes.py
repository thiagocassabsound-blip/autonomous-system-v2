"""
api/routes/system_routes.py — System state read-only visibility.

Read-only. No engine modifications. No state writes.
Exposes /system/state for operational inspection.
"""
from flask import Blueprint, jsonify

system_bp = Blueprint("system_routes", __name__)


@system_bp.route("/system/state", methods=["GET"])
def system_state():
    """
    Return a safe read-only view of the current system state.
    Uses the orchestrator registered in the Flask app config.
    Falls back to an empty dict if orchestrator is unavailable.
    """
    from flask import current_app
    orchestrator = current_app.config.get("ORCHESTRATOR")

    state: dict = {}
    if orchestrator is not None:
        try:
            # Orchestrator.state is a read-only property returning the StateManager proxy
            state = dict(orchestrator.state) if orchestrator.state else {}
        except Exception:
            state = {}

    return jsonify({"state": state})


@system_bp.route("/system/budget", methods=["GET"])
def system_budget():
    """Return current LLM budget status (calls and cost today)."""
    try:
        from infra.llm import llm_budget_guard
        return jsonify(llm_budget_guard.get_status())
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@system_bp.route("/system/health", methods=["GET"])
def system_health_detail():
    """Return last activity timestamps for all monitored components."""
    try:
        from infra.system import health_monitor
        with health_monitor._lock:
            activity = {
                k: v.isoformat() if v else None
                for k, v in health_monitor._last_activity.items()
            }
        return jsonify({"components": activity})
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
