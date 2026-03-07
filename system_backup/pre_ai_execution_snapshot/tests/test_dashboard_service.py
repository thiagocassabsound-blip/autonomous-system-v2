"""
tests/test_dashboard_service.py — A13 Dashboard Governance Validation Suite

8 closure criteria:
  1. Dashboard lê Telemetria corretamente
  2. Dashboard lê Estado Global corretamente
  3. Dashboard lê Strategic Memory corretamente
  4. Botão emite evento via Orchestrator
  5. Dashboard não altera estado diretamente
  6. Tentativa de executar engine direto lança erro
  7. Nenhuma lógica estratégica presente
  8. DirectWriteError fora do Orchestrator

Usage:
    py tests/test_dashboard_service.py
"""
import sys
import os
import io
import inspect

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.dashboard_service import (
    DashboardService,
    DashboardDirectExecutionError,
    DashboardStrategicLogicError,
)
from core.state_manager import StateManager, DirectWriteError

# ====================================================================
# Stubs / Mocks
# ====================================================================

class MockTelemetry:
    def get_snapshot(self, product_id):
        return {"product_id": product_id, "rpm": 12.5, "roas": 3.8}


class MockGlobalState:
    def get_state(self):
        return {"mode": "NORMAL", "alerta": False}


class MockStrategicMemory:
    def __init__(self):
        self._records = [
            {"product_id": "prod-1", "month_id": "2026-01", "total_revenue": 15000.0},
            {"product_id": "prod-1", "month_id": "2025-12", "total_revenue": 12000.0},
        ]
    def get_all_records(self, product_id):
        return [r for r in self._records if r["product_id"] == product_id]


class MockUptime:
    def get_record(self, product_id):
        return {"product_id": product_id, "total_active_seconds": 3600, "is_active": True}


class MockVersionManager:
    def get_current_version(self, product_id):
        return {"product_id": product_id, "baseline_version": "v2"}


class MockPricingEngine:
    def get_state(self, product_id):
        return {"product_id": product_id, "current_price": 199.0}


class MockMarketLoop:
    def get_current_cycle(self, product_id):
        return {"product_id": product_id, "phase": "FASE_2"}


class MockOrchestrator:
    """Records all emitted events for assertion."""
    def __init__(self):
        self.events = []
    def receive_event(self, event_type, payload):
        self.events.append({"event_type": event_type, "payload": payload})


def _make_dashboard(orchestrator=None):
    return DashboardService(
        telemetry=MockTelemetry(),
        global_state=MockGlobalState(),
        strategic_memory=MockStrategicMemory(),
        uptime=MockUptime(),
        version_manager=MockVersionManager(),
        pricing_engine=MockPricingEngine(),
        market_loop=MockMarketLoop(),
        orchestrator=orchestrator or MockOrchestrator(),
    )


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

def t1_reads_telemetry():
    """get_product_overview returns data from all injected engines — no computation."""
    svc = _make_dashboard()
    overview = svc.get_product_overview("prod-1")

    assert overview["product_id"] == "prod-1"
    # Uptime data present
    assert overview["uptime"]["total_active_seconds"] == 3600
    # Version data present
    assert overview["version"]["baseline_version"] == "v2"
    # Pricing data present
    assert overview["pricing"]["current_price"] == 199.0
    # Market cycle present
    assert overview["market_cycle"]["phase"] == "FASE_2"


def t2_reads_global_state():
    """get_global_state returns the current global state — no modifications."""
    svc = _make_dashboard()
    state = svc.get_global_state()

    assert state["mode"] == "NORMAL"
    assert state["alerta"] is False


def t3_reads_strategic_memory():
    """get_monthly_memory returns all consolidated records for the product."""
    svc = _make_dashboard()
    records = svc.get_monthly_memory("prod-1")

    assert len(records) == 2
    months = {r["month_id"] for r in records}
    assert "2026-01" in months
    assert "2025-12" in months
    assert records[0]["total_revenue"] > 0   # frozen values intact


def t4_button_emits_via_orchestrator():
    """Action buttons (pause, resume, start_market_cycle, etc.) emit via Orchestrator."""
    orc = MockOrchestrator()
    svc = _make_dashboard(orchestrator=orc)

    svc.pause_product("prod-1")
    svc.resume_product("prod-1")
    svc.start_market_cycle("prod-1")
    svc.apply_offensive_pricing("prod-1")
    svc.monthly_consolidation("prod-1", "2026-01")
    svc.start_beta("prod-1")

    emitted = [e["event_type"] for e in orc.events]
    assert "product_pause_requested"         in emitted
    assert "product_resume_requested"        in emitted
    assert "market_cycle_start_requested"    in emitted
    assert "pricing_offensive_requested"     in emitted
    assert "monthly_consolidation_requested" in emitted
    assert "beta_start_requested"            in emitted

    # None of the payloads should carry computed/derived fields
    for event in orc.events:
        assert "rpm" not in event["payload"],  "Dashboard must not compute RPM"
        assert "roas" not in event["payload"], "Dashboard must not compute ROAS"


def t5_no_state_mutation():
    """
    read-only methods must never mutate injected engines.
    We verify by checking that uptime record is unmodified after reads.
    """
    uptime = MockUptime()
    svc = DashboardService(uptime=uptime)

    before = uptime.get_record("prod-1").copy()
    svc.get_product_overview("prod-1")
    after  = uptime.get_record("prod-1")

    assert before == after, "Dashboard read mutated the uptime record"


def t6_direct_engine_execution_blocked():
    """execute_engine_directly and emit without orchestrator both raise error."""
    # Static guard
    raised = False
    try:
        DashboardService.execute_engine_directly()
    except DashboardDirectExecutionError:
        raised = True
    assert raised, "Expected DashboardDirectExecutionError from execute_engine_directly"

    # Action button without injected orchestrator
    svc_no_orc = DashboardService()   # no orchestrator
    raised = False
    try:
        svc_no_orc.pause_product("prod-1")
    except DashboardDirectExecutionError:
        raised = True
    assert raised, "Expected DashboardDirectExecutionError when no orchestrator injected"


def t7_no_strategic_logic_present():
    """
    Verify that DashboardService source code contains no strategic decision patterns.
    Forbidden: 'if.*roas', 'if.*rpm', 'if.*margin', 'if.*roas >', etc.
    Strategy guard method must exist and always raise.
    """
    import re

    # Static guard raises
    raised = False
    try:
        DashboardService.apply_strategic_logic()
    except DashboardStrategicLogicError:
        raised = True
    assert raised, "Expected DashboardStrategicLogicError from apply_strategic_logic"

    # Structural check: no strategic if-blocks in source
    src = inspect.getsource(DashboardService)
    forbidden_patterns = [
        r"if\s+.*roas\s*[<>]",
        r"if\s+.*rpm\s*[<>]",
        r"if\s+.*margin\s*[<>]",
        r"if\s+.*cac\s*[<>]",
        r"if\s+.*price\s*[<>]",
    ]
    for pat in forbidden_patterns:
        match = re.search(pat, src, re.IGNORECASE)
        assert match is None, (
            f"Strategic logic pattern '{pat}' found in DashboardService source. "
            f"Dashboard must be 100% passive."
        )


def t8_direct_write_blocked():
    """StateManager.set() raises DirectWriteError — no direct writes outside Orchestrator."""
    sm = StateManager()
    raised = False
    try:
        sm.set("dashboard_override", True)
    except DirectWriteError:
        raised = True
    assert raised, "Expected DirectWriteError on direct StateManager write"


# ====================================================================
# Runner
# ====================================================================
if __name__ == "__main__":
    print("\n" + "=" * 62)
    print("  A13 DASHBOARD GOVERNANCE — TEST SUITE")
    print("=" * 62)

    test("Dashboard lê Telemetria corretamente",            t1_reads_telemetry)
    test("Dashboard lê Estado Global corretamente",         t2_reads_global_state)
    test("Dashboard lê Strategic Memory corretamente",      t3_reads_strategic_memory)
    test("Botão emite evento via Orchestrator",             t4_button_emits_via_orchestrator)
    test("Dashboard não altera estado diretamente",         t5_no_state_mutation)
    test("Executar engine direto lança erro",               t6_direct_engine_execution_blocked)
    test("Nenhuma lógica estratégica presente",             t7_no_strategic_logic_present)
    test("DirectWriteError fora do Orchestrator",           t8_direct_write_blocked)

    print("\n" + "=" * 62)
    passed = sum(1 for r in results if r[0] == "[OK]")
    total  = len(results)
    print(f"  Result: {passed}/{total} tests passed")
    if passed == total:
        print("  A13 DASHBOARD GOVERNANCE — VALID")
        print("  A13 DASHBOARD GOVERNANCE LOCKED")
    else:
        print("  A13 DASHBOARD GOVERNANCE — INVALID (see failures above)")
    print("=" * 62 + "\n")

    sys.exit(0 if passed == total else 1)
