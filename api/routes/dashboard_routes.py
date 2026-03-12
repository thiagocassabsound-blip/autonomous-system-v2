"""
api/routes/dashboard_routes.py — Operational HTML dashboard.

Implements Block 1 Dashboard Foundation.
Read-only. UI + session + state access only.
No engine modifications. No state writes.
"""
import os
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify, current_app
from core.dashboard_state_manager import dashboard_state
from infrastructure.logger import get_logger

logger = get_logger("DashboardAPI")

dashboard_bp = Blueprint(
    "dashboard_routes", 
    __name__,
    template_folder="../../templates",
    strict_slashes=False
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


@dashboard_bp.route("/dashboard", methods=["GET"], strict_slashes=False)
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
    # Base context already includes latest 10 'evals'. 
    # For the full radar page, we override with all evaluations explicitly.
    ctx = _get_base_context(data)
    ctx["evals"] = data.get("evaluations") or []
    return render_template("dashboard.html", section="radar", **ctx)

@dashboard_bp.route("/dashboard/opportunities", methods=["GET"])
def dashboard_opportunities():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    # Filter for recommendations
    recommendations = [e for e in (data.get("evaluations") or []) if isinstance(e, dict) and e.get("recommended")]
    ctx = _get_base_context(data)
    ctx["recommendations"] = recommendations
    return render_template("dashboard.html", section="opportunities", **ctx)

@dashboard_bp.route("/dashboard/products", methods=["GET"])
def dashboard_products():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    ctx = _get_base_context(data)
    
    products_raw = data.get("products") or {}
    # Filter out deleted products for the main view
    products_list = [p for p in products_raw.values() if isinstance(p, dict) and not p.get("deleted", False)]
    products_list.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    
    ctx["products"] = products_list
    return render_template("dashboard.html", section="products", **ctx)

@dashboard_bp.route("/dashboard/trash", methods=["GET"])
def dashboard_trash():
    if not session.get("authenticated"):
        return redirect(url_for("dashboard_routes.login"))
    data = dashboard_state.get_data()
    ctx = _get_base_context(data)
    
    products_raw = data.get("products") or {}
    # Filter for deleted products only
    trash_list = [p for p in products_raw.values() if isinstance(p, dict) and p.get("deleted", False)]
    trash_list.sort(key=lambda x: str(x.get('deleted_at') or ''), reverse=True)
    
    ctx["trash_products"] = trash_list
    return render_template("dashboard.html", section="trash", **ctx)

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

def safe_float(val, default=0.0):
    """Safely converts a value to float, handling strings like 'None' or 'null'."""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

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
    prod_vals = [p for p in products_raw.values() if isinstance(p, dict) and not p.get("deleted", False)]
    prod_vals.sort(key=lambda x: str(x.get('created_at') or ''), reverse=True)
    latest_drafts = prod_vals[:10]

    # Global Ads Mode
    global_state = data.get("global_state", {})
    ads_system_mode = global_state.get("ads_system_mode", "enabled")

    # Defensive counts
    total_evals = len(evals_list) if isinstance(evals_list, list) else 0
    total_drafts = len(prod_vals) if isinstance(prod_vals, list) else 0

    # Status & Alerts
    system_status = data.get("global_state", {}).get("state", "UNKNOWN")
    error_alerts = []
    if system_status == "UNKNOWN":
        error_alerts.append("Motor de Estado indisponível - Falha na leitura de persistência.")

    budget_data = data.get("budget") or {}
    analytics_data = data.get("analytics") or {}

    return {
        "system_status": system_status,
        "mode": dashboard_state.mode,
        "username": session.get("username"),
        "last_updated": last_updated_str,
        "total_evals": total_evals,
        "total_drafts": total_drafts,
        "budget_calls": budget_data.get("calls_today") or 0,
        "budget_max": budget_data.get("max_calls_per_day") or 100,
        "budget_cost": f"{safe_float(budget_data.get('cost_today_usd')):.2f}",
        "stripe_balance": f"{safe_float(budget_data.get('stripe_balance_usd')):.2f}",
        "ads_spend": f"{safe_float(budget_data.get('google_ads_spend_30d')):.2f}",
        "evals": latest_evals if latest_evals else [],
        "products": latest_drafts if latest_drafts else [],
        "analytics": {
            "conversion_avg": f"{safe_float(analytics_data.get('conversion_avg')):.1f}",
            "retention_avg": f"{safe_float(analytics_data.get('retention_avg')):.1f}",
            "revenue_30d": f"{safe_float(analytics_data.get('revenue_30d')):.2f}"
        },
        "ai_decisions": data.get("ai_decisions") or [],
        "budget_data": budget_data,
        "error_alerts": error_alerts,
        "ads_system_mode": ads_system_mode,
        "traffic_mode_global": global_state.get("traffic_mode", "manual"),
        "env_mode": os.getenv("ENV_MODE", "LOCAL").upper()
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



@dashboard_bp.route("/dashboard/api/start_radar", methods=["POST"])
def start_radar():
    """Triggers a manual Radar scan via Orchestrator."""
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
    
    orchestrator = current_app.config.get('ORCHESTRATOR')
    if not orchestrator:
        return jsonify({"error": "Orchestrator not found"}), 500
        
    try:
        # Emit official request event
        orchestrator.receive_event(
            "radar_scan_requested", 
            {"source": "dashboard", "user": session.get("username")},
            source="DASHBOARD"
        )
        flash("Solicitação de início de Radar enviada com sucesso!")
        return jsonify({"status": "success", "message": "Radar scan requested"}), 200
    except Exception as e:
        logger.error(f"Error starting radar: {e}")
        return jsonify({"error": str(e)}), 500

# --- Product Operations API [Steps 4, 5, 6] ---

@dashboard_bp.route("/dashboard/api/products/<product_id>/toggle_ads", methods=["POST"])
def product_toggle_ads(product_id):
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
    
    # In a real system, we'd use ProductLifeEngine. 
    # For now, we update via the StateManager if supported, or emit an event.
    # The directives allow modifying infra/product and api/routes.
    
    orchestrator = current_app.config.get('ORCHESTRATOR')
    if not orchestrator:
        return jsonify({"error": "Orchestrator not found"}), 500
        
    try:
        # Fetch current state to toggle
        data = dashboard_state.get_data()
        product = data.get("products", {}).get(product_id)
        if not product:
            return jsonify({"error": "Product not found"}), 404
            
        new_val = not product.get("ads_enabled", False)
        
        # We need to reach the engine to persist this.
        # Since engine is not easily accessible here without a global registry,
        # we'll use the orchestrator to emit an internal request or use the engine if possible.
        # ProductLifeEngine is usually accessible via current_app if registered.
        ple = current_app.config.get('PRODUCT_LIFE_ENGINE')
        if ple:
            ple.update_metadata(product_id, {"ads_enabled": new_val})
        else:
            # Fallback if engine not in config
            logger.warning("ProductLifeEngine not found in current_app.config")
            return jsonify({"error": "Engine not accessible"}), 500

        dashboard_state.refresh_cache(force=True)
        return jsonify({"status": "success", "new_val": new_val})
    except Exception as e:
        logger.error(f"Error toggling ads for {product_id}: {e}")
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/dashboard/api/products/<product_id>/delete", methods=["POST"])
def product_delete(product_id):
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
        
    ple = current_app.config.get('PRODUCT_LIFE_ENGINE')
    if not ple:
        return jsonify({"error": "Engine not accessible"}), 500
        
    try:
        ple.move_to_trash(product_id)
        dashboard_state.refresh_cache(force=True)
        flash(f"Produto {product_id} movido para a lixeira.")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error deleting product {product_id}: {e}")
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/dashboard/api/products/<product_id>/restore", methods=["POST"])
def product_restore(product_id):
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
        
    ple = current_app.config.get('PRODUCT_LIFE_ENGINE')
    if not ple:
        return jsonify({"error": "Engine not accessible"}), 500
        
    try:
        ple.restore_from_trash(product_id)
        dashboard_state.refresh_cache(force=True)
        flash(f"Produto {product_id} restaurado com sucesso.")
        return jsonify({"status": "success"})
    except Exception as e:
        logger.error(f"Error restoring product {product_id}: {e}")
        return jsonify({"error": str(e)}), 500

@dashboard_bp.route("/dashboard/api/settings/toggle_global_ads", methods=["POST"])
def toggle_global_ads():
    if not session.get("authenticated"):
        return jsonify({"error": "Unauthorized"}), 401
        
    gs = current_app.config.get('GLOBAL_STATE')
    if not gs:
        return jsonify({"error": "GlobalState not accessible"}), 500
        
    try:
        current_mode = gs.get_ads_system_mode()
        new_mode = "disabled" if current_mode == "enabled" else "enabled"
        gs.set_ads_system_mode(new_mode, orchestrated=True)
        dashboard_state.refresh_cache(force=True)
        return jsonify({"status": "success", "new_mode": new_mode})
    except Exception as e:
        logger.error(f"Error toggling global ads: {e}")
        return jsonify({"error": str(e)}), 500
