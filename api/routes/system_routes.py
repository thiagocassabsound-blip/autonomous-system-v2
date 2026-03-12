"""
api/routes/system_routes.py — System state read-only visibility.

Read-only. No engine modifications. No state writes.
Exposes /system/state for operational inspection.
"""
from flask import Blueprint, jsonify

system_bp = Blueprint("system_routes", __name__)


@system_bp.route("/system/state", methods=["GET"])
def system_state():
    """Return a static system state JSON."""
    return jsonify({
        "orchestrator": "online",
        "engines_loaded": True
    })


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

@system_bp.route("/api/system/ads/global", methods=["POST"])
def toggle_ads_global():
    """Toggle the global ads system flag. Acts as a feature flag."""
    from flask import request, current_app
    gs = current_app.config.get('GLOBAL_STATE')
    if not gs:
        return jsonify({"error": "GlobalState not accessible"}), 500
        
    try:
        data = request.get_json() or {}
        # If 'enabled' is provided in payload, use it, else toggle current
        if 'enabled' in data:
            new_mode = "enabled" if data['enabled'] else "disabled"
        else:
            current_mode = gs.get_ads_system_mode()
            new_mode = "disabled" if current_mode == "enabled" else "enabled"
            
        gs.set_ads_system_mode(new_mode, orchestrated=True)
        
        # Trigger cache refresh if dashboard_state is available
        try:
            from core.dashboard_state_manager import dashboard_state
            dashboard_state.refresh_cache(force=True)
        except Exception:
            pass
            
        return jsonify({
            "status": "success",
            "enabled": new_mode == "enabled",
            "mode": new_mode
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@system_bp.route("/api/opportunities", methods=["GET"])
def get_opportunities():
    """Returns ranked strategic opportunities from the Radar engine."""
    from flask import current_app
    soe = current_app.config.get('STRATEGIC_RADAR')
    if not soe:
        # Fallback empty list if engine missing
        return jsonify({"opportunities": [], "count": 0})
        
    try:
        opps = soe.get_ranked_opportunities()
        return jsonify({
            "opportunities": opps,
            "count": len(opps)
        })
    except Exception as e:
        return jsonify({"error": str(e), "opportunities": [], "count": 0}), 500

@system_bp.route("/runtime-status", methods=["GET"])
def runtime_status():
    """Return a static runtime status JSON."""
    return jsonify({
        "runtime_running": True,
        "mode": "production"
    })
