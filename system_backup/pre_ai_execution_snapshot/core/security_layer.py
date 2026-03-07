"""
core/security_layer.py — A9 Security Layer

Blinds the economic core against:
  - Invalid webhook signatures (HMAC SHA256, timing-safe compare)
  - Rate limit abuse (60 req/min per IP by default)
  - Client-side execution of critical/write events
  - Role-based permission violations

All security decisions are logged in append-only format.
No direct state writes.
"""
import hashlib
import hmac
import time
from collections import defaultdict
from datetime    import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("SecurityLayer")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Events that can never be triggered by source="client"
_CLIENT_BLOCKED_EVENTS = frozenset({
    "pricing_offensive_requested",
    "pricing_defensive_requested",
    "version_promotion_requested",
    "version_rollback_requested",
    "market_cycle_start_requested",
    "post_beta_consolidation_requested",
})

# Role → allowed actions
_ROLE_PERMISSIONS: dict[str, set[str]] = {
    "SYSTEM": {"*"},          # wildcard: all internal actions allowed
    "ADMIN":  {
        "price_update",
        "version_promotion",
        "rollback",
        "read",
    },
    "CLIENT": {
        "read",
    },
}


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class WebhookSignatureError(Exception):
    """Raised when a webhook signature is missing or does not match."""

class RateLimitExceededError(Exception):
    """Raised when an IP exceeds the configured rate limit."""

class ClientSideExecutionBlockedError(Exception):
    """Raised when a critical event is received with source='client'."""

class PermissionDeniedError(Exception):
    """Raised when a user role does not have the required permission."""


# ---------------------------------------------------------------------------
# Security Layer
# ---------------------------------------------------------------------------

class SecurityLayer:
    """
    Central security enforcer for the autonomous system.

    Parameters
    ----------
    persistence          : SecurityPersistence duck type (append_log / load)
    rate_limit_per_min   : Max requests per IP per minute (default 60)
    now_fn               : Injectable clock for deterministic tests
    """

    def __init__(
        self,
        orchestrator,
        persistence,
        rate_limit_per_min: int = 60,
        now_fn=None,
    ):
        self.orchestrator       = orchestrator
        self._pers              = persistence
        self._rate_limit        = rate_limit_per_min
        self._now               = now_fn or (lambda: datetime.now(timezone.utc))

        # In-memory sliding window counters: {ip → [(timestamp, endpoint), ...]}
        self._request_log: dict[str, list] = defaultdict(list)

        logger.info(
            f"SecurityLayer initialized. "
            f"rate_limit={rate_limit_per_min}/min "
            f"client_blocked_events={len(_CLIENT_BLOCKED_EVENTS)}"
        )

    # =======================================================================
    # Webhook validation (Item 54 / 55)
    # =======================================================================

    def validate_webhook(
        self,
        signature: str,
        payload:   bytes | str,
        secret:    str,
        ip:        str = "unknown",
    ) -> bool:
        """
        Validate an inbound webhook using HMAC-SHA256 with timing-safe comparison.

        Raises: WebhookSignatureError
        Emits:  webhook_validation_failed (on failure)
        Returns: True on success
        """
        raw = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        raw_secret = secret.encode("utf-8")

        expected_sig = hmac.new(raw_secret, raw, hashlib.sha256).hexdigest()

        provided_sig = signature.lstrip("sha256=")   # strip optional "sha256=" prefix
        is_valid     = hmac.compare_digest(expected_sig, provided_sig)

        if not is_valid:
            self._log_ip(ip=ip, endpoint="webhook", status="BLOCKED")
            self.orchestrator.emit_event(
                event_type="webhook_validation_failed",
                payload={"ip": ip, "reason": "invalid_signature"},
                source="system",
            )
            logger.warning(f"Webhook signature invalid from IP={ip}")
            raise WebhookSignatureError(
                f"Webhook signature validation failed for request from {ip}."
            )

        self._log_ip(ip=ip, endpoint="webhook", status="ALLOWED")
        logger.info(f"Webhook signature valid from IP={ip}")
        return True

    # =======================================================================
    # Rate limit (Item 56)
    # =======================================================================

    def validate_rate_limit(
        self,
        ip:       str,
        endpoint: str,
    ) -> bool:
        """
        Enforce per-IP rate limiting using a 60-second sliding window.

        Raises: RateLimitExceededError
        Emits:  rate_limit_triggered (on block)
        Returns: True if within limit
        """
        now_ts  = self._now().timestamp()
        window  = 60.0   # seconds
        cutoff  = now_ts - window

        # Drop entries outside the sliding window
        self._request_log[ip] = [
            (ts, ep) for ts, ep in self._request_log[ip] if ts > cutoff
        ]

        count = len(self._request_log[ip])
        if count >= self._rate_limit:
            self._log_ip(ip=ip, endpoint=endpoint, status="BLOCKED")
            self.orchestrator.emit_event(
                event_type="rate_limit_triggered",
                payload={
                    "ip":       ip,
                    "endpoint": endpoint,
                    "count":    count,
                    "limit":    self._rate_limit,
                },
                source="system",
            )
            logger.warning(
                f"Rate limit exceeded for IP={ip} endpoint={endpoint} "
                f"({count}/{self._rate_limit})"
            )
            raise RateLimitExceededError(
                f"IP '{ip}' has exceeded the rate limit of "
                f"{self._rate_limit} requests/min on '{endpoint}'."
            )

        # Record this request
        self._request_log[ip].append((now_ts, endpoint))
        self._log_ip(ip=ip, endpoint=endpoint, status="ALLOWED")
        return True

    # =======================================================================
    # IP Logging (Item 57)
    # =======================================================================

    def log_ip(
        self,
        ip:       str,
        endpoint: str,
        status:   str,    # "ALLOWED" | "BLOCKED"
    ) -> None:
        """Public IP logging — append-only."""
        self._log_ip(ip=ip, endpoint=endpoint, status=status)

    # =======================================================================
    # Client-side execution block (Item 58)
    # =======================================================================

    def validate_source(
        self,
        event_type: str,
        source:     str,
    ) -> bool:
        """
        Block critical events that arrive with source='client'.

        Raises: ClientSideExecutionBlockedError
        Emits:  client_execution_blocked (on block)
        Returns: True if source is safe
        """
        if source == "client" and event_type in _CLIENT_BLOCKED_EVENTS:
            self.orchestrator.emit_event(
                event_type="client_execution_blocked",
                payload={
                    "blocked_event": event_type,
                    "source":        source,
                },
                source="system",
            )
            logger.warning(
                f"Client-side execution blocked: event='{event_type}' source='{source}'"
            )
            raise ClientSideExecutionBlockedError(
                f"Event '{event_type}' cannot be triggered from source='client'. "
                f"This event is restricted to system/admin execution."
            )
        return True

    # =======================================================================
    # Permission validation (Item 59)
    # =======================================================================

    def validate_permission(
        self,
        user_role: str,
        action:    str,
    ) -> bool:
        """
        Check whether user_role is allowed to execute action.

        Roles:
          SYSTEM → all actions allowed
          ADMIN  → price_update, version_promotion, rollback, read
          CLIENT → read only

        Raises: PermissionDeniedError
        Returns: True if permitted
        """
        allowed = _ROLE_PERMISSIONS.get(user_role.upper(), set())
        if "*" in allowed or action in allowed:
            return True

        logger.warning(
            f"Permission denied: role='{user_role}' action='{action}'"
        )
        raise PermissionDeniedError(
            f"Role '{user_role}' does not have permission to perform '{action}'. "
            f"Allowed actions: {sorted(allowed)}."
        )

    # =======================================================================
    # Combined pre-flight gate (used by Orchestrator)
    # =======================================================================

    def pre_flight(
        self,
        event_type: str,
        source:     str,
        ip:         str,
        endpoint:   str,
        user_role:  str = "SYSTEM",
    ) -> bool:
        """
        Run all security checks in order before route dispatch:
          1. Rate limit
          2. Source validation (client-side block)

        Returns True if all checks pass, raises on first violation.
        """
        self.validate_rate_limit(ip, endpoint)
        self.validate_source(event_type, source)
        return True

    # =======================================================================
    # Internal helpers
    # =======================================================================

    def _log_ip(self, ip: str, endpoint: str, status: str) -> None:
        now = self._now()
        entry = {
            "ip":        ip,
            "endpoint":  endpoint,
            "timestamp": now.isoformat(),
            "status":    status,
        }
        self._pers.append(entry)
