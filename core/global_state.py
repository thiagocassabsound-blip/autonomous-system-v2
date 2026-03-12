"""
core/global_state.py — System-Wide Financial Global State
Three-level state machine: NORMAL → ALERTA_FINANCEIRO → CONTENÇÃO_FINANCEIRA
State is updated by FinanceEngine and consulted by Orchestrator before sensitive actions.
"""
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("GlobalState")

STRICT_MODE = True

# ------------------------------------------------------------------
# Valid system-level states
# ------------------------------------------------------------------
NORMAL               = "NORMAL"
ALERTA_FINANCEIRO    = "ALERTA_FINANCEIRO"
CONTENCAO_FINANCEIRA = "CONTENÇÃO_FINANCEIRA"

VALID_GLOBAL_STATES: frozenset = frozenset({
    NORMAL,
    ALERTA_FINANCEIRO,
    CONTENCAO_FINANCEIRA,
})

TRAFFIC_MANUAL   = "manual"
TRAFFIC_ADS      = "ads"
TRAFFIC_DISABLED = "disabled"

VALID_TRAFFIC_MODES: frozenset = frozenset({
    TRAFFIC_MANUAL,
    TRAFFIC_ADS,
    TRAFFIC_DISABLED,
})


class GlobalState:
    """
    System-wide financial health state.
    Transitions trigger formal ledger events (global_state_updated).

    Consulted by Orchestrator before executing sensitive operations.
    Updated exclusively by FinanceEngine.validate_financial_health().
    """

    def __init__(self, orchestrator, persistence=None):
        self._orchestrated_context = False
        self.orchestrator = orchestrator
        self._persistence = persistence
        self._state: str = NORMAL

        if persistence:
            data = persistence.load()
            loaded = data.get("state", NORMAL)
            if loaded in VALID_GLOBAL_STATES:
                self._state = loaded
            
            import os
            self._traffic_mode = data.get("traffic_mode") or os.getenv("TRAFFIC_MODE", TRAFFIC_MANUAL)
            if self._traffic_mode not in VALID_TRAFFIC_MODES:
                self._traffic_mode = TRAFFIC_MANUAL
            
            self._ads_system_mode = data.get("ads_system_mode") or os.getenv("ADS_SYSTEM_MODE", "enabled")
        else:
            import os
            self._traffic_mode = os.getenv("TRAFFIC_MODE", TRAFFIC_MANUAL)
            self._ads_system_mode = os.getenv("ADS_SYSTEM_MODE", "enabled")

        logger.info(f"GlobalState initialized: {self._state} (Traffic: {self._traffic_mode}, Ads: {self._ads_system_mode})")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self) -> str:
        return self._state

    def get_traffic_mode(self) -> str:
        return self._traffic_mode

    def get_ads_system_mode(self) -> str:
        """Returns 'enabled' or 'disabled'."""
        return self._ads_system_mode

    def set_ads_system_mode(self, mode: str, orchestrated: bool = False):
        """Toggle global ads control. Mode must be 'enabled' or 'disabled'."""
        if mode not in ["enabled", "disabled"]:
            raise ValueError("Ads mode must be 'enabled' or 'disabled'")
        
        if STRICT_MODE and not orchestrated:
             raise RuntimeError("STRICT_MODE_VIOLATION: global ads mode write.")

        self._ads_system_mode = mode
        if self._persistence:
            current = self._persistence.load()
            current["ads_system_mode"] = mode
            self._persistence.save(current)
        
        logger.info(f"Global Ads System Mode set to: {mode}")

    def _enter_orchestrated_context(self):
        self._orchestrated_context = True

    def _exit_orchestrated_context(self):
        self._orchestrated_context = False

    def request_state_update(self, new_value: str, reason: str = "", source: str = None, orchestrated: bool = False) -> dict:
        """
        Public entry point for state updates.
        If not orchestrated, logs a legacy warning.
        """
        from core.legacy_write_bridge import LegacyWriteBridge
        old_state = self.get_state()
        
        if orchestrated:
            # Authorized write - log for observability without warning
            LegacyWriteBridge.intercept_global_state_write(
                old_state, 
                new_value, 
                legacy_warning=False
            )
            return self._update_state_internal(new_value, reason)
        else:
            # Unauthorized/Legacy write - log with warning
            LegacyWriteBridge.intercept_global_state_write(
                old_state, 
                new_value, 
                legacy_warning=True, 
                severity="GLOBAL_STATE_DIRECT_WRITE"
            )
            logger.warning(f"legacy_global_state_write_detected: origin={source or 'unknown'}")
            return self._update_state_internal(new_value, event_bus, reason)

    def _update_state_internal(self, new_state: str, reason: str = "") -> dict:
        """
        Internal transition logic (semi-private). 
        Should only be called via request_state_update.
        """
        if STRICT_MODE and not self._orchestrated_context:
            raise RuntimeError(
                f"STRICT_MODE_VIOLATION: global state write. "
                f"new_state={new_state} reason={reason}"
            )
        if new_state not in VALID_GLOBAL_STATES:
            raise ValueError(
                f"Invalid global state: '{new_state}'. "
                f"Valid: {sorted(VALID_GLOBAL_STATES)}"
            )

        old_state = self._state
        self._state = new_state

        if self._persistence:
            self._persistence.save({
                "state":             new_state,
                "last_updated":      datetime.now(timezone.utc).isoformat(),
                "reason":            reason,
                "traffic_mode":      self._traffic_mode,
                "ads_system_mode":   self._ads_system_mode,
            })

        if old_state != new_state:
            self.orchestrator.emit_event(
                event_type="global_state_updated",
                payload={
                    "from":    old_state,
                    "to":      new_state,
                    "reason":  reason,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
                source="system",
            )
            logger.info(f"GlobalState: {old_state} → {new_state} (reason={reason})")

        return {"from": old_state, "to": new_state}
