"""
infra/communication/email_gateway.py

Infrastructure module responsible for sending transactional emails via Resend.
Migrated from V1: acts only when called by other engines or event handlers.
Replaces file logging with standard V2 logger.
"""
import os
import time
from infrastructure.logger import get_logger

logger = get_logger("EmailGateway")

class EmailGateway:
    def __init__(self):
        self.api_key = os.getenv('RESEND_API_KEY')
        self.from_email = os.getenv('EMAIL_FROM', 'noreply@fastoolhub.com')
        
        if not self.api_key:
            logger.error("[EmailGateway] RESEND_API_KEY not configured. Email delivery blocked.")
        else:
            try:
                import resend
                resend.api_key = self.api_key
                self.client = resend
                logger.info(f"[EmailGateway] Initialized (from: {self.from_email})")
            except ImportError:
                logger.warning("[EmailGateway] 'resend' library not installed. Sending will fail.")
                self.client = None

    def _retry_send(self, payload, max_retries=3):
        """Exponential backoff retry logic for external API calls."""
        if not getattr(self, "client", None):
            logger.error("[EmailGateway] Cannot send, client not initialized.")
            return False

        for attempt in range(max_retries):
            try:
                response = self.client.Emails.send(payload)
                logger.info(f"[EmailGateway] Email sent successfully. ID: {response.get('id')}")
                return True
            except Exception as e:
                logger.warning(f"[EmailGateway] Email send attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt  # 1s, 2s, 4s
                    time.sleep(wait_time)
        
        logger.error(f"[EmailGateway] Email sending failed after {max_retries} attempts.")
        return False

    def send_email(self, event_type: str, recipient: str, payload: dict) -> bool:
        """
        Unified interface for email routing.
        """
        logger.info(f"[EmailGateway] Preparing to send '{event_type}' to {recipient}")
        
        if event_type == "product_delivery":
            subject = f"🎁 Your {payload.get('name', 'Product')} is Ready!"
            # Mock template rendering
            html_content = f"<h1>Here is {payload.get('name')}</h1><p>{payload.get('description')}</p><a href='{payload.get('download_link')}'>Download Now</a>"
        
        elif event_type == "payment_confirmation":
            subject = f"✅ Payment Confirmed - {payload.get('product_name', 'Order')}"
            html_content = f"<h1>Payment Confirmed</h1><p>You paid ${payload.get('amount')}</p><p>Order ID: {payload.get('order_id')}</p>"
            
        elif event_type == "feedback_request":
            subject = f"💬 How was {payload.get('product_name')}? We'd love your feedback!"
            html_content = f"<h1>Did you like {payload.get('product_name')}?</h1><p>Please let us know.</p>"
            
        else:
            logger.error(f"[EmailGateway] Unknown event_type: {event_type}")
            return False

        email_payload = {
            "from": self.from_email,
            "to": recipient,
            "subject": subject,
            "html": html_content
        }
        
        return self._retry_send(email_payload)

# Singleton export
email_gateway = EmailGateway()

def send_email(event_type: str, recipient: str, payload: dict) -> bool:
    """Wrapper for external calls."""
    return email_gateway.send_email(event_type, recipient, payload)
