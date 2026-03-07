"""
engines/economic_engine.py — Economic Engine (Migrated)
All state writes routed through Orchestrator.receive_event().
"""
from infrastructure.logger import get_logger

logger = get_logger("EconomicEngine")


def _classify(viabilidade_score: float) -> str:
    if viabilidade_score > 1000:
        return "VIAVEL"
    if viabilidade_score >= 300:
        return "TESTAVEL"
    return "NAO_VIAVEL"


class EconomicEngine:
    """
    Runs economic projection on each score_computed event.
    Writes evaluation via orchestrator.receive_event() — no direct state access.
    """

    def __init__(self, event_bus, orchestrator):
        self.bus  = event_bus
        self.orch = orchestrator
        self.bus.subscribe("score_computed", self._on_score_computed)
        logger.info("EconomicEngine initialized.")

    def _on_score_computed(self, payload: dict) -> None:
        opp_id      = payload.get("id")
        score_final = payload.get("score_final", 0)

        preco_sugerido    = score_final * 0.8
        custo_estimado    = score_final * 0.3
        margem            = preco_sugerido - custo_estimado
        taxa_conversao    = min(0.15, score_final / 1000)
        volume_estimado   = 100
        receita_projetada = preco_sugerido * volume_estimado * taxa_conversao
        lucro_projetado   = margem * volume_estimado * taxa_conversao
        viabilidade_score = lucro_projetado
        classificacao     = _classify(viabilidade_score)

        evaluation = {
            "opportunity_id":    opp_id,
            "score_final":       score_final,
            "preco_sugerido":    round(preco_sugerido, 2),
            "custo_estimado":    round(custo_estimado, 2),
            "margem":            round(margem, 2),
            "taxa_conversao":    round(taxa_conversao, 4),
            "volume_estimado":   volume_estimado,
            "receita_projetada": round(receita_projetada, 2),
            "lucro_projetado":   round(lucro_projetado, 2),
            "viabilidade_score": round(viabilidade_score, 2),
            "classificacao":     classificacao,
        }

        # Write via orchestrator
        self.orch.receive_event("economic_evaluation_recorded", evaluation)

        logger.info(
            f"Opportunity #{opp_id}: {classificacao} "
            f"lucro={evaluation['lucro_projetado']:.2f}"
        )
        self.bus.emit("economic_evaluated", evaluation)
