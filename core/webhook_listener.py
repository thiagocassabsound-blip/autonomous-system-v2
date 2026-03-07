"""
core/webhook_listener.py — Stripe Webhook Handler (C3_MARKET_02)
Governed entry point for Stripe events. Strictly uses Orchestrator.
"""
import stripe
import logging

logger = logging.getLogger(__name__)

class StripeWebhookHandler:
    def __init__(self, orchestrator, webhook_secret: str):
        self.orchestrator = orchestrator
        self.webhook_secret = webhook_secret

    def handle_event(self, payload: bytes, sig_header: str):
        """
        Validates the Stripe webhook and routes events to the Orchestrator.
        """
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
        except ValueError as e:
            # Invalid payload
            raise e
        except stripe.error.SignatureVerificationError as e:
            # Invalid signature
            raise e

        # Authorized events only
        authorized_events = ["checkout.session.completed", "charge.refunded"]
        if event.type not in authorized_events:
            logger.info(f"Ignoring unauthorized Stripe event type: {event.type}")
            return

        # Process events strictly from metadata
        if event.type == "checkout.session.completed":
            self._handle_checkout_completed(event.data.object)
        elif event.type == "charge.refunded":
            self._handle_charge_refunded(event.data.object)

    def _handle_checkout_completed(self, session):
        """Processes checkout.session.completed via Orchestrator."""
        metadata = session.get("metadata", {})
        product_id = metadata.get("product_id")
        snapshot_id = metadata.get("snapshot_id")

        if not product_id or not snapshot_id:
            logger.error("Missing internal metadata in Stripe session. Ignoring event.")
            return

        self.orchestrator.receive_event(
            event_type="purchase_success",
            payload={
                "product_id": product_id,
                "snapshot_id": snapshot_id,
                "stripe_session_id": session.id,
                "amount_total": session.amount_total / 100.0,
                "customer_email": session.customer_details.get("email") if session.customer_details else None
            },
            product_id=product_id
        )

    def _handle_charge_refunded(self, charge):
        """Processes charge.refunded via Orchestrator."""
        # For charge.refunded, metadata is often on the original payment intent or session.
        # However, the user request specifies session.metadata["product_id"] and snapshot_id.
        # Stripe Charge objects also have metadata if passed during creation.
        metadata = charge.get("metadata", {})
        product_id = metadata.get("product_id")
        snapshot_id = metadata.get("snapshot_id")

        if not product_id or not snapshot_id:
            logger.error("Missing internal metadata in Stripe charge. Ignoring event.")
            return

        self.orchestrator.receive_event(
            event_type="refund_completed",
            payload={
                "product_id": product_id,
                "snapshot_id": snapshot_id,
                "refund_id": charge.id,
                "amount": charge.amount_refunded / 100.0
            },
            product_id=product_id
        )
