"""
engines/cycle_engine.py — Multi-Cycle Lifecycle Manager (Migrated)
All state writes routed through Orchestrator.receive_event().
"""
import copy
import time
from infrastructure.logger import get_logger

logger = get_logger("CycleEngine")

CYCLE_ACTIVE_TICK_THRESHOLD = 5


def _resolve_next_cycle_id(history: list, active_cycles: dict) -> int:
    max_id = 0
    for entry in history:
        if isinstance(entry, dict):
            max_id = max(max_id, entry.get("cycle_id", 0))
    for cid in active_cycles:
        try:
            max_id = max(max_id, int(cid))
        except (ValueError, TypeError):
            pass
    return max_id


class CycleEngine:
    """
    Full multi-cycle lifecycle manager.
    Reads state via orchestrator.state.get().
    Writes state exclusively via orchestrator.receive_event().
    """

    def __init__(self, event_bus, orchestrator):
        self.bus  = event_bus
        self.orch = orchestrator

        history       = self.orch.state.get("cycle_history", [])
        active_cycles = self.orch.state.get("active_cycles", {})
        self._last_cycle_id = _resolve_next_cycle_id(history, active_cycles)
        logger.info(f"CycleEngine initialized. Last cycle_id={self._last_cycle_id}.")

        self.bus.subscribe("opportunity_detected", self._on_opportunity_detected)
        self.bus.subscribe("score_computed",       self._on_score_computed)
        self.bus.subscribe("cycle_tick",           self._on_cycle_tick)

    # ------------------------------------------------------------------
    # Metrics (computed locally, written via orchestrator)
    # ------------------------------------------------------------------

    def _compute_metrics(self, history: list) -> dict:
        metrics = self.orch.state.get("metrics", {}).copy()
        total   = len(history)
        scores  = [c.get("score", 0) for c in history if isinstance(c, dict)]
        avg     = sum(scores) / len(scores) if scores else 0.0
        beta_ok = sum(1 for c in history if c.get("duration_ticks_beta", 0) > 0)
        rate    = (beta_ok / total * 100) if total > 0 else 0.0

        metrics["total_cycles"]      = total
        metrics["avg_score"]         = round(avg, 2)
        metrics["beta_success_rate"] = round(rate, 2)
        return metrics

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _on_opportunity_detected(self, payload: dict) -> None:
        self.orch.receive_event("opportunity_counted", {})

    def _on_score_computed(self, payload: dict) -> None:
        self._last_cycle_id += 1
        str_cid = str(self._last_cycle_id)

        cycle = {
            "cycle_id":              self._last_cycle_id,
            "opportunity_id":        payload.get("id"),
            "score":                 payload.get("score_final"),
            "phase":                 "BETA_ACTIVE",
            "created_at":            time.time(),
            "duration_ticks_beta":   0,
            "duration_ticks_active": 0,
        }

        active_cycles          = copy.deepcopy(self.orch.state.get("active_cycles", {}))
        active_cycles[str_cid] = cycle

        self.orch.receive_event("active_cycles_updated", {"active_cycles": active_cycles})
        logger.info(
            f"Cycle #{self._last_cycle_id} created "
            f"(opp={cycle['opportunity_id']}, score={cycle['score']}). "
            f"Active: {len(active_cycles)}"
        )
        self.bus.emit("cycle_started", cycle)

    def _on_cycle_tick(self, payload: dict) -> None:
        active_cycles = copy.deepcopy(self.orch.state.get("active_cycles", {}))
        if not active_cycles:
            return

        completed_ids = []
        modified      = False

        for str_cid, cycle in active_cycles.items():
            if not isinstance(cycle, dict) or cycle.get("phase") != "CYCLE_ACTIVE":
                continue

            cycle["duration_ticks_active"] = cycle.get("duration_ticks_active", 0) + 1
            modified = True

            if cycle["duration_ticks_active"] >= CYCLE_ACTIVE_TICK_THRESHOLD:
                completed_ids.append(str_cid)

        if modified:
            self.orch.receive_event(
                "active_cycles_updated", {"active_cycles": active_cycles}
            )

        for str_cid in completed_ids:
            self._complete_cycle(str_cid)

    def _complete_cycle(self, str_cid: str) -> None:
        active_cycles = copy.deepcopy(self.orch.state.get("active_cycles", {}))
        cycle = active_cycles.get(str_cid)
        if not cycle:
            return

        completed = copy.deepcopy(cycle)
        completed["phase"]        = "CYCLE_COMPLETED"
        completed["completed_at"] = time.time()

        history = list(self.orch.state.get("cycle_history", []))
        history.append(completed)
        active_cycles.pop(str_cid, None)
        metrics = self._compute_metrics(history)

        self.orch.receive_event("cycle_completed_recorded", {
            "cycle_history": history,
            "active_cycles": active_cycles,
            "metrics":       metrics,
        })

        logger.info(
            f"Cycle #{str_cid} COMPLETED. "
            f"History: {len(history)} | Active: {len(active_cycles)}"
        )
        self.bus.emit("cycle_completed", completed)
