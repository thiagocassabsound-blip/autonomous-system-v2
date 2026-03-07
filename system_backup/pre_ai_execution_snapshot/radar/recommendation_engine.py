"""
radar/recommendation_engine.py — Bloco 26 V2: Phase 6 Recommendation Output Layer

Responsibilities:
  • Receive output from StrategicOpportunityEngine (Core)
  • Apply final display/formatting decisions
  • Emit expansion_recommendation_event via Orchestrator
  • Prepare structured output for dashboard consumption

Constitutional constraints:
  - CANNOT create products
  - CANNOT launch betas
  - CANNOT allocate capital
  - CANNOT modify system state directly
  - ALL actions require explicit Orchestrator event emission
  - CANNOT recompute or override scores from Core

Authority: ZERO executive authority.
The Core (StrategicOpportunityEngine) is the sole scoring authority.
This module is a READ + FORMAT + EMIT layer only.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from infrastructure.logger import get_logger
from radar.models.radar_metrics_snapshot import RadarMetricsSnapshot

logger = get_logger("RadarRecommendationEngine")

# ---------------------------------------------------------------------------
# Output formatting helpers
# ---------------------------------------------------------------------------

def _ice_label(ice: str) -> str:
    labels = {
        "ALTO":     "HIGH PRIORITY — Validated for expansion consideration",
        "MODERADO": "MEDIUM PRIORITY — Warrants monitoring and further validation",
        "BLOQUEADO": "BLOCKED — ICE criteria not met, expansion not recommended",
    }
    return labels.get(ice, f"UNKNOWN ICE: {ice}")


def format_recommendation_output(engine_result: dict, strategy: Optional[dict] = None) -> dict:
    """
    Format the raw engine output into a structured dashboard-ready recommendation.

    Args:
        engine_result: Dict returned by StrategicOpportunityEngine.evaluate_opportunity_v2()
        strategy:      Optional output from validation_strategy.generate_full_strategy()

    Returns:
        Structured recommendation dict (read-only, no side-effects)
    """
    status = engine_result.get("status")

    if status in ("blocked", "rejected", "not_qualified"):
        return {
            "recommendation":  False,
            "status":          status,
            "reason":          engine_result.get("reason", "Gate rejection"),
            "ice":             engine_result.get("ice"),
            "product_id":      engine_result.get("product_id"),
            "timestamp":       datetime.now(timezone.utc).isoformat(),
            "action_required": False,
        }

    ice = engine_result.get("ice", "BLOQUEADO")
    return {
        "recommendation":      engine_result.get("recommended", False),
        "status":              "qualified" if "status" not in engine_result else status,
        "product_id":          engine_result.get("product_id"),
        "ice":                 ice,
        "ice_label":           _ice_label(ice),
        "score_final":         engine_result.get("score_final"),
        "emotional":           engine_result.get("emotional"),
        "monetization":        engine_result.get("monetization"),
        "growth_score":        engine_result.get("growth_score"),
        "cluster_penalty":     engine_result.get("cluster_penalty"),
        "snapshot_hash":       engine_result.get("snapshot_hash"),
        "timestamp":           datetime.now(timezone.utc).isoformat(),
        "strategy":            strategy or engine_result.get("strategy"),
        "action_required":     engine_result.get("recommended", False),
        "execution_authority": "Requires explicit Orchestrator event + human approval",
        "auto_execution":      False,  # Constitutional guarantee — always False
    }


# Constitutional score thresholds for recommendation pre-check (read-only, never recompute)
_EMOTIONAL_MIN    = 70.0
_MONETIZATION_MIN = 75.0
_GROWTH_MIN       = 60.0


def check_recommendation_preconditions(
    engine_result: dict,
    governance_allowed: bool = True,
) -> tuple[bool, list[str]]:
    """
    Check all 5 constitutional pre-conditions before emitting recommendation.

    Constitutional contract:
      - Reads score fields verbatim from engine_result — NO recalculation
      - governance_allowed is the result of validate_radar_execution()["allowed"]
      - Returns (True, []) when all pass; (False, reasons) when any fail
      - Caller MUST NOT emit or persist if this returns False

    Pre-conditions (ALL must be True):
      1. engine_result["emotional"]    >= 70
      2. engine_result["monetization"] >= 75
      3. engine_result["growth_score"] >= 60
      4. engine_result["ice"]         != "BLOQUEADO"
      5. governance_allowed           == True

    Returns:
        (passed: bool, failure_reasons: list[str])
    """
    failures: list[str] = []

    emotional    = float(engine_result.get("emotional",    0.0))
    monetization = float(engine_result.get("monetization", 0.0))
    growth_score = float(engine_result.get("growth_score", 0.0))
    ice          = engine_result.get("ice", "BLOQUEADO")

    if emotional < _EMOTIONAL_MIN:
        failures.append(f"emotional={emotional:.2f} < {_EMOTIONAL_MIN}")
    if monetization < _MONETIZATION_MIN:
        failures.append(f"monetization={monetization:.2f} < {_MONETIZATION_MIN}")
    if growth_score < _GROWTH_MIN:
        failures.append(f"growth_score={growth_score:.2f} < {_GROWTH_MIN}")
    if ice == "BLOQUEADO":
        failures.append("ice=BLOQUEADO")
    if not governance_allowed:
        failures.append("governance_allowed=False")

    return len(failures) == 0, failures


def persist_recommendation(
    engine_result: dict,
    cluster_id: str = "",
    persistence_path: str = "radar_recommendations.jsonl",
) -> dict:
    """
    Append-only persist the recommendation decision to radar_recommendations.jsonl.

    Constitutional contract:
      - NEVER recalculates any score field
      - Append-only — no mutation or deletion
      - Persisted whether recommendation was emitted or not (for audit trail)

    Persisted record schema (exact, per specification):
        event_id, cluster_id, score_final, ice, timestamp

    Args:
        engine_result:    Dict from StrategicOpportunityEngine
        cluster_id:       Dominant cluster identifier
        persistence_path: Target JSONL file path

    Returns:
        The persisted record dict
    """
    import json

    record = {
        "event_id":   engine_result.get("event_id", ""),
        "cluster_id": cluster_id,
        "score_final": engine_result.get("score_final"),
        "ice":         engine_result.get("ice", "BLOQUEADO"),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }

    try:
        with open(persistence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[RecommendationEngine] persist_recommendation failed: {exc}")

    logger.info(
        f"[RecommendationEngine] Recommendation record persisted. "
        f"event_id={record['event_id']} ice={record['ice']} "
        f"score_final={record['score_final']}"
    )
    return record


def emit_recommendation_event(
    orchestrator,
    engine_result: dict,
    strategy: Optional[dict] = None,
    cluster_id: str = "",
    governance_allowed: bool = True,
    recommendations_path: str = "radar_recommendations.jsonl",
) -> dict:
    """
    Formal Phase 7 emission of expansion_recommendation_event.

    Constitutional contract:
      - ONLY emits an event — does NOT create products
      - NEVER initiates betas, allocates capital, or modifies global state
      - Runs 5-condition pre-check before any emission
      - Persists to radar_recommendations.jsonl ALWAYS (audit trail)
      - Orchestrator event emitted ONLY when ALL 5 conditions pass
      - Human review is required before any product-level action

    Pre-conditions (ALL required for emission):
      1. emotional >= 70
      2. monetization >= 75
      3. growth_score >= 60
      4. ice != "BLOQUEADO"
      5. governance_allowed == True

    Payload emitted:
        event_id, timestamp, cluster_id,
        metrics_snapshot (RadarMetricsSnapshot as dict, immutable),
        justification_summary (from strategy)

    Returns:
        {"emitted": bool, "reason": str|None, "record": dict}
    """
    import uuid

    # Step 1 — Pre-condition gate (reads verbatim, no recalculation)
    passed, failures = check_recommendation_preconditions(engine_result, governance_allowed)

    # Step 2 — Persist record ALWAYS (for audit trail, even if gate fails)
    record = persist_recommendation(
        engine_result    = engine_result,
        cluster_id       = cluster_id,
        persistence_path = recommendations_path,
    )

    if not passed:
        reason = f"Recommendation gate failed: {'; '.join(failures)}"
        logger.warning(
            f"[RecommendationEngine] expansion_recommendation_event NOT emitted: {reason}"
        )
        return {"emitted": False, "reason": reason, "record": record}

    # Step 3 — Build formal event payload
    ice = engine_result.get("ice", "BLOQUEADO")
    event_id  = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    justification = (
        strategy.get("justification_summary", "")
        if strategy else ""
    )

    event_payload = {
        "event_id":            event_id,
        "timestamp":           timestamp,
        "cluster_id":          cluster_id,
        "score_final":         engine_result.get("score_final"),
        "emotional":           engine_result.get("emotional"),
        "monetization":        engine_result.get("monetization"),
        "growth_score":        engine_result.get("growth_score"),
        "ice":                 ice,
        "ice_label":           _ice_label(ice),
        "justification_summary": justification,
        "strategy":            strategy,
        "auto_execution":      False,      # Constitutional guarantee — always False
        "execution_authority": "Requires explicit Orchestrator event + human approval",
        "note": "SIGNAL ONLY — does not create product, does not allocate capital, does not start beta.",
    }

    # Step 4 — Emit via Orchestrator ONLY (no direct state change)
    try:
        orchestrator.receive_event(
            event_type="expansion_recommendation_event",
            payload=event_payload,
        )
        logger.info(
            f"[RecommendationEngine] expansion_recommendation_event emitted. "
            f"cluster_id='{cluster_id}' "
            f"ice={ice} score_final={engine_result.get('score_final')}"
        )
    except Exception as exc:
        logger.error(f"[RecommendationEngine] Orchestrator emit failed: {exc}")
        return {"emitted": False, "reason": str(exc), "record": record}

    # Format backwards-compat payload for pipeline_result
    formatted = format_recommendation_output(engine_result, strategy)
    formatted["event_id_emitted"] = event_id
    formatted["emitted"] = True
    return formatted


def persist_metrics_snapshot(
    engine_result:   dict,
    snapshot_event_id: str,
    noise_score:     float,
    persistence_path: str = "radar_metrics.jsonl",
) -> RadarMetricsSnapshot:
    """
    Build and append-only persist a RadarMetricsSnapshot from the engine result.

    Constitutional guarantee: append-only, never mutates existing records.

    Returns:
        RadarMetricsSnapshot
    """
    import json

    status = engine_result.get("status", "qualified") if "status" in engine_result else "qualified"
    if status in ("blocked", "rejected", "not_qualified"):
        # Still record the rejection for audit purposes
        pass

    metrics = RadarMetricsSnapshot.from_engine_result(
        engine_result     = engine_result,
        snapshot_event_id = snapshot_event_id,
        noise_score       = noise_score,
    )

    line = json.dumps(metrics.to_dict(), ensure_ascii=False)
    with open(persistence_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    logger.info(
        f"[RecommendationEngine] MetricsSnapshot persisted. "
        f"event_id={metrics.event_id} recommended={metrics.recommended}"
    )
    return metrics


# ---------------------------------------------------------------------------
# Score_Final Preservation Layer (Etapa 8)
# ---------------------------------------------------------------------------

def extract_score_envelope(engine_result: dict, cluster_id: str = "") -> dict:
    """
    Extract the official scoring envelope from Core output WITHOUT recalculation.

    Constitutional contract:
      - Copies fields directly from engine_result — NO arithmetic performed
      - cluster_penalty is already applied inside StrategicOpportunityEngine
      - score_final is already the post-penalty value
      - Radar NEVER touches these values beyond this extraction

    Returns:
        {
            event_id, cluster_id,
            emotional_score, monetization_score, growth_score,
            score_final, cluster_ratio, cluster_penalty,
            ice_classification, qualified, timestamp
        }
    """
    return {
        "event_id":           engine_result.get("event_id", ""),
        "cluster_id":         cluster_id,
        "emotional_score":    engine_result.get("emotional"),
        "monetization_score": engine_result.get("monetization"),
        "growth_score":       engine_result.get("growth_score"),
        "score_final":        engine_result.get("score_final"),
        "cluster_ratio":      engine_result.get("cluster_ratio"),
        "cluster_penalty":    engine_result.get("cluster_penalty", False),
        "ice_classification": engine_result.get("ice", "BLOQUEADO"),
        "qualified":          engine_result.get("recommended", False),
        "timestamp":          datetime.now(timezone.utc).isoformat(),
    }


def persist_score_result(
    engine_result: dict,
    cluster_id: str = "",
    persistence_path: str = "radar_score_results.jsonl",
) -> dict:
    """
    Append-only persist the Core's score result to radar_score_results.jsonl.

    This function:
      - NEVER recalculates score_final
      - NEVER applies or modifies cluster_penalty
      - NEVER modifies emotional / monetization / growth values
      - Only writes what was returned verbatim by StrategicOpportunityEngine

    Persisted record schema (exact, per specification):
        event_id, cluster_id, score_final, emotional, monetization,
        growth, cluster_ratio, ice, timestamp

    Returns:
        The persisted record dict (identical to what was written)
    """
    import json

    record = {
        "event_id":     engine_result.get("event_id", ""),
        "cluster_id":   cluster_id,
        "score_final":  engine_result.get("score_final"),
        "emotional":    engine_result.get("emotional"),
        "monetization": engine_result.get("monetization"),
        "growth":       engine_result.get("growth_score"),
        "cluster_ratio": engine_result.get("cluster_ratio"),
        "ice":          engine_result.get("ice", "BLOQUEADO"),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    }

    try:
        with open(persistence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[RecommendationEngine] persist_score_result failed: {exc}")

    logger.info(
        f"[RecommendationEngine] ScoreResult persisted. "
        f"event_id={record['event_id']} "
        f"score_final={record['score_final']} "
        f"ice={record['ice']}"
    )
    return record


def rank_by_score_final(score_envelopes: list) -> list:
    """
    Sort a list of score envelopes by score_final descending.

    Constitutional contract:
      - Uses score_final exclusively as the sort key
      - NEVER uses emotional, monetization, growth, or cluster_ratio as sort keys
      - Does NOT recalculate any scores
      - Returns a new sorted list — does NOT mutate the input

    Args:
        score_envelopes: List of dicts as returned by extract_score_envelope()
                         or persist_score_result(). Must contain "score_final".

    Returns:
        New list sorted by score_final descending (highest first).
    """
    return sorted(
        score_envelopes,
        key=lambda r: float(r.get("score_final") or 0.0),
        reverse=True,
    )


# ---------------------------------------------------------------------------
# ICE Gate Formalization (Etapa 9)
# ---------------------------------------------------------------------------

# Valid ICE values as emitted by StrategicOpportunityEngine (Core)
_ICE_BLOQUEADO = "BLOQUEADO"
_ICE_MODERADO  = "MODERADO"
_ICE_ALTO      = "ALTO"
_VALID_ICE     = {_ICE_BLOQUEADO, _ICE_MODERADO, _ICE_ALTO}


def extract_ice_classification(engine_result: dict) -> str:
    """
    Extract ICE classification from Core output WITHOUT any recalculation.

    Constitutional contract:
      - Reads engine_result['ice'] verbatim — NO logic, NO reclassification
      - Returns 'BLOQUEADO' as safe default if missing (fail-safe)
      - Radar NEVER applies its own ICE classification rules

    Args:
        engine_result: Dict returned by StrategicOpportunityEngine.evaluate_opportunity_v2()

    Returns:
        str — one of "BLOQUEADO" | "MODERADO" | "ALTO"
    """
    ice = engine_result.get("ice", _ICE_BLOQUEADO)
    if ice not in _VALID_ICE:
        logger.warning(
            f"[ICEGate] Unknown ICE value '{ice}' received from Core. "
            f"Defaulting to BLOQUEADO (fail-safe)."
        )
        return _ICE_BLOQUEADO
    return ice


def is_ice_blocked(engine_result: dict) -> bool:
    """
    Structural ICE gate — returns True if the cycle must abort (ICE == BLOQUEADO).

    Constitutional contract:
      - Uses ONLY extract_ice_classification() — no custom logic
      - BLOQUEADO → pipeline must stop before Recommendation (Phase 7)
      - MODERADO or ALTO → pipeline continues to Validation Strategy

    Args:
        engine_result: Dict returned by StrategicOpportunityEngine.evaluate_opportunity_v2()

    Returns:
        True  → ICE is BLOQUEADO → abort before Recommendation
        False → ICE is MODERADO or ALTO → continue pipeline
    """
    return extract_ice_classification(engine_result) == _ICE_BLOQUEADO


def persist_ice_decision(
    engine_result: dict,
    cluster_id: str = "",
    persistence_path: str = "radar_ice_decisions.jsonl",
) -> dict:
    """
    Append-only persist the ICE decision from Core output.

    Constitutional contract:
      - NEVER recalculates or reclassifies ICE
      - NEVER adds derived fields beyond the required schema
      - Append-only — no mutate, no delete

    Persisted record schema (exact, per specification):
        event_id, cluster_id, score_final, ice_classification, timestamp

    Args:
        engine_result:    Dict from StrategicOpportunityEngine (carries 'ice' field)
        cluster_id:       Identifier of the cluster being evaluated
        persistence_path: Target JSONL file path

    Returns:
        The persisted record dict
    """
    import json

    record = {
        "event_id":           engine_result.get("event_id", ""),
        "cluster_id":         cluster_id,
        "score_final":        engine_result.get("score_final"),
        "ice_classification": extract_ice_classification(engine_result),
        "timestamp":          datetime.now(timezone.utc).isoformat(),
    }

    try:
        with open(persistence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[ICEGate] persist_ice_decision failed: {exc}")

    logger.info(
        f"[ICEGate] ICE decision persisted. "
        f"event_id={record['event_id']} "
        f"ice={record['ice_classification']} "
        f"score_final={record['score_final']}"
    )
    return record
