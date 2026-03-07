"""
core/dashboard_service.py — A13 Dashboard Governance Layer

100% passive read-only service. Rules:
  - No engine mutations: all reads are non-destructive
  - Buttons emit events ONLY via Orchestrator.receive_event()
  - No strategic logic: no if/else decisions on metrics
  - No direct engine execution: DashboardDirectExecutionError if attempted
  - No calculations: RPM, ROAS, eligibility decisions live in their own engines

Domain exceptions:
  DashboardDirectExecutionError  — attempt to call engine methods directly
  DashboardStrategicLogicError   — strategic logic detected inside dashboard
"""
from infrastructure.logger import get_logger

logger = get_logger("DashboardService")


# ---------------------------------------------------------------------------
# Domain Exceptions
# ---------------------------------------------------------------------------

class DashboardDirectExecutionError(Exception):
    """Raised when dashboard code attempts to call an engine method directly."""

class DashboardStrategicLogicError(Exception):
    """
    Raised when the dashboard attempts to make a strategic decision.
    All decisions (pricing, eligibility, phase) belong to their engines.
    """


# ---------------------------------------------------------------------------
# Dashboard Service
# ---------------------------------------------------------------------------

class DashboardService:
    """
    Passive read-only gateway for the Autonomous System dashboard.

    Injected sources (all optional — missing sources return empty/None):
      telemetry       — TelemetryEngine or compatible duck type
      finance         — FinanceEngine or compatible duck type
      global_state    — GlobalState or compatible duck type
      strategic_memory — StrategicMemoryEngine or compatible duck type
      uptime          — UptimeEngine or compatible duck type
      version_manager — VersionManager or compatible duck type
      pricing_engine  — PricingEngine or compatible duck type
      market_loop     — MarketLoopEngine or compatible duck type
      orchestrator    — Orchestrator (for action buttons)

    All read methods are non-destructive.
    All action methods call only Orchestrator.receive_event().
    """

    def __init__(
        self,
        *,
        telemetry=None,
        finance=None,
        global_state=None,
        strategic_memory=None,
        uptime=None,
        version_manager=None,
        pricing_engine=None,
        market_loop=None,
        orchestrator=None,
    ):
        self._telemetry       = telemetry
        self._finance         = finance
        self._global_state    = global_state
        self._strategic_memory = strategic_memory
        self._uptime          = uptime
        self._vm              = version_manager
        self._pricing         = pricing_engine
        self._market_loop     = market_loop
        self._orchestrator    = orchestrator

        logger.info("DashboardService initialized (read-only).")

    # ==================================================================
    # READ-ONLY VIEWS
    # ==================================================================

    def get_product_overview(self, product_id: str) -> dict:
        """
        Aggregate read-only product data from multiple engines.
        Returns a plain dict — no calculations, no decisions.
        """
        overview: dict = {"product_id": product_id}

        # Uptime
        if self._uptime:
            rec = self._uptime.get_record(product_id)
            overview["uptime"] = rec

        # Version
        if self._vm:
            try:
                overview["version"] = self._vm.get_current_version(product_id)
            except Exception:
                overview["version"] = None

        # Pricing
        if self._pricing:
            try:
                overview["pricing"] = self._pricing.get_state(product_id)
            except Exception:
                overview["pricing"] = None

        # Market loop
        if self._market_loop:
            try:
                overview["market_cycle"] = self._market_loop.get_current_cycle(product_id)
            except Exception:
                overview["market_cycle"] = None

        return overview

    def get_financial_overview(self) -> dict:
        """Return current financial projections from FinanceEngine — read-only."""
        if self._finance is None:
            return {}
        try:
            return self._finance.get_financial_projection()
        except Exception:
            return {}

    def get_global_state(self) -> dict:
        """Return the current global financial/operational state — read-only."""
        if self._global_state is None:
            return {}
        try:
            return self._global_state.get_state()
        except Exception:
            return {}

    def get_monthly_memory(self, product_id: str) -> list[dict]:
        """Return all consolidated monthly records for a product — read-only."""
        if self._strategic_memory is None:
            return []
        try:
            return self._strategic_memory.get_all_records(product_id)
        except Exception:
            return []

    def get_market_cycle_status(self, product_id: str) -> dict | None:
        """Return the current market cycle state for a product — read-only."""
        if self._market_loop is None:
            return None
        try:
            return self._market_loop.get_current_cycle(product_id)
        except Exception:
            return None

    # ==================================================================
    # ACTION BUTTONS (emit events via Orchestrator only)
    # ==================================================================

    def _emit(self, event_type: str, payload: dict) -> None:
        """
        Internal routing: emit an event via Orchestrator.
        Raises DashboardDirectExecutionError if Orchestrator is not injected.
        """
        if self._orchestrator is None:
            raise DashboardDirectExecutionError(
                f"DashboardService has no Orchestrator injected. "
                f"Cannot emit event '{event_type}' without going through the Orchestrator. "
                f"Direct engine calls from Dashboard are forbidden."
            )
        self._orchestrator.receive_event(event_type, payload)
        logger.info(f"Dashboard emitted event: {event_type} payload={payload}")

    def start_beta(self, product_id: str) -> None:
        """Emit beta_start_requested via Orchestrator."""
        self._emit("beta_start_requested", {"product_id": product_id})

    def pause_product(self, product_id: str) -> None:
        """Emit product_pause_requested via Orchestrator."""
        self._emit("product_pause_requested", {"product_id": product_id})

    def resume_product(self, product_id: str) -> None:
        """Emit product_resume_requested via Orchestrator."""
        self._emit("product_resume_requested", {"product_id": product_id})

    def start_market_cycle(self, product_id: str) -> None:
        """Emit market_cycle_start_requested via Orchestrator."""
        self._emit(
            "market_cycle_start_requested",
            {"product_id": product_id, "source": "dashboard"},
        )

    def apply_offensive_pricing(self, product_id: str) -> None:
        """Emit pricing_offensive_requested via Orchestrator."""
        self._emit(
            "pricing_offensive_requested",
            {"product_id": product_id, "source": "dashboard"},
        )

    def monthly_consolidation(self, product_id: str, month_id: str) -> None:
        """Emit monthly_consolidation_requested via Orchestrator."""
        self._emit(
            "monthly_consolidation_requested",
            {"product_id": product_id, "month_id": month_id, "source": "dashboard"},
        )

    # ==================================================================
    # Static guard: document the prohibition of direct engine calls
    # ==================================================================

    @staticmethod
    def execute_engine_directly(*args, **kwargs) -> None:
        """
        Always raises DashboardDirectExecutionError.
        All engine execution must go through Orchestrator.receive_event().
        """
        raise DashboardDirectExecutionError(
            "execute_engine_directly() is permanently forbidden. "
            "Dashboard actions must route through Orchestrator.receive_event(). "
            "A13 Dashboard Governance: zero direct engine calls permitted."
        )

    @staticmethod
    def apply_strategic_logic(*args, **kwargs) -> None:
        """
        Always raises DashboardStrategicLogicError.
        Strategic decisions belong to their respective engines, not the dashboard.
        """
        raise DashboardStrategicLogicError(
            "apply_strategic_logic() is permanently forbidden inside DashboardService. "
            "RPM, ROAS, pricing eligibility, and phase decisions belong to "
            "PricingEngine / MarketLoopEngine / TelemetryEngine. "
            "Dashboard is 100% passive."
        )
