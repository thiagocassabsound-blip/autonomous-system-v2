"""
core/state_manager.py — Write-Protected State Manager
Direct writes raise DirectWriteError unless unlocked by Orchestrator._write_context().
"""
import copy
from infrastructure.logger import get_logger

logger = get_logger("StateManager")


class DirectWriteError(Exception):
    """
    Raised when any code outside Orchestrator._write_context()
    attempts to call state_manager.set() or state_manager.delete().
    """


# Default structures always guaranteed to exist
_DEFAULTS: dict = {
    "active_cycles":    {},
    "cycle_history":    [],
    "processed_events": [], # Idempotency Index (event_id list)
    "metrics": {
        "total_cycles":        0,
        "total_opportunities": 0,
        "avg_score":           0.0,
        "beta_success_rate":   0.0,
    },
}


def _autocorrect(state: dict) -> dict:
    """
    Validate and repair known state keys on startup.
    Migrates stale active_cycle → active_cycles if found.
    """
    # Migrate legacy singular active_cycle
    if "active_cycle" in state:
        old = state.pop("active_cycle")
        if isinstance(old, dict) and "cycle_id" in old:
            str_cid = str(old["cycle_id"])
            state.setdefault("active_cycles", {})
            if str_cid not in state["active_cycles"]:
                state["active_cycles"][str_cid] = old
                logger.warning(
                    f"Autocorrect: migrated stale active_cycle #{str_cid} → active_cycles."
                )
        else:
            logger.warning("Autocorrect: stale active_cycle was invalid — discarded.")

    # active_cycles must be a dict
    if not isinstance(state.get("active_cycles"), dict):
        logger.warning("Autocorrect: active_cycles invalid → {}.")
        state["active_cycles"] = {}
    else:
        bad = [k for k, v in state["active_cycles"].items() if not isinstance(v, dict)]
        for k in bad:
            del state["active_cycles"][k]
            logger.warning(f"Autocorrect: active_cycles[{k}] invalid → removed.")

    # cycle_history must be a list
    if not isinstance(state.get("cycle_history"), list):
        logger.warning("Autocorrect: cycle_history invalid → [].")
        state["cycle_history"] = []

    # processed_events must be a list
    if not isinstance(state.get("processed_events"), list):
        logger.warning("Autocorrect: processed_events invalid → [].")
        state["processed_events"] = []

    # metrics must be a dict with all required keys
    metrics = state.get("metrics")
    if not isinstance(metrics, dict):
        logger.warning("Autocorrect: metrics invalid → reset.")
        state["metrics"] = copy.deepcopy(_DEFAULTS["metrics"])
    else:
        for key, default in _DEFAULTS["metrics"].items():
            if key not in metrics:
                metrics[key] = default
                logger.warning(f"Autocorrect: metrics['{key}'] missing → {default}.")
        state["metrics"] = metrics

    return state


class StateManager:
    """
    In-memory key-value store with:
    - File persistence via FilePersistence
    - Write-protection: set()/delete() raise DirectWriteError when _locked=True
    - Autocorrection of known structures on startup
    - Default keys guaranteed on init

    Write pattern (Orchestrator only):
        state._locked = False
        state.set(...)
        state._locked = True

    Preferred: use Orchestrator._write_context() context manager.
    """

    def __init__(self, persistence=None):
        # Unlocked during init — bootstrapping writes are allowed
        self._locked      = False
        self._persistence = persistence
        self._state: dict = {}

        # Load from persistence
        if self._persistence:
            self._state = self._persistence.load()

        # Initialize missing default keys
        for key, default in _DEFAULTS.items():
            if key not in self._state:
                self._state[key] = copy.deepcopy(default)

        # Repair corrupted structures
        self._state = _autocorrect(self._state)

        logger.info(
            f"StateManager initialized ({len(self._state)} keys, "
            f"active_cycles={len(self._state.get('active_cycles', {}))}, "
            f"history={len(self._state.get('cycle_history', []))}). "
            f"Write-lock ACTIVE."
        )

        # Lock after initialization
        self._locked = True

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set(self, key: str, value) -> None:
        if self._locked:
            raise DirectWriteError(
                f"Direct write to state['{key}'] is forbidden. "
                "All writes must go through Orchestrator.receive_event()."
            )
        self._state[key] = value
        logger.debug(f"State SET: {key}")
        if self._persistence:
            self._persistence.save(self._state)

    def get(self, key: str, default=None):
        """Always allowed — reads are never locked."""
        return self._state.get(key, default)

    def delete(self, key: str) -> None:
        if self._locked:
            raise DirectWriteError(
                f"Direct delete of state['{key}'] is forbidden. "
                "All writes must go through Orchestrator.receive_event()."
            )
        if key in self._state:
            del self._state[key]
            logger.debug(f"State DELETED: {key}")
            if self._persistence:
                self._persistence.save(self._state)

    def all(self) -> dict:
        return copy.deepcopy(self._state)
