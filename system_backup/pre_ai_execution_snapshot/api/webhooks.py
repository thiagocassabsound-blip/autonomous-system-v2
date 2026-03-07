import os
import json
import stripe
from flask import request, jsonify
from infrastructure.logger import get_logger

logger = get_logger("WebhookBridge")

def register_webhooks(app, orchestrator):
    """Registers Stripe webhook endpoints."""

    @app.route('/webhook', methods=['POST'])
    def stripe_webhook():
        payload = request.get_data(as_text=True)
        sig_header = request.headers.get('Stripe-Signature')
        endpoint_secret = os.getenv('WEBHOOK_SECRET')

        if not endpoint_secret:
            logger.error("WEBHOOK_SECRET missing in environment.")
            return jsonify({"error": "Configuration error"}), 500

        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, endpoint_secret
            )
        except Exception as e:
            logger.error(f"Webhook Verification Failed: {e}")
            return jsonify({"error": str(e)}), 400

        # Absorbed Logic: Checkout Completed
        if event['type'] == 'checkout.session.completed':
            session = event['data']['object']
            customer_email = session.get('customer_details', {}).get('email')
            metadata = session.get('metadata', {})
            product_id = metadata.get('product_id')
            
            logger.info(f"Payment Confirmed: {product_id} from {customer_email}")

            # Routing to V2 Orchestrator
            orchestrator.receive_event(
                event_type="payment_confirmed",
                payload={
                    "session_id": session.get('id'),
                    "customer_email": customer_email,
                    "amount": session.get('amount_total', 0) / 100,
                    "metadata": metadata
                },
                product_id=product_id,
                source="stripe_webhook"
            )

        return jsonify({"status": "event_received"}), 200
