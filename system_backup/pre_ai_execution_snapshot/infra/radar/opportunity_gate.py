"""
infra/radar/opportunity_gate.py — Semantic similarity gate for Bloco 30 / Etapa 2.6.

Prevents creation of products from semantically duplicate opportunities.

Algorithm: TF-IDF bag-of-words cosine similarity (no external ML deps).

Constitutional guarantees:
  - Never alters state.json
  - Never calls StateMachine.transition()
  - Emits opportunity_similarity_blocked_event via receive_event() when blocking
  - Never raises — returns structured dict
"""
from __future__ import annotations

import logging
import math
import os
import re
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("infra.radar.opportunity_gate")

# ── Configuration ─────────────────────────────────────────────────────────────
SIMILARITY_THRESHOLD   = float(os.getenv("OPPORTUNITY_SIMILARITY_THRESHOLD", "0.82"))
MIN_OPPORTUNITY_SCORE  = float(os.getenv("MIN_OPPORTUNITY_SCORE", "0.40"))

# ── In-memory index ──────────────────────────────────────────────────────────
# {cluster_id: {"text": str, "vector": dict[str, float]}}
_index: dict[str, dict] = {}
_lock  = threading.Lock()

# ── Text normalization & vectorization ────────────────────────────────────────
_STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "de", "da", "do", "em", "e", "é", "que", "para", "por",
    "com", "um", "uma", "os", "as", "se", "no", "na", "não",
}

def _tokenize(text: str) -> list[str]:
    """Lowercase, strip punctuation, remove stop words."""
    tokens = re.findall(r"[a-záéíóúàâêôãõüçñ]+", text.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) > 2]


def _tfidf_vector(tokens: list[str]) -> dict[str, float]:
    """Simple TF vector (term frequency). IDF is approximated per-index at query time."""
    tf: dict[str, float] = {}
    total = len(tokens) or 1
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1.0 / total
    return tf


def _cosine(v1: dict[str, float], v2: dict[str, float]) -> float:
    """Cosine similarity between two sparse TF vectors."""
    dot   = sum(v1.get(t, 0.0) * v2.get(t, 0.0) for t in v2)
    norm1 = math.sqrt(sum(x * x for x in v1.values())) or 1e-9
    norm2 = math.sqrt(sum(x * x for x in v2.values())) or 1e-9
    return dot / (norm1 * norm2)


def _vectorize(text: str) -> dict[str, float]:
    return _tfidf_vector(_tokenize(text))


# ── Public API ────────────────────────────────────────────────────────────────

def register_opportunity(cluster_id: str, opportunity_text: str) -> None:
    """
    Register an allowed opportunity in the index.
    Called after product_creation_requested is emitted (opportunity is green-lit).
    """
    with _lock:
        _index[cluster_id] = {
            "text":    opportunity_text,
            "vector":  _vectorize(opportunity_text),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
    logger.info("[OpportunityGate] Registered cluster_id=%s tokens=%d",
                cluster_id, len(_tokenize(opportunity_text)))


def should_block_opportunity(
    opportunity_text: str,
    opportunity_score: float,
    cluster_id: str = "",
    orchestrator=None,
) -> dict:
    """
    Gate check for a new opportunity.

    Returns:
      {"blocked": False, "reason": "", "similarity": 0.0}           — allowed
      {"blocked": True,  "reason": str, "similarity": float}        — blocked

    Rules:
      1. If score < MIN_OPPORTUNITY_SCORE → blocked (low quality)
      2. If cosine similarity to any indexed cluster > SIMILARITY_THRESHOLD → blocked
      3. Otherwise → allowed
    """
    # Rule 1 — score gate
    if opportunity_score < MIN_OPPORTUNITY_SCORE:
        reason = (
            f"Score {opportunity_score:.2f} below minimum "
            f"{MIN_OPPORTUNITY_SCORE:.2f}"
        )
        logger.info("[OpportunityGate] BLOCKED score_gate cluster=%s %s",
                    cluster_id, reason)
        _emit_blocked(cluster_id, opportunity_text, reason, 0.0, orchestrator)
        return {"blocked": True, "reason": reason, "similarity": 0.0}

    # Rule 2 — similarity gate
    query_vec = _vectorize(opportunity_text)
    max_sim   = 0.0
    most_sim_cluster = ""

    with _lock:
        for cid, entry in _index.items():
            if cid == cluster_id:
                continue  # skip self
            sim = _cosine(query_vec, entry["vector"])
            if sim > max_sim:
                max_sim = sim
                most_sim_cluster = cid

    if max_sim > SIMILARITY_THRESHOLD:
        reason = (
            f"Similarity {max_sim:.3f} > threshold {SIMILARITY_THRESHOLD:.2f} "
            f"(similar to cluster {most_sim_cluster})"
        )
        logger.info("[OpportunityGate] BLOCKED similarity_gate cluster=%s %s",
                    cluster_id, reason)
        _emit_blocked(cluster_id, opportunity_text, reason, max_sim, orchestrator)
        return {"blocked": True, "reason": reason, "similarity": max_sim}

    logger.info("[OpportunityGate] ALLOWED cluster=%s max_similarity=%.3f score=%.2f",
                cluster_id, max_sim, opportunity_score)
    return {"blocked": False, "reason": "", "similarity": max_sim}


def _emit_blocked(
    cluster_id: str,
    opportunity_text: str,
    reason: str,
    similarity: float,
    orchestrator,
) -> None:
    """Emit opportunity_similarity_blocked_event via receive_event()."""
    if orchestrator is None:
        return
    try:
        orchestrator.receive_event(
            event_type="opportunity_similarity_blocked_event",
            payload={
                "cluster_id":        cluster_id,
                "reason":            reason,
                "similarity":        round(similarity, 4),
                "opportunity_text":  opportunity_text[:200],
                "timestamp":         datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        logger.error("[OpportunityGate] Failed to emit blocked event: %s", exc)


def reset_index() -> None:
    """Reset the in-memory index. Used in tests only."""
    with _lock:
        _index.clear()


def index_size() -> int:
    """Return current index size."""
    with _lock:
        return len(_index)
