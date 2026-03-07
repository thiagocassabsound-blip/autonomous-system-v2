import os
import sys
import stripe
import json

from pathlib import Path
from infrastructure.logger import get_logger

# Ensure V2 root is in path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

logger = get_logger("Phase2Test")

# Attempt to load from local .env
try:
    from dotenv import load_dotenv
    # Use local .env in the root directory
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

stripe.api_key = os.getenv("STRIPE_SECRET_KEY") or os.getenv("PAYMENT_API_KEY")

def run_phase_2():
    print(">>> PHASE 2: CHECKOUT CREATION TEST <<<")
    
    if not stripe.api_key:
        print("ERROR: STRIPE_SECRET_KEY is missing from environment.")
        # Try to find it in V1 as a fallback for this test? No, focus on V2 independence.
        sys.exit(1)

    try:
        # Create Test Product
        product = stripe.Product.create(
            name="V2 E2E Test Product",
            description="Automated Test Product for V2 E2E Validation",
        )
        print(f"Product Created: {product.id}")

        # Create Test Price
        price = stripe.Price.create(
            unit_amount=1000,
            currency="brl",
            product=product.id,
        )
        print(f"Price Created: {price.id}")

        # Create Checkout Session
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price.id,
                'quantity': 1,
            }],
            mode='payment',
            success_url='https://example.com/success',
            cancel_url='https://example.com/cancel',
            metadata={
                'product_id': 'test_v2_prod_01',
                'snapshot_id': 'snap_test_e2e'
            }
        )
        print(f"Checkout Session Created: {session.id}")
        print(f"Checkout URL: {session.url}")
        
        results = {
            "product_id": product.id,
            "price_id": price.id,
            "session_id": session.id,
            "checkout_url": session.url
        }
        
        # Save results for Phase 3
        with open("phase_2_results.json", "w") as f:
            json.dump(results, f)
            
    except Exception as e:
        print(f"API Error during checkout creation: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_phase_2()
