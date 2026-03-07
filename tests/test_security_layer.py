"""
tests/test_security_layer.py — A9 Security Layer Validation Suite

9 closure criteria:
  1. Webhook inválido bloqueado
  2. Webhook válido permitido
  3. Rate limit bloqueia após limite
  4. IP logging registra ALLOWED
  5. IP logging registra BLOCKED
  6. Client-side bloqueado para price_update
  7. CLIENT role não pode promover versão
  8. ADMIN pode promover versão
  9. DirectWriteError fora do Orchestrator

Usage:
    py tests/test_security_layer.py
"""
import sys
import os
import io
import hashlib
import hmac as _hmac

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.event_bus      import EventBus
from core.security_layer import (
    SecurityLayer,
    WebhookSignatureError,
    RateLimitExceededError,
    ClientSideExecutionBlockedError,
    PermissionDeniedError,
)
from core.state_manager  import StateManager, DirectWriteError

class MockOrchestrator:
    def __init__(self, bus):
        self._bus = bus
    def emit_event(self, event_type, payload, source=None, product_id=None):
        return self._bus.append_event({
            "event_type": event_type,
            "payload": payload,
            "source": source or "orchestrator",
            "user_id": payload.get("user_id") if isinstance(payload, dict) else None,
            "product_id": product_id
        })

# ====================================================================
# Stubs
# ====================================================================

class MemSecPersistence:
    """In-memory security log."""
    def __init__(self):
        self._log = []
    def append_log(self, entry):
        self._log.append(dict(entry))
    def load_all(self):
        return list(self._log)


def _make_sl(orchestrator=None, rate_limit=60, now_fn=None):
    if orchestrator is None:
        orchestrator = MockOrchestrator(EventBus())
    return SecurityLayer(
        orchestrator=orchestrator,
        persistence=MemSecPersistence(),
        rate_limit_per_min=rate_limit,
        now_fn=now_fn,
    )


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

def t1_invalid_webhook_blocked():
    """Webhook with wrong signature raises WebhookSignatureError."""
    bus = EventBus()
    orc = MockOrchestrator(bus)
    sl  = _make_sl(orchestrator=orc)

    payload = b'{"amount": 9999}'
    secret  = "correct-secret"
    bad_sig = "deadbeefdeadbeef"   # definitely wrong

    raised = False
    try:
        sl.validate_webhook(bad_sig, payload, secret, ip="1.2.3.4")
    except WebhookSignatureError:
        raised = True
    assert raised, "Expected WebhookSignatureError for invalid signature"

    types = [e["event_type"] for e in bus.get_events()]
    assert "webhook_validation_failed" in types, (
        "webhook_validation_failed not emitted on failed validation"
    )


def t2_valid_webhook_permitted():
    """Webhook with correct HMAC-SHA256 signature passes."""
    bus     = EventBus()
    orc     = MockOrchestrator(bus)
    sl      = _make_sl(orchestrator=orc)
    secret  = "my-webhook-secret"
    payload = b'{"event": "charge.succeeded", "amount": 100}'
    sig     = _sign(payload, secret)

    result = sl.validate_webhook(sig, payload, secret, ip="5.6.7.8")
    assert result is True, "Expected True for valid webhook"


def t3_rate_limit_blocks():
    """Rate limit raises after configured limit is reached."""
    # Inject a fixed timestamp so all calls fall in the same window
    fixed_ts = 1_700_000_000.0
    from datetime import datetime, timezone
    fixed_dt = datetime.fromtimestamp(fixed_ts, tz=timezone.utc)

    sl = _make_sl(rate_limit=3, now_fn=lambda: fixed_dt)

    # 3 allowed
    for _ in range(3):
        sl.validate_rate_limit("9.9.9.9", "/api/order")

    # 4th should be blocked
    raised = False
    try:
        sl.validate_rate_limit("9.9.9.9", "/api/order")
    except RateLimitExceededError:
        raised = True
    assert raised, "Expected RateLimitExceededError after limit exceeded"


def t4_ip_logging_allowed():
    """ALLOWED entries are written to the log."""
    sl  = _make_sl()
    sl.log_ip("10.0.0.1", "/api/ping", "ALLOWED")

    logs = sl._pers.load_all()
    assert any(e["status"] == "ALLOWED" and e["ip"] == "10.0.0.1" for e in logs), (
        "Expected ALLOWED log entry for 10.0.0.1"
    )


def t5_ip_logging_blocked():
    """BLOCKED entries are written to the log via rate limit trigger."""
    from datetime import datetime, timezone
    fixed_dt = datetime.fromtimestamp(1_700_000_001.0, tz=timezone.utc)
    bus = EventBus()
    orc = MockOrchestrator(bus)
    sl  = _make_sl(orchestrator=orc, rate_limit=1, now_fn=lambda: fixed_dt)

    sl.validate_rate_limit("11.0.0.1", "/api/buy")

    try:
        sl.validate_rate_limit("11.0.0.1", "/api/buy")
    except RateLimitExceededError:
        pass

    logs = sl._pers.load_all()
    assert any(e["status"] == "BLOCKED" and e["ip"] == "11.0.0.1" for e in logs), (
        "Expected BLOCKED log entry for 11.0.0.1"
    )


def t6_client_side_blocked():
    """Critical events with source='client' raise ClientSideExecutionBlockedError."""
    sl  = _make_sl()
    bus = EventBus()

    critical_events = [
        "pricing_offensive_requested",
        "pricing_defensive_requested",
        "version_promotion_requested",
        "version_rollback_requested",
        "market_cycle_start_requested",
        "post_beta_consolidation_requested",
    ]

    for evt in critical_events:
        raised = False
        try:
            sl.validate_source(evt, "client")
        except ClientSideExecutionBlockedError:
            raised = True
        assert raised, f"Expected ClientSideExecutionBlockedError for '{evt}' from client"

    # Non-critical events from client should be fine
    sl.validate_source("read_product_data", "client")   # no error


def t7_client_role_cannot_promote():
    """CLIENT role raises PermissionDeniedError for version_promotion."""
    sl = _make_sl()

    raised = False
    try:
        sl.validate_permission("CLIENT", "version_promotion")
    except PermissionDeniedError:
        raised = True
    assert raised, "Expected PermissionDeniedError for CLIENT role on version_promotion"

    raised2 = False
    try:
        sl.validate_permission("CLIENT", "price_update")
    except PermissionDeniedError:
        raised2 = True
    assert raised2, "Expected PermissionDeniedError for CLIENT role on price_update"


def t8_admin_can_promote():
    """ADMIN role is permitted for version_promotion, price_update, rollback."""
    sl = _make_sl()

    assert sl.validate_permission("ADMIN", "version_promotion") is True
    assert sl.validate_permission("ADMIN", "price_update") is True
    assert sl.validate_permission("ADMIN", "rollback") is True

    # SYSTEM gets everything
    assert sl.validate_permission("SYSTEM", "any_internal_action") is True


def t9_direct_write_fails():
    """StateManager.set() raises DirectWriteError — no direct writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("security_bypass", True)
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A9 SECURITY LAYER — TEST SUITE")
    print("=" * 62)

    test("Webhook inválido bloqueado",                t1_invalid_webhook_blocked)
    test("Webhook válido permitido",                  t2_valid_webhook_permitted)
    test("Rate limit bloqueia após limite",           t3_rate_limit_blocks)
    test("IP logging registra ALLOWED",               t4_ip_logging_allowed)
    test("IP logging registra BLOCKED",               t5_ip_logging_blocked)
    test("Client-side bloqueado para price_update",   t6_client_side_blocked)
    test("CLIENT role não pode promover versão",      t7_client_role_cannot_promote)
    test("ADMIN pode promover versão",                t8_admin_can_promote)
    test("DirectWriteError fora do Orchestrator",     t9_direct_write_fails)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A9 SECURITY LAYER — VALID")
        print("  A9 SECURITY LAYER LOCKED")
    else:
        print("  A9 SECURITY LAYER — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
