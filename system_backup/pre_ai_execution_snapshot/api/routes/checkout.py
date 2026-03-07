import os
from flask import Blueprint, request, jsonify, current_app
from core.stripe_adapter import StripeAdapter
from infrastructure.logger import get_logger

logger = get_logger("CheckoutRoute")
checkout_bp = Blueprint('checkout', __name__)

@checkout_bp.route('/create-checkout-session', methods=['POST'])
def create_checkout_session_route():
    """
    Dynamically creates a Stripe Checkout Session for a given product_id.
    """
    data = request.get_json()
    if not data or 'product_id' not in data:
        return jsonify({"error": "Missing product_id"}), 400

    product_id = data['product_id']
    
    # 1. Instantiate StripeAdapter using environment keys
    api_key = os.getenv("STRIPE_SECRET_KEY")
    if not api_key:
        logger.error("STRIPE_SECRET_KEY missing in environment")
        return jsonify({"error": "Configuration error"}), 500
    
    adapter = StripeAdapter(api_key)

    # 2. Lookup dynamic metadata (In a real system, these would come from VersionManager/DB)
    # For now, we use placeholders or simple lookup logic.
    # In V2, we assume a default success/cancel URL if not provided via .env
    success_url = os.getenv("SUCCESS_URL", "https://example.com/success")
    cancel_url = os.getenv("CANCEL_URL", "https://example.com/cancel")
    
    # We attempt to find the latest snapshot_id from orchestrator state if available
    orchestrator = current_app.config.get('ORCHESTRATOR')
    snapshot_id = "live_prod_active" # Default fallback
    stripe_price_id = os.getenv(f"STRIPE_PRICE_ID_{product_id.upper()}") 

    if orchestrator:
        state = orchestrator.state
        # Logic to find price_id/snapshot_id dynamically from governed state
        # (This bridges the gap identified in the forensic trace)
        active_cycles = state.get("active_cycles", {})
        for cid, cycle in active_cycles.items():
            if str(cycle.get("opportunity_id")) == str(product_id):
                snapshot_id = f"snap_{cid}"
                break

    # If no specific price_id in .env, we'd ideally trigger create_price, 
    # but strictly following "do not modify adapter/orchestrator" logic.
    if not stripe_price_id:
        logger.warning(f"No STRIPE_PRICE_ID found for {product_id}. Using fallback if any.")
        # In a real production scenario, this would be a lookup in a product-prices table.

    try:
        logger.info(f"Creating checkout session for product: {product_id}")
        session_url = adapter.create_checkout_session(
            stripe_price_id=stripe_price_id or "price_placeholder", # Placeholder if missing
            success_url=success_url,
            cancel_url=cancel_url,
            product_id=product_id,
            snapshot_id=snapshot_id
        )
        
        logger.info(f"checkout_session_created: {product_id}")
        return jsonify({"checkout_url": session_url}), 200

    except Exception as e:
        logger.error(f"Stripe Error: {str(e)}")
        return jsonify({"error": f"Stripe integration error: {str(e)}"}), 500
