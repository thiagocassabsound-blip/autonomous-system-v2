"""
api/routes/dashboard_routes.py — Operational HTML dashboard.

Implements Block 1 Dashboard Foundation.
Read-only. UI + session + state access only.
No engine modifications. No state writes.
"""
import os
from datetime import datetime, timezone, timedelta
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
            flash("Credenciais inválidas. Acesso negado.")
            
    return render_template("login.html")

@dashboard_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("dashboard_routes.login"))


@dashboard_bp.route("/dashboard", methods=["GET"])
def dashboard():
    """Simplified system dashboard entry point."""
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
        
    # Read from cache
    data = dashboard_state.get_data()
    mode = dashboard_state.mode
    
    return render_template(
        "dashboard.html",
        section="overview",
        **_get_base_context(data)
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
    """Helper to get base template context, ensuring all required keys exist."""
    last_ts = data.get("last_updated", 0)
    last_updated_str = datetime.fromtimestamp(last_ts, tz=timezone.utc).astimezone(timezone(timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S BRT")
    
    # Defensive data extraction
    budget = data.get("budget", {})
    evals_list = data.get("evaluations", [])
    products_raw = data.get("products", {})
    
    # Standardize eval/draft lists
    latest_evals = list(reversed(evals_list[-10:]))
    prod_vals = [p for p in products_raw.values() if isinstance(p, dict)]
    prod_vals.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    latest_drafts = prod_vals[:10]

    # Defensive counts
    total_evals = len(evals_list)
    total_drafts = len(prod_vals)

    # Status & Alerts
    system_status = data.get("global_state", {}).get("state", "UNKNOWN")
    error_alerts = []
    if system_status == "UNKNOWN":
        error_alerts.append("Motor de Estado indisponível - Falha na leitura de persistência.")

    return {
        "system_status": system_status,
        "mode": dashboard_state.mode,
        "username": session.get("username"),
        "last_updated": last_updated_str,
        "total_evals": total_evals,
        "total_drafts": total_drafts,
        "budget_calls": budget.get("calls_today", 0),
        "budget_max": budget.get("max_calls_per_day", 100),
        "budget_cost": f"{float(budget.get('cost_today_usd') or 0.0):.2f}",
        "evals": latest_evals,
        "products": latest_drafts,
        "analytics": data.get("analytics", {}),
        "ai_decisions": data.get("ai_decisions", []),
        "budget_data": budget,
        "error_alerts": error_alerts
    }


@dashboard_bp.route("/dashboard/api/refresh", methods=["POST"])
def refresh_data():
    """Forces cache refresh and redirects back."""
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
        
    dashboard_state.refresh_cache(force=True)
    return redirect(request.referrer or url_for("dashboard_routes.dashboard"))


@dashboard_bp.route("/dashboard/api/toggle_mock", methods=["POST"])
def toggle_mock():
    """Toggles MOCK/REAL mode."""
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
        
    dashboard_state.toggle_mode()
    return redirect(request.referrer or url_for("dashboard_routes.dashboard"))

@dashboard_bp.route("/dashboard/api/debug_paths", methods=["GET"])
def debug_paths():
    """Debug routine to inspect server-side paths and file existence."""
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    
    from core.dashboard_state_manager import PROJECT_ROOT, PERSISTENCE_DIR
    import os
    
    paths_to_check = dashboard_state.paths
    existence = {name: os.path.exists(path) for name, path in paths_to_check.items()}
    
    debug_info = {
        "PROJECT_ROOT": PROJECT_ROOT,
        "PERSISTENCE_DIR": PERSISTENCE_DIR,
        "cwd": os.getcwd(),
        "paths": paths_to_check,
        "existence": existence,
        "cache_sample": dashboard_state.get_data().get("global_state")
    }
    return debug_info


