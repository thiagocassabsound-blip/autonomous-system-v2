"""
api/routes/dashboard_routes.py — Operational HTML dashboard.

Implements Block 1 Dashboard Foundation.
Read-only. UI + session + state access only.
No engine modifications. No state writes.
"""
import os
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from core.dashboard_state_manager import dashboard_state

dashboard_bp = Blueprint(
    "dashboard_routes", 
    __name__,
    template_folder="../../templates"
)

@dashboard_bp.route("/login", methods=["GET", "POST"])
def login():
    # Read fresh from environment inside handler for robustness
    # Priority: ADMIN_USERNAME (NEW) -> DASHBOARD_USER (LEGACY) -> admin (FALLBACK)
    env_user = os.getenv("ADMIN_USERNAME") or os.getenv("DASHBOARD_USER", "admin")
    env_pass = os.getenv("ADMIN_PASSWORD") or os.getenv("DASHBOARD_PASSWORD", "admin")
    
    # Normalize comparison values
    target_user = env_user.strip().lower()
    target_pass = env_pass.strip()

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = (request.form.get("password") or "").strip()
        
        user_match = (username == target_user)
        pass_match = (password == target_pass)

        if user_match and pass_match:
            session["authenticated"] = True
            session["username"] = username
            return redirect(url_for("dashboard_routes.dashboard"))
        else:
            flash("Invalid credentials. Access denied.")
            
    return render_template("login.html")

@dashboard_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("dashboard_routes.login"))


@dashboard_bp.route("/debug/env")
def debug_env():
    # Only return specific auth keys for security
    keys = ["ADMIN_USERNAME", "ADMIN_PASSWORD", "DASHBOARD_USER", "DASHBOARD_PASSWORD"]
    info = {k: os.getenv(k) for k in keys}
    # Obfuscate password but show length and first/last char
    for k in info:
        if "PASSWORD" in k and info[k]:
            val = info[k]
            info[k] = f"{val[0]}...{val[-1]} (len={len(val)})"
    return info

@dashboard_bp.route("/dashboard", methods=["GET"])
def dashboard():
    """Simplified system dashboard entry point."""
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
        
    # Read from cache
    data = dashboard_state.get_data()
    mode = dashboard_state.mode
    
    global_s = data.get("global_state", {})
    system_status = global_s.get("state", "UNKNOWN")
    
    evals = data.get("evaluations", [])
    products_dict = data.get("products", {})
    budget = data.get("budget", {})
    last_ts_float = data.get("last_updated", 0)
    
    last_updated_str = datetime.fromtimestamp(last_ts_float, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Latest 10 eval history (descending)
    latest_evals = list(reversed(evals[-10:]))
    total_evals = len(evals)
    
    # Latest 10 product drafts 
    prod_vals = list(products_dict.values())
    prod_vals.sort(key=lambda x: x.get('created_at', ''), reverse=True)
    latest_drafts = prod_vals[:10]
    total_drafts = len(prod_vals)

    # Budget info
    budget_calls = budget.get("calls_today", 0)
    budget_max = budget.get("max_calls_per_day", 100)
    budget_cost = f"{budget.get('cost_today_usd', 0.0):.2f}"

    # Verify if integrations are "unavailable" based on global state tracking
    error_alerts = []
    if system_status == "UNKNOWN":
        error_alerts.append("State Engine unavailable - Persistence read failed.")

    return render_template(
        "dashboard.html",
        system_status=system_status,
        mode=mode,
        username=session.get("username"),
        last_updated=last_updated_str,
        total_evals=total_evals,
        total_drafts=total_drafts,
        budget_calls=budget_calls,
        budget_max=budget_max,
        budget_cost=budget_cost,
        evals=latest_evals,
        products=latest_drafts,
        error_alerts=error_alerts,
        section="overview"
    )

@dashboard_bp.route("/dashboard/radar", methods=["GET"])
def dashboard_radar():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    return render_template("dashboard.html", section="radar", evals=data.get("evaluations", []), **_get_base_context(data))

@dashboard_bp.route("/dashboard/opportunities", methods=["GET"])
def dashboard_opportunities():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    # Filter for recommendations
    recommendations = [e for e in data.get("evaluations", []) if e.get("recommended")]
    return render_template("dashboard.html", section="opportunities", recommendations=recommendations, **_get_base_context(data))

@dashboard_bp.route("/dashboard/products", methods=["GET"])
def dashboard_products():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    return render_template("dashboard.html", section="products", products=list(data.get("products", {}).values()), **_get_base_context(data))

@dashboard_bp.route("/dashboard/analytics", methods=["GET"])
def dashboard_analytics():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    return render_template("dashboard.html", section="analytics", **_get_base_context(data))

@dashboard_bp.route("/dashboard/settings", methods=["GET"])
def dashboard_settings():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    return render_template("dashboard.html", section="settings", **_get_base_context(data))

def _get_base_context(data):
    """Helper to get base template context."""
    last_ts = data.get("last_updated", 0)
    last_updated_str = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    budget = data.get("budget", {})
    return {
        "system_status": data.get("global_state", {}).get("state", "UNKNOWN"),
        "mode": dashboard_state.mode,
        "username": session.get("username"),
        "last_updated": last_updated_str,
        "total_evals": len(data.get("evaluations", [])),
        "total_drafts": len(data.get("products", {})),
        "budget_calls": budget.get("calls_today", 0),
        "budget_max": budget.get("max_calls_per_day", 100),
        "budget_cost": f"{budget.get('cost_today_usd', 0.0):.2f}",
        "error_alerts": []
    }


@dashboard_bp.route("/dashboard/api/refresh", methods=["POST"])
def refresh_data():
    """Forces cache refresh and redirects back."""
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
        
    dashboard_state.force_refresh()
    return redirect(url_for("dashboard_routes.dashboard"))


@dashboard_bp.route("/dashboard/api/toggle_mock", methods=["POST"])
def toggle_mock():
    """Toggles MOCK/REAL mode."""
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
        
    dashboard_state.toggle_mode()
    return redirect(url_for("dashboard_routes.dashboard"))


