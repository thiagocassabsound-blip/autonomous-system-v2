"""
core/stripe_adapter.py — Isolated Stripe API Adapter
Handles external communication with Stripe. No internal governance/event access.
"""
import stripe

class StripeAdapter:
    def __init__(self, api_key: str):
        self.api_key = api_key
        stripe.api_key = self.api_key

    def create_product(self, product_id: str, name: str) -> str:
        """Create a Stripe product for the internal product_id."""
        prod = stripe.Product.create(
            name=name,
            metadata={
                "product_id": product_id
            }
        )
        return prod.id

    def create_price(self, stripe_product_id: str, price: float) -> str:
        """Create a Stripe price for the stripe_product_id."""
        p = stripe.Price.create(
            unit_amount=int(price * 100),
            currency="usd",
            product=stripe_product_id,
        )
        return p.id

    def create_checkout_session(
        self,
        stripe_price_id: str,
        success_url: str,
        cancel_url: str,
        product_id: str,
        snapshot_id: str
    ) -> str:
        """Create a Stripe Checkout session with required metadata."""
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": stripe_price_id,
                "quantity": 1,
            }],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "product_id": product_id,
                "snapshot_id": snapshot_id
            }
        )
        return session.url
