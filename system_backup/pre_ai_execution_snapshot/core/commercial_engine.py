"""
core/commercial_engine.py — A10 Commercial Flow Engine

Governs the complete commercial lifecycle:
  payment_confirmed → license_created → access_token_issued
  login_validated
  refund_requested → refund_completed → access_revoked

Structural rules:
  - payment_confirmed only via webhook-validated, source="system"
  - License only created after confirmed payment
  - Refund automatically revokes access
  - All mutations emit formal EventBus events
  - No direct writes outside Orchestrator
"""
import uuid
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("CommercialEngine")


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class UnauthorizedPaymentSourceError(Exception):
    """Raised when payment_confirmed arrives from an untrusted source."""

class AccessRevokedError(Exception):
    """Raised when a login is attempted for a REVOKED license."""

class RefundWithoutPaymentError(Exception):
    """Raised when refund_completed is requested but no payment record exists."""

class LicenseNotFoundError(Exception):
    """Raised when a user/token lookup finds no matching record."""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CommercialEngine:
    """
    Deterministic, event-driven commercial flow engine.

    Parameters
    ----------
    persistence : CommercialPersistence duck type (load / save)
    now_fn      : Injectable clock for deterministic tests
    """

    def __init__(self, orchestrator, persistence, now_fn=None):
        self.orchestrator = orchestrator
        self._pers = persistence
        self._now  = now_fn or (lambda: datetime.now(timezone.utc))

        raw = persistence.load()
        # Index by user_id
        self._users: dict = raw if isinstance(raw, dict) else {}
        # Secondary index: token → user_id  (rebuilt at startup)
        self._token_index: dict = {
            rec.get("access_token"): uid
            for uid, rec in self._users.items()
            if rec.get("access_token")
        }

        logger.info(f"CommercialEngine initialized. Users tracked: {len(self._users)}")

    # =======================================================================
    # Payment Confirmation (Item 60)
    # =======================================================================

    def confirm_payment(
        self,
        user_id:    str,
        product_id: str,
        payment_id: str,
        source:     str,
    ) -> dict:
        """
        Confirm a payment and immediately trigger license + token creation.

        source MUST be "system" (webhook-validated path).

        Raises: UnauthorizedPaymentSourceError
        Emits:  payment_confirmed, license_created, access_token_issued
        """
        if source != "system":
            raise UnauthorizedPaymentSourceError(
                f"payment_confirmed rejected: source='{source}'. "
                f"Payments must arrive via validated webhook (source='system')."
            )

        now = self._now()
        uid = str(user_id)

        # Idempotent: if already ACTIVE, return existing record
        if uid in self._users and self._users[uid].get("status") == "ACTIVE":
            logger.warning(
                f"CommercialEngine: payment_confirmed for '{uid}' already ACTIVE. "
                f"Skipping duplicate."
            )
            return self._users[uid]

        # Emit payment_confirmed
        self.orchestrator.emit_event(
            event_type="payment_confirmed",
            payload={
                "user_id":    uid,
                "product_id": product_id,
                "payment_id": payment_id,
                "confirmed_at": now.isoformat(),
            },
            source="system",
        )
        logger.info(f"Payment confirmed for user='{uid}' product='{product_id}'")

        # Create license + token in the same transaction
        record = self._create_license(uid, product_id, payment_id, now)
        self._issue_token(uid, record, now)
        return record

    # =======================================================================
    # License Creation (Item 61)
    # =======================================================================

    def create_license(
        self,
        user_id:    str,
        product_id: str,
        payment_id: str,
    ) -> dict:
        """
        Create a new license for a user (external call path).
        Emits: license_created
        """
        now = self._now()
        return self._create_license(str(user_id), product_id, payment_id, now)

    def _create_license(self, uid, product_id, payment_id, now) -> dict:
        lid = str(uuid.uuid4())
        record = {
            "user_id":     uid,
            "product_id":  product_id,
            "license_id":  lid,
            "access_token": None,          # issued separately
            "status":      "ACTIVE",
            "payment_id":  payment_id,
            "created_at":  now.isoformat(),
            "revoked_at":  None,
        }
        self._users[uid] = record
        self._save()

        self.orchestrator.emit_event(
            event_type="license_created",
            payload={
                "user_id":    uid,
                "product_id": product_id,
                "license_id": lid,
                "payment_id": payment_id,
                "created_at": now.isoformat(),
                "status":     "ACTIVE",
            },
            source="system",
        )
        logger.info(f"License '{lid}' created for user='{uid}'")
        return record

    # =======================================================================
    # Access Token Issuance (Item 62)
    # =======================================================================

    def issue_access_token(self, user_id: str) -> str:
        """
        Issue a cryptographically secure access token for an ACTIVE user.
        Emits: access_token_issued
        """
        now = self._now()
        return self._issue_token(str(user_id), self._require_user(str(user_id)), now)

    def _issue_token(self, uid, record, now) -> str:
        token = str(uuid.uuid4())
        record["access_token"] = token
        self._token_index[token] = uid
        self._save()

        self.orchestrator.emit_event(
            event_type="access_token_issued",
            payload={
                "user_id":    uid,
                "license_id": record.get("license_id"),
                "token_prefix": token[:8] + "...",   # never log full token
                "issued_at":  now.isoformat(),
            },
            source="system",
        )
        logger.info(f"Access token issued for user='{uid}'")
        return token

    # =======================================================================
    # Login Validation (Item 63)
    # =======================================================================

    def validate_login(self, token: str) -> dict:
        """
        Validate an access token.

        Raises: AccessRevokedError, LicenseNotFoundError
        Emits:  login_validated
        """
        now = self._now()
        uid = self._token_index.get(token)
        if uid is None:
            raise LicenseNotFoundError(
                f"Access token not found. Ensure the token was issued by the system."
            )

        record = self._users[uid]
        if record["status"] == "REVOKED":
            raise AccessRevokedError(
                f"Access for user='{uid}' has been revoked "
                f"(revoked_at={record.get('revoked_at')}). "
                f"Refund was processed — token is no longer valid."
            )

        self.orchestrator.emit_event(
            event_type="login_validated",
            payload={
                "user_id":    uid,
                "license_id": record.get("license_id"),
                "validated_at": now.isoformat(),
                "status":     "ACTIVE",
            },
            source="system",
        )
        logger.info(f"Login validated for user='{uid}'")
        return record

    # =======================================================================
    # Refund Requested (Item 64)
    # =======================================================================

    def request_refund(
        self,
        user_id:   str,
        reason:    str,
        user_role: str = "SYSTEM",
    ) -> dict:
        """
        Register a refund request. Does not immediately revoke access.
        Allowed only for ADMIN or SYSTEM roles.

        Emits: refund_requested
        """
        role = user_role.upper()
        if role not in {"ADMIN", "SYSTEM"}:
            from core.security_layer import PermissionDeniedError
            raise PermissionDeniedError(
                f"Role '{user_role}' cannot request a refund. "
                f"Requires ADMIN or SYSTEM."
            )

        uid = str(user_id)
        now = self._now()

        self.orchestrator.emit_event(
            event_type="refund_requested",
            payload={
                "user_id":      uid,
                "reason":       reason,
                "requested_at": now.isoformat(),
                "requested_by": role,
            },
            source="system",
        )
        logger.info(f"Refund requested for user='{uid}' reason='{reason}'")
        return {"user_id": uid, "status": "refund_pending"}

    # =======================================================================
    # Refund Completed + Access Revocation (Items 65 / 66)
    # =======================================================================

    def complete_refund(self, user_id: str) -> dict:
        """
        Complete a refund and automatically revoke access.

        Precondition: user must have a confirmed payment (payment_id set).
        Raises: RefundWithoutPaymentError
        Emits:  refund_completed, access_revoked
        """
        uid    = str(user_id)
        record = self._require_user(uid)
        now    = self._now()

        if not record.get("payment_id"):
            raise RefundWithoutPaymentError(
                f"Cannot complete refund for user='{uid}': "
                f"no confirmed payment record found. "
                f"Ensure payment_confirmed was processed first."
            )

        lid = record.get("license_id")

        self.orchestrator.emit_event(
            event_type="refund_completed",
            payload={
                "user_id":      uid,
                "payment_id":   record["payment_id"],
                "license_id":   lid,
                "completed_at": now.isoformat(),
            },
            source="system",
        )
        logger.info(f"Refund completed for user='{uid}'")

        # Automatic access revocation
        return self._revoke_access(uid, record, now)

    def _revoke_access(self, uid, record, now) -> dict:
        record["status"]     = "REVOKED"
        record["revoked_at"] = now.isoformat()
        self._save()

        self.orchestrator.emit_event(
            event_type="access_revoked",
            payload={
                "user_id":    uid,
                "license_id": record.get("license_id"),
                "revoked_at": now.isoformat(),
                "status":     "REVOKED",
            },
            source="system",
        )
        logger.warning(f"Access revoked for user='{uid}' license='{record.get('license_id')}'")
        return record

    # =======================================================================
    # Read-only accessors
    # =======================================================================

    def get_record(self, user_id: str) -> dict | None:
        return self._users.get(str(user_id))

    def get_all_records(self) -> list:
        return list(self._users.values())

    # =======================================================================
    # Internal helpers
    # =======================================================================

    def _require_user(self, uid: str) -> dict:
        rec = self._users.get(uid)
        if rec is None:
            raise LicenseNotFoundError(
                f"No commercial record found for user='{uid}'."
            )
        return rec

    def _save(self) -> None:
        self._pers.save(self._users)
