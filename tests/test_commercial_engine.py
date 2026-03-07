"""
tests/test_commercial_engine.py — A10 Commercial Flow Validation Suite

9 closure criteria:
  1. payment_confirmed cria licença
  2. access_token_issued gerado corretamente
  3. login_validated funciona para ACTIVE
  4. login bloqueado para REVOKED
  5. refund_requested registrado
  6. refund_completed revoga acesso
  7. Não permite refund sem pagamento
  8. Webhook inválido bloqueado
  9. DirectWriteError fora do Orchestrator

Usage:
    py tests/test_commercial_engine.py
"""
import sys
import os
import io
import hashlib
import hmac as _hmac

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus         import EventBus
from core.commercial_engine import (
    CommercialEngine,
    UnauthorizedPaymentSourceError,
    AccessRevokedError,
    RefundWithoutPaymentError,
    LicenseNotFoundError,
)
from core.security_layer    import SecurityLayer, WebhookSignatureError
from core.state_manager     import StateManager, DirectWriteError

# ====================================================================
# Stubs
# ====================================================================

class MemFile:
    def __init__(self):
        self._d = {}
    def load(self):
        import copy; return copy.deepcopy(self._d)
    def save(self, data):
        import copy; self._d = copy.deepcopy(data)


class MemSecPersistence:
    def __init__(self):
        self._log = []
    def append_log(self, entry):
        self._log.append(dict(entry))
    def load_all(self):
        return list(self._log)


class MockOrchestrator:
    def __init__(self, bus):
        self._bus = bus
    def emit_event(self, event_type, payload, source=None, product_id=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload": payload,
            "source": source or "orchestrator",
            "product_id": product_id
        })

def _make_engine(orchestrator=None):
    if orchestrator is None:
        orchestrator = MockOrchestrator(EventBus())
    return CommercialEngine(orchestrator=orchestrator, persistence=MemFile())


def _make_security():
    return SecurityLayer(persistence=MemSecPersistence())


def _sign(payload: bytes, secret: str) -> str:
    return _hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


# ====================================================================
# Test runner
# ====================================================================
results = []

def test(name, fn):
    try:
        fn()
        results.append(("[OK]", name))
        print(f"  [OK]  {name}")
    except AssertionError as e:
        results.append(("[FAIL]", name))
        print(f"  [FAIL] {name} — AssertionError: {e}")
    except Exception as e:
        results.append(("[FAIL]", name))
        print(f"  [FAIL] {name} — {type(e).__name__}: {e}")


# ====================================================================
# TESTS
# ====================================================================

def t1_payment_confirmed_creates_license():
    """payment_confirmed (source=system) creates license with ACTIVE status."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)

    record = eng.confirm_payment(
        user_id="user-1", product_id="prod-x",
        payment_id="pay-001", source="system",
    )

    assert record["status"] == "ACTIVE", f"Expected ACTIVE, got {record['status']}"
    assert record["license_id"], "Expected a non-empty license_id"
    assert record["payment_id"] == "pay-001", "payment_id not stored"

    types = [e["event_type"] for e in bus.get_events()]
    assert "payment_confirmed" in types, "payment_confirmed not in ledger"
    assert "license_created"   in types, "license_created not in ledger"
    assert "access_token_issued" in types, "access_token_issued not in ledger"

    # Payment from untrusted source must fail
    raised = False
    try:
        eng.confirm_payment("user-2", "prod-x", "pay-002", source="client")
    except UnauthorizedPaymentSourceError:
        raised = True
    assert raised, "Expected UnauthorizedPaymentSourceError for source='client'"


def t2_access_token_issued():
    """Access token is a non-empty string with correct length (UUID4)."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
 
    eng.confirm_payment("user-2", "prod-y", "pay-002", source="system")
    rec = eng.get_record("user-2")

    token = rec["access_token"]
    assert token and len(token) == 36, f"Expected UUID4 (36 chars), got: '{token}'"

    # Token must appear in ledger as prefix only (never full token)
    payload_tokens = [
        e["payload"].get("token_prefix", "")
        for e in bus.get_events()
        if e["event_type"] == "access_token_issued"
    ]
    assert any(p.endswith("...") for p in payload_tokens), (
        "Full token should not be in ledger; expected '...' prefix"
    )


def t3_login_validated_for_active():
    """validate_login succeeds and emits login_validated for ACTIVE user."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
 
    eng.confirm_payment("user-3", "prod-z", "pay-003", source="system")
    token = eng.get_record("user-3")["access_token"]
 
    result = eng.validate_login(token)
    assert result["status"] == "ACTIVE", f"Expected ACTIVE, got {result['status']}"

    types = [e["event_type"] for e in bus.get_events()]
    assert "login_validated" in types, "login_validated not in ledger"


def t4_login_blocked_for_revoked():
    """validate_login raises AccessRevokedError for a REVOKED user."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
 
    eng.confirm_payment("user-4", "prod-a", "pay-004", source="system")
    token = eng.get_record("user-4")["access_token"]

    eng.complete_refund("user-4")   # revokes access

    raised = False
    try:
        eng.validate_login(token)
    except AccessRevokedError:
        raised = True
    assert raised, "Expected AccessRevokedError after refund/revocation"


def t5_refund_requested_is_registered():
    """request_refund emits refund_requested event; only ADMIN/SYSTEM allowed."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
 
    eng.confirm_payment("user-5", "prod-b", "pay-005", source="system")
    eng.request_refund("user-5", reason="Customer not satisfied",
                       user_role="ADMIN")

    types = [e["event_type"] for e in bus.get_events()]
    assert "refund_requested" in types, "refund_requested not in ledger"

    # CLIENT role must be denied
    from core.security_layer import PermissionDeniedError
    raised = False
    try:
        eng.request_refund("user-5", reason="nope", user_role="CLIENT")
    except PermissionDeniedError:
        raised = True
    assert raised, "Expected PermissionDeniedError for CLIENT role on refund"


def t6_refund_completed_revokes_access():
    """complete_refund sets status=REVOKED and emits access_revoked."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    eng = _make_engine(orc)
 
    eng.confirm_payment("user-6", "prod-c", "pay-006", source="system")
    record = eng.complete_refund("user-6")

    assert record["status"] == "REVOKED", f"Expected REVOKED, got {record['status']}"
    assert record["revoked_at"] is not None, "revoked_at must be set"

    types = [e["event_type"] for e in bus.get_events()]
    assert "refund_completed" in types, "refund_completed not in ledger"
    assert "access_revoked"   in types, "access_revoked not in ledger"


def t7_refund_without_payment_fails():
    """complete_refund raises RefundWithoutPaymentError if no payment exists."""
    eng = _make_engine()
    bus = EventBus()

    # Manually insert a user record WITHOUT payment_id
    from infrastructure.commercial_persistence import CommercialPersistence
    eng._users["user-7"] = {
        "user_id": "user-7", "product_id": "prod-x",
        "license_id": "lic-xyz", "access_token": None,
        "status": "ACTIVE", "payment_id": None,
        "created_at": "2026-01-01T00:00:00+00:00", "revoked_at": None,
    }

    raised = False
    try:
        eng.complete_refund("user-7")
    except RefundWithoutPaymentError:
        raised = True
    assert raised, "Expected RefundWithoutPaymentError when payment_id is None"


def t8_invalid_webhook_blocked():
    """SecurityLayer.validate_webhook raises WebhookSignatureError for wrong sig."""
    sl  = _make_security()
    bus = EventBus()

    payload = b'{"amount": 5000}'
    secret  = "stripe-webhook-secret"
    bad_sig = "000000000000000000000000000000000000000000000000000000000000000"

    raised = False
    try:
        sl.validate_webhook(bad_sig, payload, secret, event_bus=bus, ip="99.1.2.3")
    except WebhookSignatureError:
        raised = True
    assert raised, "Expected WebhookSignatureError for invalid signature"

    types = [e["event_type"] for e in bus.get_events()]
    assert "webhook_validation_failed" in types, "webhook_validation_failed not in ledger"


def t9_direct_write_fails():
    """StateManager.set() raises DirectWriteError — no direct writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("license_bypass", "hack")
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A10 COMMERCIAL ENGINE — TEST SUITE")
    print("=" * 62)

    test("payment_confirmed cria licença",          t1_payment_confirmed_creates_license)
    test("access_token_issued gerado corretamente", t2_access_token_issued)
    test("login_validated funciona para ACTIVE",    t3_login_validated_for_active)
    test("login bloqueado para REVOKED",            t4_login_blocked_for_revoked)
    test("refund_requested registrado",             t5_refund_requested_is_registered)
    test("refund_completed revoga acesso",          t6_refund_completed_revokes_access)
    test("Não permite refund sem pagamento",        t7_refund_without_payment_fails)
    test("Webhook inválido bloqueado",              t8_invalid_webhook_blocked)
    test("DirectWriteError fora do Orchestrator",   t9_direct_write_fails)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A10 COMMERCIAL ENGINE — VALID")
        print("  A10 COMMERCIAL FLOW LOCKED")
    else:
        print("  A10 COMMERCIAL ENGINE — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
