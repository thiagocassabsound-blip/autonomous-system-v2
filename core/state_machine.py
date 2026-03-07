"""
core/state_machine.py — Product Lifecycle State Machine
Governs formal product state transitions with event emission and persistence.
"""
from datetime import datetime, timezone
from infrastructure.logger import get_logger

logger = get_logger("StateMachine")

STRICT_MODE = True

# ------------------------------------------------------------------
# Valid states
# ------------------------------------------------------------------
VALID_STATES: frozenset = frozenset({
    "Draft",
    "Beta",
    "Ativo",
    "Ads_Pausado",
    "Ads_Beta",
    "Escalando",
    "Defesa_Preço",
    "Ataque_Preço",
    "Pausado_Estratégico",
    "Inativo",
    "Arquivado",
})

# ------------------------------------------------------------------
# Valid transitions: current_state → set of allowed next states
# Arquivado is terminal — no exits.
# ------------------------------------------------------------------
VALID_TRANSITIONS: dict = {
    "Draft":               {"Beta", "Inativo"},
    "Beta":                {"Ativo", "Inativo", "Draft"},
    "Ativo":               {
        "Ads_Pausado", "Ads_Beta", "Escalando",
        "Defesa_Preço", "Ataque_Preço",
        "Pausado_Estratégico", "Inativo",
    },
    "Ads_Pausado":         {"Ativo", "Inativo"},
    "Ads_Beta":            {"Ativo", "Inativo"},
    "Escalando":           {"Ativo", "Defesa_Preço", "Pausado_Estratégico"},
    "Defesa_Preço":        {"Ativo", "Ataque_Preço", "Escalando"},
    "Ataque_Preço":        {"Ativo", "Defesa_Preço", "Escalando"},
    "Pausado_Estratégico": {"Ativo", "Inativo", "Arquivado"},
    "Inativo":             {"Arquivado", "Draft"},
    "Arquivado":           set(),   # terminal
}


class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted by the machine."""


class InvalidStateError(Exception):
    """Raised when an unknown state name is used."""


class StateMachine:
    """
    Persistent product lifecycle state machine.
    All transitions must be formal and are recorded as ledger events.
    """

    def __init__(self, persistence=None):
        self._orchestrated_context = False
        self._persistence = persistence
        self._product_states: dict = {}   # product_id → current state
        self._history: list = []          # all transition records

        if persistence:
            data = persistence.load()
            if isinstance(data, dict):
                self._product_states = data.get("product_states", {})
                self._history        = data.get("history", [])

        logger.info(
            f"StateMachine initialized. "
            f"Products tracked: {len(self._product_states)}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self, product_id: str) -> str:
        """Return current state, defaulting to 'Draft'."""
        return self._product_states.get(str(product_id), "Draft")

    def _enter_orchestrated_context(self):
        self._orchestrated_context = True

    def _exit_orchestrated_context(self):
        self._orchestrated_context = False

    def transition(
        self,
        product_id: str,
        new_state: str,
        reason: str,
        metric: str | None,
        orchestrator,
    ) -> dict:
        """
        Execute a state transition.
        - Raises InvalidStateError  if new_state is unknown.
        - Raises InvalidTransitionError if the move is not permitted.
        - Appends a formal ledger event on success.
        """
        product_id = str(product_id)
        current = self.get_state(product_id)

        from core.legacy_write_bridge import LegacyWriteBridge
        LegacyWriteBridge.intercept_state_write(current, new_state)

        if STRICT_MODE and not self._orchestrated_context:
            raise RuntimeError(
                f"STRICT_MODE_VIOLATION: state machine transition. "
                f"product={product_id} to_state={new_state}"
            )
        if new_state not in VALID_STATES:
            raise InvalidStateError(
                f"Unknown state: '{new_state}'. "
                f"Valid states: {sorted(VALID_STATES)}"
            )


        allowed = VALID_TRANSITIONS.get(current, set())

        if new_state not in allowed:
            raise InvalidTransitionError(
                f"Transition '{current}' → '{new_state}' is not permitted "
                f"for product '{product_id}'. "
                f"Allowed: {sorted(allowed) if allowed else '[none — terminal state]'}"
            )

        record = {
            "product_id":  product_id,
            "from_state":  current,
            "to_state":    new_state,
            "reason":      reason,
            "metric":      metric,
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }

        self._product_states[product_id] = new_state
        self._history.append(record)
        self._save()

        orchestrator.emit_event(
            event_type="state_transitioned",
            product_id=product_id,
            payload=record
        )

        logger.info(
            f"Product '{product_id}': {current} → {new_state} "
            f"(reason={reason}, metric={metric})"
        )
        return record

    def get_history(self, product_id: str) -> list:
        return [r for r in self._history if r.get("product_id") == str(product_id)]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _save(self) -> None:
        if self._persistence:
            self._persistence.save({
                "product_states": self._product_states,
                "history":        self._history,
            })
