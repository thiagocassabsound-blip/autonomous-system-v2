"""
infra/landing/landing_draft_listener.py — EventBus subscriber for product_draft_created.

Responsibilities:
  - Capture product_draft_created events from the EventBus
  - Extract product_id and opportunity_id (= cluster_id)
  - Associate cluster_id → product_id in the shared index
  - Initiate the landing generation pipeline

Registered in bootstrap via:
    EventBus.subscribe("product_draft_created", landing_draft_listener)

Constitutional guarantees:
  - Never calls StateMachine.transition()
  - Never instantiates ProductLifeEngine
  - Never calls GuardianEngine
  - Never alters state.json
  - All events via orchestrator.receive_event()
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from infra.landing import landing_prompt_builder
from infra.landing import landing_llm_executor
from infra.landing import landing_structure_validator
from infra.landing import landing_html_validator
from infra.landing import landing_five_second_rule
from infra.landing import landing_snapshot
from infra.landing import landing_versioning

if TYPE_CHECKING:
    pass

logger = logging.getLogger("infra.landing.draft_listener")


def run_landing_pipeline(
    *,
    cluster_id:           str,
    product_id:           str,
    event_id:             str,
    icp:                  str,
    strategy:             str,
    justification_summary: str,
    emotional_score:      float,
    monetization_score:   float,
    orchestrator,
) -> None:
    """
    Execute the full landing generation pipeline for a given product_id.

    Pipeline (sequential):
        1. LandingPromptBuilder
        2. LandingLLMExecutor
        3. LandingStructureValidator
        4. HTMLSchemaValidator
        5. FiveSecondRuleEvaluator
        6. LandingSnapshotPersistence

    On any failure: emits landing_generation_failed_event via receive_event().
    On success: emits landing_ready_event via receive_event().
    Never crashes. Never raises.
    """

    def _fail(reason: str, stage: str) -> None:
        logger.warning(
            "[LandingPipeline] FAILED at stage=%s product_id=%s reason=%s",
            stage, product_id, reason,
        )
        try:
            orchestrator.receive_event(
                event_type="landing_generation_failed_event",
                payload={
                    "product_id":  product_id,
                    "cluster_id":  cluster_id,
                    "stage":       stage,
                    "reason":      reason,
                    "timestamp":   datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.error("[LandingPipeline] Failed to emit failure event: %s", exc)

    # ── Step 1: Build prompt ──────────────────────────────────────────────
    try:
        prompt = landing_prompt_builder.build_prompt(
            icp                  = icp,
            strategy             = strategy,
            justification_summary= justification_summary,
            emotional_score      = emotional_score,
            monetization_score   = monetization_score,
        )
    except Exception as exc:
        _fail(str(exc), "LandingPromptBuilder")
        return

    # ── Step 2: Execute LLM ───────────────────────────────────────────────
    try:
        llm_result = landing_llm_executor.execute_landing_generation(prompt)
    except Exception as exc:
        _fail(str(exc), "LandingLLMExecutor")
        return

    if llm_result.get("status") != "ok":
        _fail(
            llm_result.get("error_type", "LLMUnknownError"),
            "LandingLLMExecutor",
        )
        return

    html       = llm_result["html"]
    model_used = llm_result["model_used"]
    latency_ms = llm_result["latency_ms"]
    prompt_hash= llm_result["prompt_hash"]
    html_hash  = llm_result["html_hash"]

    # ── Step 3: Structure validator ────────────────────────────────────────
    struct_result = landing_structure_validator.validate(html, icp=icp)
    if not struct_result["valid"]:
        _fail(struct_result["reason"], "LandingStructureValidator")
        return

    # ── Step 4: HTML security validator ───────────────────────────────────
    html_result = landing_html_validator.validate(html)
    if not html_result["valid"]:
        _fail(html_result["reason"], "HTMLSchemaValidator")
        return

    # ── Step 5: Five second rule ──────────────────────────────────────────
    fsr_result = landing_five_second_rule.validate(html)
    if not fsr_result["valid"]:
        _fail(fsr_result["reason"], "FiveSecondRuleEvaluator")
        return

    # ── Step 6: Snapshot persistence ──────────────────────────────────────
    version = landing_versioning.compute_version(cluster_id)
    try:
        landing_snapshot.append_snapshot(
            event_id          = event_id,
            product_id        = product_id,
            cluster_id        = cluster_id,
            prompt_hash       = prompt_hash,
            model_used        = model_used,
            latency_ms        = latency_ms,
            validation_passed = True,
            html_hash         = html_hash,
            version           = version,
        )
    except Exception as exc:
        logger.error("[LandingPipeline] Snapshot persistence failed: %s", exc)
        # Non-fatal: continue to emit landing_ready_event

    # ── Success: emit landing_ready_event ─────────────────────────────────
    logger.info(
        "[LandingPipeline] SUCCESS product_id=%s cluster_id=%s version=%d model=%s",
        product_id, cluster_id, version, model_used,
    )
    try:
        orchestrator.receive_event(
            event_type="landing_ready_event",
            payload={
                "product_id":  product_id,
                "cluster_id":  cluster_id,
                "version":     version,
                "model_used":  model_used,
                "html_hash":   html_hash,
                "latency_ms":  latency_ms,
                "timestamp":   datetime.now(timezone.utc).isoformat(),
                "landing_url": f"https://fastoolhub.com/product/{product_id}",
                "product_context": justification_summary,
                "persona_context": icp,
            },
        )
    except Exception as exc:
        logger.error("[LandingPipeline] Failed to emit landing_ready_event: %s", exc)


def make_draft_listener(
    cluster_index: dict,
    orchestrator,
    recommendation_payload_store: dict,
) -> callable:
    """
    Factory: returns an EventBus handler for the product_draft_created event.

    cluster_index:               shared dict {cluster_id: product_id}
    orchestrator:                Orchestrator instance
    recommendation_payload_store: shared dict {cluster_id: original Radar payload}
        Used to retrieve ICP, strategy, justification_summary and scores.
    """

    def handler(event: dict) -> None:
        """
        Called when product_draft_created is emitted by ProductLifeEngine.create_draft().
        """
        payload       = event.get("payload", event)
        product_id    = payload.get("product_id", "")
        opportunity_id= payload.get("opportunity_id", "")  # == cluster_id
        event_id      = payload.get("event_id", str(uuid.uuid4()))

        if not product_id or not opportunity_id:
            logger.warning(
                "[LandingDraftListener] Missing product_id or opportunity_id in event: %s",
                payload,
            )
            return

        cluster_id = opportunity_id

        # Update the in-memory index
        cluster_index[cluster_id] = product_id
        logger.info(
            "[LandingDraftListener] Mapped cluster_id=%s → product_id=%s",
            cluster_id, product_id,
        )

        # Retrieve original Radar payload for this cluster
        radar_payload = recommendation_payload_store.get(cluster_id, {})
        icp            = radar_payload.get("icp", "General audience")
        strategy       = radar_payload.get("strategy", "Value-based positioning")
        jsummary       = radar_payload.get("justification_summary", "")
        emotional      = float(radar_payload.get("emotional_score", 70.0))
        monetization   = float(radar_payload.get("monetization_score", 70.0))

        # Run full pipeline
        run_landing_pipeline(
            cluster_id            = cluster_id,
            product_id            = product_id,
            event_id              = event_id,
            icp                   = icp,
            strategy              = strategy,
            justification_summary = jsummary,
            emotional_score       = emotional,
            monetization_score    = monetization,
            orchestrator          = orchestrator,
        )

    return handler
