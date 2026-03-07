"""
infra/landing/landing_recommendation_handler.py — Main handler for Bloco 30.

This module provides:
  1. bootstrap(event_bus, orchestrator) — called at system START
  2. handle(self, payload, product_id, orchestrator) — called by Orchestrator
     via _sh_landing_recommendation

Constitutional guarantees:
  - Nunca altera state.json
  - Nunca chama StateMachine.transition()
  - Nunca instancia ProductLifeEngine
  - Nunca chama GuardianEngine
  - Usa receive_event(), nunca emit_event() para eventos governados
  - Respeita contenção financeira (Orchestrator bloqueia automaticamente)
  - Nunca ignora STRICT_MODE
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from infra.landing.landing_snapshot import load_snapshots, build_cluster_index
from infra.landing.landing_draft_listener import make_draft_listener

logger = logging.getLogger("infra.landing.recommendation_handler")

# ── Etapa 2.6 safeguards ─────────────────────────────────────────────────────
import os

# 2.6.2 — Product limit gate
MAX_ACTIVE_PRODUCTS = int(os.getenv("MAX_ACTIVE_PRODUCTS", "10"))


def _count_active_products() -> int:
    """Count unique product_ids in landing_snapshots.jsonl."""
    try:
        snapshots = load_snapshots()
        return len({s["product_id"] for s in snapshots if s.get("product_id")})
    except Exception:
        return 0

# ── Shared state (module-level, initialized in bootstrap) ────────────────────
_cluster_index: dict[str, str] = {}
"""
Persistent idempotency index: {cluster_id: product_id}.
Reconstructed from landing_snapshots.jsonl at bootstrap.
"""

_recommendation_payload_store: dict[str, dict] = {}
"""
Temporary store of Radar payloads keyed by cluster_id.
Allows LandingDraftListener to retrieve ICP, strategy, scores
when product_draft_created arrives asynchronously.
"""

_bootstrapped: bool = False


# ── Bootstrap ────────────────────────────────────────────────────────────────

def bootstrap(event_bus, orchestrator) -> None:
    """
    Called once at system START, before any run_cycle().

    Responsibilities:
      1. Register EventBus.subscribe("product_draft_created", handler)
      2. Read landing_snapshots.jsonl and rebuild cluster_index
         for idempotency persistence across restarts.

    Must be called in single-threaded bootstrap context.
    """
    global _bootstrapped

    if _bootstrapped:
        logger.warning("[Bloco30-Bootstrap] Already bootstrapped — skipping.")
        return

    # 1. Rebuild persistent cluster index from JSONL
    snapshots = []
    try:
        snapshots = load_snapshots()
        recovered = build_cluster_index(snapshots)
        _cluster_index.update(recovered)
        logger.info(
            "[Bloco30-Bootstrap] Cluster index rebuilt: %d entries from %d snapshots.",
            len(_cluster_index), len(snapshots),
        )
    except Exception as exc:
        logger.error(
            "[Bloco30-Bootstrap] Failed to rebuild cluster index: %s. "
            "Starting with empty index — idempotency not guaranteed for prior clusters.",
            exc,
        )

    # 1b. Reconstruct OpportunityGate index from snapshots (Etapa 2.6 fix)
    #     Registers each known cluster so the gate can detect duplicates post-restart.
    try:
        from infra.radar import opportunity_gate

        # Build a map of cluster_id → justification_summary from snapshots
        snap_map: dict[str, str] = {}
        for snap in snapshots:
            cid = snap.get("cluster_id", "")
            text = (
                snap.get("justification_summary")
                or snap.get("strategy")
                or snap.get("icp")
                or cid  # fallback: use cluster_id as identity token
            )
            if cid and text and cid not in snap_map:
                snap_map[cid] = str(text)

        for cid, text in snap_map.items():
            opportunity_gate.register_opportunity(cid, text)

        logger.info(
            "[Bloco30-Bootstrap] OpportunityGate index reconstructed: %d clusters.",
            len(snap_map),
        )
    except Exception as exc:
        logger.warning(
            "[Bloco30-Bootstrap] OpportunityGate reconstruction failed (non-blocking): %s", exc
        )

    # 2. Register subscribe for product_draft_created
    try:
        draft_handler = make_draft_listener(
            cluster_index              = _cluster_index,
            orchestrator               = orchestrator,
            recommendation_payload_store = _recommendation_payload_store,
        )
        event_bus.subscribe("product_draft_created", draft_handler)
        logger.info("[Bloco30-Bootstrap] Subscribed to product_draft_created.")
    except Exception as exc:
        logger.error(
            "[Bloco30-Bootstrap] Failed to subscribe to product_draft_created: %s", exc
        )

    _bootstrapped = True
    logger.info("[Bloco30-Bootstrap] Bootstrap complete.")


# ── SVC Handler (called by Orchestrator via _sh_landing_recommendation) ───────

def handle(
    orchestrator,
    payload: dict,
    product_id: str | None = None,
) -> None:
    """
    Primary entry point for expansion_recommendation_event.

    Called by Orchestrator._sh_landing_recommendation() after event is
    received and persisted to the ledger.

    Flow (Etapa 2.6 hardened):
        1. Validate payload completeness
        2. Validate ICE != BLOQUEADO
        3. Opportunity Gate (score + semantic similarity)
        4. Product limit gate (MAX_ACTIVE_PRODUCTS)
        5. Idempotency by cluster_id
        6. Store Radar payload for LandingDraftListener
        7. Generate version_id = str(uuid4())
        8. Register opportunity in OpportunityGate index
        9. Emit product_creation_requested via receive_event()

    Never calls ProductLifeEngine directly.
    Never uses emit_event() for governed events.
    Finance containment is enforced by Orchestrator automatically.
    """
    # ── 1. Payload validation ─────────────────────────────────────────────
    cluster_id = payload.get("cluster_id", "")
    if not cluster_id:
        logger.warning("[Bloco30-Handler] Missing cluster_id in payload — aborting.")
        return

    ice = payload.get("ice", "")
    if not ice:
        logger.warning(
            "[Bloco30-Handler] Missing ICE in payload for cluster_id=%s — aborting.", cluster_id
        )
        return

    # ── 2. ICE gate ───────────────────────────────────────────────────────
    if str(ice).upper() == "BLOQUEADO":
        logger.info(
            "[Bloco30-Handler] ICE=BLOQUEADO for cluster_id=%s — not creating landing.", cluster_id
        )
        return

    # ── 3. Opportunity Gate (Etapa 2.6.1) ─────────────────────────────────
    opportunity_text  = payload.get("justification_summary",
                                    payload.get("justification", ""))
    opportunity_score = float(payload.get("score_final",
                              payload.get("emotional_score", 50.0)))
    try:
        from infra.radar import opportunity_gate
        gate_result = opportunity_gate.should_block_opportunity(
            opportunity_text  = opportunity_text,
            opportunity_score = opportunity_score,
            cluster_id        = cluster_id,
            orchestrator      = orchestrator,
        )
        if gate_result["blocked"]:
            logger.info(
                "[Bloco30-Handler] OpportunityGate BLOCKED cluster_id=%s reason=%s",
                cluster_id, gate_result["reason"],
            )
            return
    except Exception as exc:
        logger.warning("[Bloco30-Handler] OpportunityGate check failed (non-blocking): %s", exc)

    # ── 4. Product limit gate (Etapa 2.6.2) ───────────────────────────────
    active_count = _count_active_products()
    if active_count >= MAX_ACTIVE_PRODUCTS:
        logger.warning(
            "[Bloco30-Handler] Product limit reached: %d/%d — blocking cluster_id=%s",
            active_count, MAX_ACTIVE_PRODUCTS, cluster_id,
        )
        try:
            orchestrator.receive_event(
                event_type="product_creation_blocked_event",
                payload={
                    "cluster_id":    cluster_id,
                    "active_count":  active_count,
                    "max_allowed":   MAX_ACTIVE_PRODUCTS,
                    "reason":        "MAX_ACTIVE_PRODUCTS limit reached",
                    "timestamp":     datetime.now(timezone.utc).isoformat(),
                },
            )
        except Exception as exc:
            logger.error("[Bloco30-Handler] Failed to emit product_creation_blocked_event: %s", exc)
        return

    # ── 5. Idempotency by cluster_id ──────────────────────────────────────
    if cluster_id in _cluster_index:
        existing_product_id = _cluster_index[cluster_id]
        logger.info(
            "[Bloco30-Handler] Idempotent: cluster_id=%s already has product_id=%s — skipping.",
            cluster_id, existing_product_id,
        )
        return

    # ── 6. Store Radar payload for async retrieval by LandingDraftListener
    _recommendation_payload_store[cluster_id] = {
        "icp":                  payload.get("icp", "General audience interested in the topic"),
        "strategy":             payload.get("strategy", payload.get("recommendation", "Value-based positioning")),
        "justification_summary": payload.get("justification_summary", payload.get("justification", "")),
        "emotional_score":      float(payload.get("emotional_score", 70.0)),
        "monetization_score":   float(payload.get("monetization_score", 70.0)),
    }

    # ── 7. Generate version_id ────────────────────────────────────────────
    version_id = str(uuid.uuid4())

    # ── 8. Build justification_snapshot ──────────────────────────────────
    justification_snapshot = {
        "cluster_id":             cluster_id,
        "ice":                    str(ice),
        "score_final":            payload.get("score_final"),
        "emotional_score":        payload.get("emotional_score"),
        "monetization_score":     payload.get("monetization_score"),
        "growth_percent":         payload.get("growth_percent"),
        "strategy":               payload.get("strategy", payload.get("recommendation", "")),
        "justification_summary":  payload.get("justification_summary", payload.get("justification", "")),
        "generated_at":           datetime.now(timezone.utc).isoformat(),
    }

    # ── 8b. Register opportunity in gate index (post-approval) ────────────
    try:
        from infra.radar import opportunity_gate
        opportunity_gate.register_opportunity(cluster_id, opportunity_text)
    except Exception as exc:
        logger.warning("[Bloco30-Handler] OpportunityGate registration failed: %s", exc)

    # ── 9. Emit product_creation_requested via receive_event() ────────────
    logger.info(
        "[Bloco30-Handler] Emitting product_creation_requested for cluster_id=%s version_id=%s",
        cluster_id, version_id,
    )
    try:
        orchestrator.receive_event(
            event_type="product_creation_requested",
            payload={
                "opportunity_id":        cluster_id,
                "emotional_score":       float(payload.get("emotional_score", 70.0)),
                "monetization_score":    float(payload.get("monetization_score", 70.0)),
                "growth_percent":        float(payload.get("growth_percent", 0.0)),
                "justification_snapshot": justification_snapshot,
                "version_id":            version_id,
            },
        )
    except Exception as exc:
        logger.error(
            "[Bloco30-Handler] Failed to emit product_creation_requested "
            "for cluster_id=%s: %s",
            cluster_id, exc,
        )
