"""
radar/validation_strategy.py — Bloco 26 V2: Phase 6 Validation Strategy (v2)

Responsibilities:
  • Generate ICP (Ideal Customer Profile) from scored signals and snapshot context
  • Generate Fake Door Strategy template
  • Define central hypothesis (structured: If X for Y in Z → W)
  • Define minimum validation metric (CTR / opt-in threshold)
  • Generate justification summary based on Core scores + cluster evidence
  • Persist RadarMetricsSnapshot v2 (with embedded strategy) to JSONL

Constitutional constraints:
  - CANNOT recalculate Emotional / Monetization / Growth / ICE / Score_Final
  - CANNOT execute product creation or launch anything
  - CANNOT modify system state or assets
  - CANNOT call Orchestrator
  - All output is READ-ONLY advisory content
  - Only runs when ICE != "BLOQUEADO" (gate enforced by radar_engine.py)
  - All values read from engine_result are copied verbatim — no arithmetic
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from infrastructure.logger import get_logger
from radar.models.radar_metrics_snapshot import RadarMetricsSnapshot

logger = get_logger("RadarValidationStrategy")

# ---------------------------------------------------------------------------
# Constitutional validation thresholds (advisory — NOT used in scoring)
# ---------------------------------------------------------------------------
MIN_CTR_THRESHOLD    = 3.0   # % — minimum click-through rate for fake door test
MIN_OPT_IN_THRESHOLD = 50    # minimum email opt-ins in validation window
VALIDATION_WINDOW_H  = 72    # hours for fake door test

# Channel suggestions (purely advisory)
_CHANNEL_HIGH_SCORE  = "Sponsored landing page + targeted ad set (Facebook/Google)"
_CHANNEL_MID_SCORE   = "Organic landing page + social post test"
_CHANNEL_ALL         = "Waitlist / email capture with 3-question survey"


# ---------------------------------------------------------------------------
# ICP Generator
# ---------------------------------------------------------------------------

def generate_icp(
    keyword:       str,
    emotional:     float,
    monetization:  float,
    cluster_label: Optional[str] = None,
    dominant_source: Optional[str] = None,
    dominant_context: Optional[str] = None,
) -> str:
    """
    Generate Ideal Customer Profile statement derived from Core scores.

    Reads emotional and monetization verbatim — NO recalculation.
    dominant_source and dominant_context are optional context from snapshot.

    Returns:
        str — ICP description for advisory dashboard
    """
    pain_level = "high" if emotional >= 80 else ("moderate" if emotional >= 65 else "low")
    pay_level  = "high" if monetization >= 80 else ("moderate" if monetization >= 65 else "low")
    ctx_parts  = []
    if cluster_label:
        ctx_parts.append(f"cluster '{cluster_label}'")
    if dominant_source:
        ctx_parts.append(f"predominantly surfaced on {dominant_source}")
    if dominant_context:
        ctx_parts.append(f"engaging around: {dominant_context}")
    context = f" ({', '.join(ctx_parts)})" if ctx_parts else ""

    icp = (
        f"Professional or prosumer experiencing {pain_level}-intensity pain around '{keyword}'{context}, "
        f"with {pay_level} willingness to pay for a dedicated solution. "
        f"Likely already searching for alternatives and frustrated with current options."
    )
    logger.info(
        f"[ValidationStrategy] ICP generated for '{keyword}' "
        f"(emo={emotional:.1f}, mon={monetization:.1f})"
    )
    return icp


# ---------------------------------------------------------------------------
# Fake Door Strategy
# ---------------------------------------------------------------------------

def generate_fake_door_strategy(
    keyword:     str,
    score_final: float,
    ice:         str,
) -> dict:
    """
    Generate a Fake Door (landing page validation) strategy template.

    Constitutional guarantee:
      - Advisory TEMPLATE only — nothing is created or deployed automatically
      - All execution requires explicit Orchestrator event + human review

    Returns:
        dict — Fake Door strategy for dashboard display
    """
    if ice == "BLOQUEADO":
        return {
            "strategy_type": "fake_door",
            "actionable":    False,
            "reason":        "ICE=BLOQUEADO — validation strategy not generated",
        }

    urgency  = "high" if score_final >= 80 else "standard"
    channel  = _CHANNEL_HIGH_SCORE if score_final >= 80 else _CHANNEL_MID_SCORE

    strategy = {
        "strategy_type":    "fake_door",
        "actionable":       True,
        "keyword":          keyword,
        "ice":              ice,
        "score_final":      score_final,
        "suggested_channel": channel,
        "landing_structure": {
            "headline":      f"Are you struggling with {keyword}? [Problem-focused headline]",
            "subheadline":   f"Join {MIN_OPT_IN_THRESHOLD}+ people discovering the solution.",
            "cta_primary":   "Get Early Access",
            "cta_secondary": "Tell me more about your situation",
        },
        "cta_target":            _CHANNEL_ALL,
        "validation_window_h":   VALIDATION_WINDOW_H,
        "min_ctr_pct":           MIN_CTR_THRESHOLD,
        "min_opt_ins":           MIN_OPT_IN_THRESHOLD,
        "urgency_level":         urgency,
        "requires_human_review": True,
        "auto_execution":        False,          # Constitutional guarantee — always False
        "execution_authority":   "Exclusive via Orchestrator on human approval",
    }
    logger.info(
        f"[ValidationStrategy] FakeDoor strategy generated. "
        f"keyword='{keyword}' ice={ice} channel='{channel}'"
    )
    return strategy


# ---------------------------------------------------------------------------
# Central Hypothesis
# ---------------------------------------------------------------------------

def generate_central_hypothesis(
    keyword:        str,
    emotional:      float,
    monetization:   float,
    growth_percent: float,
    dominant_source: Optional[str] = None,
) -> str:
    """
    Generate the central validation hypothesis.

    Structured format: "If we offer X for Y in context Z, then we obtain W."

    Reads inputs verbatim — NO arithmetic on score fields.
    """
    where = f"via {dominant_source}" if dominant_source else "through a focused landing test"
    hypothesis = (
        f"If we offer a dedicated solution for '{keyword}' to users experiencing "
        f"this pain {where}, "
        f"then we will obtain CTR >= {MIN_CTR_THRESHOLD}% or "
        f">= {MIN_OPT_IN_THRESHOLD} opt-ins in {VALIDATION_WINDOW_H}h — "
        f"confirming genuine demand. "
        f"[Evidence basis: Emotional={emotional:.1f}, Monetization={monetization:.1f}, "
        f"Growth={growth_percent:.1f}%]"
    )
    return hypothesis


# ---------------------------------------------------------------------------
# Justification Summary (NEW — Etapa 10)
# ---------------------------------------------------------------------------

def generate_justification_summary(
    emotional:     float,
    monetization:  float,
    growth_score:  float,
    cluster_ratio: float,
    text_evidence: Optional[list] = None,
) -> str:
    """
    Generate a brief justification summary based EXCLUSIVELY on Core score
    outputs and cluster textual evidence.

    Constitutional contract:
      - Reads score fields verbatim — NO recalculation
      - cluster_ratio is informational only (penalty already applied by Core)
      - text_evidence is sampled from raw_provider_payloads — advisory only

    Args:
        emotional:     Emotional Score from Core (read-only copy)
        monetization:  Monetization Score from Core (read-only copy)
        growth_score:  Growth Score from Core (read-only copy)
        cluster_ratio: Cluster ratio from Phase 4 / Core (informational)
        text_evidence: Optional list of raw text samples from provider payloads

    Returns:
        str — justification summary for advisory record
    """
    saturation_note = (
        f"Cluster saturation is elevated ({cluster_ratio*100:.1f}%), "
        "which may increase competitive pressure."
        if cluster_ratio >= 0.30
        else f"Cluster saturation is within acceptable range ({cluster_ratio*100:.1f}%)."
    )

    evidence_note = ""
    if text_evidence:
        samples = text_evidence[:3]
        evidence_note = (
            " Representative signals: "
            + "; ".join(f'"{s}"' for s in samples) + "."
        )

    summary = (
        f"Opportunity scores: Emotional={emotional:.2f}/100, "
        f"Monetization={monetization:.2f}/100, Growth={growth_score:.2f}/100. "
        f"{saturation_note}"
        f"{evidence_note}"
    )
    return summary


# ---------------------------------------------------------------------------
# Full Strategy Generator
# ---------------------------------------------------------------------------

def generate_full_strategy(
    keyword:          str,
    emotional:        float,
    monetization:     float,
    growth_percent:   float,
    score_final:      float,
    ice:              str,
    cluster_label:    Optional[str] = None,
    cluster_ratio:    float = 0.0,
    dominant_source:  Optional[str] = None,
    dominant_context: Optional[str] = None,
    text_evidence:    Optional[list] = None,
    growth_score:     float = 0.0,
) -> dict:
    """
    Generate all advisory strategy components in one call.

    Inputs are read verbatim from Core output — NO recalculation.

    Returns:
        {
            "icp":                  str,
            "fake_door_strategy":   dict,
            "central_hypothesis":   str,
            "min_validation_metric": str,
            "justification_summary": str,
        }
    """
    icp = generate_icp(
        keyword          = keyword,
        emotional        = emotional,
        monetization     = monetization,
        cluster_label    = cluster_label,
        dominant_source  = dominant_source,
        dominant_context = dominant_context,
    )
    fake_door = generate_fake_door_strategy(keyword, score_final, ice)
    hypothesis = generate_central_hypothesis(keyword, emotional, monetization, growth_percent, dominant_source)
    justification = generate_justification_summary(
        emotional     = emotional,
        monetization  = monetization,
        growth_score  = growth_score,
        cluster_ratio = cluster_ratio,
        text_evidence = text_evidence,
    )

    strategy = {
        "icp":                   icp,
        "fake_door_strategy":    fake_door,
        "central_hypothesis":    hypothesis,
        "min_validation_metric": (
            f"CTR >= {MIN_CTR_THRESHOLD}% in {VALIDATION_WINDOW_H}h "
            f"OR >= {MIN_OPT_IN_THRESHOLD} opt-ins"
        ),
        "justification_summary": justification,
    }

    logger.info(
        f"[ValidationStrategy] Full strategy generated for '{keyword}'. "
        f"ICE={ice} score_final={score_final}"
    )
    return strategy


# ---------------------------------------------------------------------------
# Persistence — RadarMetricsSnapshot v2 (Etapa 10)
# ---------------------------------------------------------------------------

def persist_metrics_snapshot_full(
    engine_result:       dict,
    snapshot_event_id:   str,
    noise_score:         float,
    strategy:            dict,
    cluster_id:          str = "",
    persistence_path:    str = "radar_metrics_snapshots.jsonl",
) -> RadarMetricsSnapshot:
    """
    Build and append-only persist a RadarMetricsSnapshot v2.

    This snapshot embeds the validation_strategy dict generated in Phase 6,
    alongside all Core score fields (copied verbatim — no recalculation).

    Constitutional contract:
      - NEVER recomputes emotional / monetization / growth / ice / score_final
      - NEVER executes any action
      - Append-only — no mutation or deletion of existing records
      - validation_strategy is None when ICE == BLOQUEADO

    Args:
        engine_result:      Dict from StrategicOpportunityEngine.evaluate_opportunity_v2()
        snapshot_event_id:  event_id of the RadarDatasetSnapshot (Phase 2.5)
        noise_score:        Noise_Filter_Score at evaluation time
        strategy:           Advisory strategy dict from generate_full_strategy()
        cluster_id:         Dominant cluster identifier (from Phase 4)
        persistence_path:   Target JSONL path (default: radar_metrics_snapshots.jsonl)

    Returns:
        RadarMetricsSnapshot (frozen, append-only)
    """
    metrics = RadarMetricsSnapshot.from_engine_result(
        engine_result       = engine_result,
        snapshot_event_id   = snapshot_event_id,
        noise_score         = noise_score,
        cluster_id          = cluster_id,
        validation_strategy = strategy,
    )

    try:
        with open(persistence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(metrics.to_dict(), ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[ValidationStrategy] persist_metrics_snapshot_full failed: {exc}")

    logger.info(
        f"[ValidationStrategy] MetricsSnapshot v2 persisted. "
        f"event_id={metrics.event_id} "
        f"ice={metrics.ice} "
        f"recommended={metrics.recommended}"
    )
    return metrics
