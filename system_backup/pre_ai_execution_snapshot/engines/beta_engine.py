"""
engines/beta_engine.py — Multi-Cycle Beta Engine (Migrated)
All state writes routed through Orchestrator.receive_event().
"""
import copy
from infrastructure.logger import get_logger

logger = get_logger("BetaEngine")

BETA_TICK_THRESHOLD = 3


class BetaEngine:
    """
    Iterates all BETA_ACTIVE cycles on each cycle_tick.
    Transitions individual cycles → CYCLE_ACTIVE after BETA_TICK_THRESHOLD ticks.
    Reads via orchestrator.state.get(); writes via orchestrator.receive_event().
    """

    def __init__(self, event_bus, orchestrator):
        self.bus  = event_bus
        self.orch = orchestrator
        self.bus.subscribe("cycle_started", self._on_cycle_started)
        self.bus.subscribe("cycle_tick",    self._on_cycle_tick)
        logger.info("BetaEngine initialized.")

    def _on_cycle_started(self, payload: dict) -> None:
        """Ensure duration_ticks_beta is initialized for the new cycle."""
        str_cid = str(payload.get("cycle_id"))
        active_cycles = copy.deepcopy(self.orch.state.get("active_cycles", {}))
        cycle = active_cycles.get(str_cid)

        if cycle and isinstance(cycle, dict):
            cycle.setdefault("duration_ticks_beta", 0)
            active_cycles[str_cid] = cycle
            self.orch.receive_event(
                "active_cycles_updated", {"active_cycles": active_cycles}
            )
        logger.info(f"BetaEngine tracking cycle #{str_cid}.")

    def _on_cycle_tick(self, payload: dict) -> None:
        active_cycles = copy.deepcopy(self.orch.state.get("active_cycles", {}))
        if not active_cycles:
            return

        to_promote = []
        modified   = False

        for str_cid, cycle in active_cycles.items():
            if not isinstance(cycle, dict) or cycle.get("phase") != "BETA_ACTIVE":
                continue

            cycle["duration_ticks_beta"] = cycle.get("duration_ticks_beta", 0) + 1
            modified = True

            if cycle["duration_ticks_beta"] >= BETA_TICK_THRESHOLD:
                to_promote.append(str_cid)

        if modified:
            self.orch.receive_event(
                "active_cycles_updated", {"active_cycles": active_cycles}
            )

        for str_cid in to_promote:
            self._promote_cycle(str_cid)

    def _promote_cycle(self, str_cid: str) -> None:
        active_cycles = copy.deepcopy(self.orch.state.get("active_cycles", {}))
        cycle = active_cycles.get(str_cid)
        if not cycle:
            return

        cycle["phase"]                 = "CYCLE_ACTIVE"
        cycle["duration_ticks_active"] = 0
        active_cycles[str_cid]         = cycle

        self.orch.receive_event(
            "active_cycles_updated", {"active_cycles": active_cycles}
        )
        logger.info(
            f"Cycle #{str_cid}: BETA_ACTIVE → CYCLE_ACTIVE "
            f"(beta_ticks={cycle['duration_ticks_beta']})"
        )
        self.bus.emit("beta_completed", cycle)
