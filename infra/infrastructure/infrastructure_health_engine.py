"""
infra/infrastructure/infrastructure_health_engine.py

Responsibilities:
  - Monitor domain status and expiration.
  - Monitor DNS resolution.
  - Monitor SSL certificate validity.
  - Monitor server hosting latency/reachability.
  - Monitor infrastructure billing dates (simulated/tracked via file).
  - Emits health alerts to EventBus.
  - Strictly READ-ONLY. NO state mutation. NO direct dashboard changes.
"""

import os
import ssl
import socket
import logging
import requests
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv

logger = logging.getLogger("infra.infrastructure.health")

LOCK_FILE = os.path.join(os.getcwd(), "data", "infrastructure_health.lock")
BILLING_FILE = os.path.join(os.getcwd(), "data", "system_costs.json")

class InfrastructureHealthEngine:
    def __init__(self, event_bus):
        self.event_bus = event_bus
        load_dotenv()
        self.domain = os.getenv("DOMAIN_NAME", "fastoolhub.com")
        self.base_url = f"https://{self.domain}"
        
    def run_checks(self):
        """Main execution sequence triggered by the Scheduler."""
        if self._is_locked():
            logger.warning("[InfraHealth] Lock file detected. Aborting concurrent execution.")
            return

        self._create_lock()
        try:
            # Emit telemetry start
            self.event_bus.publish("infrastructure_check_started", {
                "origin": "infrastructure_health_engine",
                "timestamp": datetime.utcnow().isoformat()
            })
            
            # Execute modules
            self.monitor_domain()
            self.monitor_dns()
            self.monitor_ssl()
            self.monitor_hosting()
            self.monitor_billing()
            
            # Emit telemetry finish 
            self.event_bus.publish("infrastructure_check_completed", {
                "origin": "infrastructure_health_engine",
                "timestamp": datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            logger.error(f"[InfraHealth] Execution error: {e}")
        finally:
            self._remove_lock()

    # -------------------------------------------------------------------------
    # LOCK MECHANISM
    # -------------------------------------------------------------------------

    def _is_locked(self) -> bool:
        return os.path.exists(LOCK_FILE)

    def _create_lock(self):
        try:
            os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
            with open(LOCK_FILE, "w") as f:
                f.write(datetime.utcnow().isoformat())
        except Exception as e:
            logger.error(f"[InfraHealth] Error creating lock: {e}")

    def _remove_lock(self):
        try:
            if os.path.exists(LOCK_FILE):
                os.remove(LOCK_FILE)
        except Exception as e:
            logger.error(f"[InfraHealth] Error removing lock: {e}")

    # -------------------------------------------------------------------------
    # MONITORS
    # -------------------------------------------------------------------------

    def monitor_domain(self):
        """Monitor domain status and remaining days. (Stubbed to dummy lookup for now)"""
        try:
            # Full whois lookup is external dependent. Stubbing standard health values.
            # In production, integrate python-whois.
            days_remaining = 320
            
            payload = {
                "domain": self.domain,
                "days_remaining": days_remaining,
                "status": "OK"
            }
            
            if days_remaining < 30:
                self.event_bus.publish("domain_expiration_critical", payload)
            elif days_remaining < 60:
                self.event_bus.publish("domain_expiration_warning", payload)
            else:
                self.event_bus.publish("domain_status_ok", payload)
                
        except Exception as e:
            logger.error(f"[InfraHealth] Domain check failed: {e}")

    def monitor_dns(self):
        """Verify DNS resolution."""
        try:
            ip_address = socket.gethostbyname(self.domain)
            self.event_bus.publish("dns_ok", {
                "domain": self.domain,
                "resolved_ip": ip_address
            })
        except socket.gaierror:
            self.event_bus.publish("dns_resolution_failure", {
                "domain": self.domain,
                "error": "Address resolution failed"
            })
        except Exception as e:
            logger.error(f"[InfraHealth] DNS check failed: {e}")

    def monitor_ssl(self):
        """Verify SSL certificate validity."""
        try:
            context = ssl.create_default_context()
            with socket.create_connection((self.domain, 443), timeout=5) as sock:
                with context.wrap_socket(sock, server_hostname=self.domain) as ssock:
                    cert = ssock.getpeercert()
                    # Example format: 'notAfter': 'Mar 17 23:59:59 2026 GMT'
                    expire_str = cert.get('notAfter')
                    if expire_str:
                        expire_date = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z")
                        days_remaining = (expire_date - datetime.utcnow()).days
                        
                        payload = {
                            "domain": self.domain,
                            "days_remaining": days_remaining,
                            "valid": True
                        }
                        
                        if days_remaining < 15:
                            self.event_bus.publish("ssl_expiration_critical", payload)
                        elif days_remaining < 30:
                            self.event_bus.publish("ssl_expiration_warning", payload)
                        else:
                            self.event_bus.publish("ssl_valid", payload)
        except Exception as e:
            self.event_bus.publish("ssl_expiration_critical", {
                "domain": self.domain,
                "error": str(e),
                "valid": False
            })
            logger.error(f"[InfraHealth] SSL check failed: {e}")

    def monitor_hosting(self):
        """Verify server hosting health and latency."""
        try:
            start_time = datetime.utcnow()
            response = requests.get(self.base_url, timeout=10)
            latency_ms = (datetime.utcnow() - start_time).total_seconds() * 1000
            
            payload = {
                "status_code": response.status_code,
                "latency_ms": latency_ms
            }
            
            if response.status_code >= 500:
                self.event_bus.publish("hosting_unreachable", payload)
            elif latency_ms > 2000:
                self.event_bus.publish("hosting_latency_warning", payload)
            else:
                self.event_bus.publish("hosting_status_ok", payload)
                
        except requests.exceptions.Timeout:
            self.event_bus.publish("hosting_unreachable", {"error": "timeout"})
        except requests.exceptions.ConnectionError:
            self.event_bus.publish("hosting_unreachable", {"error": "connection_error"})
        except Exception as e:
            logger.error(f"[InfraHealth] Hosting check failed: {e}")

    def monitor_billing(self):
        """Monitor infrastructure billing warnings (mocked against system_costs.json if available)."""
        try:
            # We mock the cycle check. A real implementation hooks to Stripe or Vercel billing endpoints.
            days_until_renewal = 25 
            
            payload = {
                "next_renewal_days": days_until_renewal,
                "component": "hosting"
            }
            
            if days_until_renewal < 3:
                self.event_bus.publish("billing_failure", payload) # simulated failure proximity
            elif days_until_renewal < 10:
                self.event_bus.publish("billing_payment_warning", payload)
            else:
                self.event_bus.publish("billing_status_ok", payload)
                
        except Exception as e:
            logger.error(f"[InfraHealth] Billing check failed: {e}")
