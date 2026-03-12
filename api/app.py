import os
from flask import Flask, jsonify, redirect, url_for
from flask_cors import CORS
from .webhooks import register_webhooks
from .routes.health import health_bp
from .routes.checkout import checkout_bp
from .routes.landing_routes import landing_bp
from .routes.product_routes import product_bp
from .routes.system_routes import system_bp
from .routes.dashboard_routes import dashboard_bp
from infrastructure.logger import get_logger

logger = get_logger("API")

def create_app(orchestrator):
    """
    Factory to create the Flask application with the injected orchestrator.
    """
    app = Flask(__name__)
    app.url_map.strict_slashes = False
    
    # Enable session management for Dashboard Foundation
    app.secret_key = os.getenv("FLASK_SECRET_KEY", "autonomous_system_v2_fallback_secret")
    
    # Inject orchestrator into the app context or global if preferred for access in routes
    app.config['ORCHESTRATOR'] = orchestrator
    
    # Expose specific engines for route accessibility (A15 Stabilized)
    app.config['GLOBAL_STATE'] = orchestrator.get_service("global_state")
    app.config['PRODUCT_LIFE_ENGINE'] = orchestrator.get_service("product_life")
    app.config['STRATEGIC_RADAR'] = orchestrator.get_service("strategic_radar")
    
    # Configure CORS for production domain
    CORS(app, resources={r"/*": {"origins": "https://app.fastoolhub.com"}})
    
    # Core blueprints
    app.register_blueprint(health_bp)
    app.register_blueprint(checkout_bp)
    register_webhooks(app, orchestrator)

    # Etapa 3 — API layer blueprints (read-only)
    app.register_blueprint(landing_bp)
    app.register_blueprint(product_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(dashboard_bp)

    @app.route('/')
    def index():
        return redirect(url_for('dashboard_routes.dashboard'))

    return app

