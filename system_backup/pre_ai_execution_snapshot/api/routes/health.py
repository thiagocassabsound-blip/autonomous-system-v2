from flask import Blueprint, jsonify

health_bp = Blueprint('health', __name__)

@health_bp.route('/health')
def health_check():
    """Definitive health check for V2 Satellite layer."""
    return jsonify({
        "status": "healthy",
        "system": "autonomous-system-v2",
        "mode": "production"
    }), 200
