"""
radar/noise_filter.py — Bloco 26 V2: Noise Rejection Layer

Phase 3 constitutional gate between DatasetSnapshot and Core scoring.

Responsibilities:
  • Compute Noise_Filter_Score (0–100) from raw merged data
  • Apply 5 signal-quality rules sequentially
  • Emit "cluster_rejected_by_noise" event on rejection
  • Persist decision append-only to radar_noise_decisions.jsonl
  • Return structured result: {approved, noise_score, reason}

Constitutional contract (ENFORCED):
  ✓ Executes AFTER DatasetSnapshot is persisted (Phase 2.5)
  ✓ Executes BEFORE StrategicOpportunityEngine scoring (Phase 4)
  ✗ CANNOT alter Emotional Score
  ✗ CANNOT alter Monetization Score
  ✗ CANNOT alter Growth Score
  ✗ CANNOT create products or launch betas
  ✗ CANNOT modify system state
  ✗ Scoring NEVER runs if approved == False

Noise_Filter_Score formula:
  Score = (Occurrences × 0.35) + (Diversity × 0.30) + (Persistence × 0.25) - (Sarcasm × 0.10)
  Cutoff: score < 60 → REJECT
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from infrastructure.logger import get_logger

logger = get_logger("RadarNoiseFilter")

# ---------------------------------------------------------------------------
# Configuration thresholds
# ---------------------------------------------------------------------------
MIN_OCCURRENCES_PER_CLUSTER = 3       # Rule A: fewer signals → immediate reject
MAX_DOMINANT_SOURCE_RATIO   = 0.70    # Rule B: one source cannot exceed 70% of corpus
MIN_TEMPORAL_SPREAD_DAYS    = 2       # Rule C: spike isolation threshold
NOISE_SCORE_CUTOFF          = 60.0    # Rule E: final gate

# Persistence path for noise decisions
_NOISE_DECISIONS_LOG = "radar_noise_decisions.jsonl"

# Rule-based sarcasm/irony patterns (no ML required)
_SARCASM_PATTERNS = [
    re.compile(r"\b(yeah\s+right|sure\s+sure|oh\s+totally|as\s+if|wow\s+amazing|lol\s+no|pff+)\b", re.IGNORECASE),
    re.compile(r"\b(definitely\s+not|oh\s+sure|absolutely\s+not|right\s+\?)\b",                re.IGNORECASE),
    re.compile(r"(\.{3,}|!{3,}|\?{3,}|/s\b)",                                                 re.IGNORECASE),
]

_ISOLATING_KEYWORDS = ["trend", "viral", "hype", "overnight", "suddenly", "blew up", "one day"]


# ---------------------------------------------------------------------------
# Internal score helpers
# ---------------------------------------------------------------------------

def _compute_occurrence_score(occurrences: int) -> float:
    """
    Normalize occurrence count → 0–100.
    < 3   → 0   (rule A rejected before this)
    3–9   → 0–30
    10–49 → 30–60
    50–99 → 60–80
    ≥100  → 80–100
    """
    if occurrences < 3:
        return 0.0
    if occurrences < 10:
        return round(30.0 * (occurrences - 3) / 7, 2)
    if occurrences < 50:
        return round(30.0 + 30.0 * (occurrences - 10) / 40, 2)
    if occurrences < 100:
        return round(60.0 + 20.0 * (occurrences - 50) / 50, 2)
    return round(min(80.0 + 20.0 * (occurrences - 100) / 900, 100.0), 2)


def _compute_source_diversity_score(
    sources: list, source_counts: dict
) -> tuple:
    """
    Returns (diversity_score 0–100, rejection_reason or None).
    Penalises when any single source dominates > 70% of total volume.
    """
    if not source_counts:
        return 0.0, "source_counts empty"

    total    = max(sum(source_counts.values()), 1)
    max_share = max(source_counts.values()) / total

    if max_share > MAX_DOMINANT_SOURCE_RATIO:
        dominant = max(source_counts, key=source_counts.get)
        return 0.0, f"dominant_source={dominant} share={round(max_share * 100, 1)}% > 70%"

    n_sources           = len(set(sources))
    diversity_score     = min(n_sources / 5 * 100, 100.0)
    concentration_penalty = max_share * 50  # up to ~35 pts at 70% share
    return round(max(diversity_score - concentration_penalty, 0), 2), None


def _compute_persistence_score(temporal_spread_days: int) -> float:
    """
    Measures signal persistence over time.
    0d → 0 (spike with no persistence)
    1d → 20
    2–6d → 20–70
    ≥7d → 70–100
    """
    if temporal_spread_days <= 0:
        return 0.0
    if temporal_spread_days == 1:
        return 20.0
    if temporal_spread_days < 7:
        return round(20.0 + 50.0 * (temporal_spread_days - 1) / 5, 2)
    return round(min(70.0 + 30.0 * (temporal_spread_days - 7) / 23, 100.0), 2)


def _detect_sarcasm(texts: list) -> tuple:
    """
    Rule-based sarcasm/irony detection.
    Returns (hit_count, sarcasm_ratio 0.0–1.0).
    """
    hits  = 0
    total = max(len(texts), 1)
    for text in texts:
        for pattern in _SARCASM_PATTERNS:
            if pattern.search(text):
                hits += 1
                break
    return hits, round(hits / total, 4)


def _detect_isolated_spike(text_samples: list) -> bool:
    """
    Detect if corpus is dominated by isolation keywords suggesting a
    viral/one-time spike without genuine recurrence (≥ 3 keywords = spike).
    """
    combined = " ".join(text_samples).lower()
    hits = sum(1 for kw in _ISOLATING_KEYWORDS if kw in combined)
    return hits >= 3


# ---------------------------------------------------------------------------
# Persistence — append-only audit trail
# ---------------------------------------------------------------------------

def persist_noise_decision(
    result: dict,
    snapshot_id: str,
    persistence_path: str = _NOISE_DECISIONS_LOG,
) -> None:
    """
    Append-only persistence of a noise filter decision.

    Persists:
        snapshot_id, noise_score, approved, reason, timestamp
    """
    record = {
        "snapshot_id": snapshot_id,
        "noise_score": result.get("noise_score", 0.0),
        "approved":    result.get("approved", False),
        "reason":      result.get("reason"),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "detail":      result.get("detail", {}),
    }
    try:
        with open(persistence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[NoiseFilter] Could not persist decision: {exc}")


# ---------------------------------------------------------------------------
# Primary public function
# ---------------------------------------------------------------------------

def apply_noise_filter(
    cluster_data: dict,
    snapshot_id: str = "",
    orchestrator=None,
    persistence_path: str = _NOISE_DECISIONS_LOG,
) -> dict:
    """
    Phase 3 — Apply Bloco 26 V2 constitutional noise filter.

    Executes AFTER DatasetSnapshot is persisted (Phase 2.5).
    Executes BEFORE StrategicOpportunityEngine scoring (Phase 4).

    Expected cluster_data keys:
        sources              (list[str])      — data source identifiers
        source_counts        (dict[str, int]) — per-source volume counts
        occurrences          (int)            — total signal occurrences
        temporal_spread_days (int)            — days signal was observed
        text_samples         (list[str])      — raw text snippets (sarcasm detect)
        cluster_id           (str, optional)  — identifier for logging

    Returns:
        {
            "approved":    bool,
            "noise_score": float (0–100),
            "reason":      str | None,
            "detail": {
                "occurrence_score":         float,
                "diversity_score":          float,
                "persistence_score":        float,
                "sarcasm_ratio":            float,
                "isolated_spike":           bool,
                "dominant_source_rejected": bool,
            }
        }

    If rejected:
        → Emits "cluster_rejected_by_noise" event via orchestrator
        → Persists decision append-only to radar_noise_decisions.jsonl
        → Scoring (Phase 4) MUST NOT execute
    """
    cluster_id      = cluster_data.get("cluster_id", "unknown")
    sources         = cluster_data.get("sources", [])
    source_counts   = cluster_data.get("source_counts", {})
    occurrences     = int(cluster_data.get("occurrences", 0))
    temporal_spread = int(cluster_data.get("temporal_spread_days", 0))
    text_samples    = cluster_data.get("text_samples", [])

    rejection_reason: Optional[str] = None

    # ──────────────────────────────────────────────────────────────────
    # Rule A: Minimum occurrences — immediate hard reject
    # ──────────────────────────────────────────────────────────────────
    if occurrences < MIN_OCCURRENCES_PER_CLUSTER:
        result = {
            "approved":    False,
            "noise_score": 0.0,
            "reason":      f"cluster_too_small: occurrences={occurrences} < {MIN_OCCURRENCES_PER_CLUSTER}",
            "detail": {
                "occurrence_score":         0.0,
                "diversity_score":          0.0,
                "persistence_score":        0.0,
                "sarcasm_ratio":            0.0,
                "isolated_spike":           False,
                "dominant_source_rejected": False,
            },
        }
        _handle_rejection(result, cluster_id, snapshot_id, orchestrator, persistence_path)
        return result

    # ──────────────────────────────────────────────────────────────────
    # Component scores
    # ──────────────────────────────────────────────────────────────────
    occ_score                     = _compute_occurrence_score(occurrences)
    div_score, div_rejection_reason = _compute_source_diversity_score(sources, source_counts)
    pers_score                    = _compute_persistence_score(temporal_spread)
    _, sarcasm_ratio              = _detect_sarcasm(text_samples)
    is_spike                      = _detect_isolated_spike(text_samples)

    dominant_source_rejected = div_rejection_reason is not None

    # ──────────────────────────────────────────────────────────────────
    # Rule B: Dominant source (> 70%)
    # ──────────────────────────────────────────────────────────────────
    if dominant_source_rejected:
        rejection_reason = div_rejection_reason

    # ──────────────────────────────────────────────────────────────────
    # Rule C: Isolated spike without persistence
    # ──────────────────────────────────────────────────────────────────
    if is_spike and temporal_spread < MIN_TEMPORAL_SPREAD_DAYS:
        rejection_reason = rejection_reason or (
            f"isolated_spike: spread={temporal_spread}d < {MIN_TEMPORAL_SPREAD_DAYS}d"
        )

    # ──────────────────────────────────────────────────────────────────
    # Rule D: Sarcasm penalisation (applied in composite score)
    # ──────────────────────────────────────────────────────────────────
    sarcasm_penalty = sarcasm_ratio * 100 * 0.10  # max −10 pts

    # ──────────────────────────────────────────────────────────────────
    # Rule E: Composite Noise_Filter_Score
    # Formula: (Occurrences × 0.35) + (Diversity × 0.30) + (Persistence × 0.25) - (Sarcasm × 0.10)
    # ──────────────────────────────────────────────────────────────────
    raw_score = (
        (occ_score  * 0.35) +
        (div_score  * 0.30) +
        (pers_score * 0.25)
    ) - sarcasm_penalty

    noise_score = round(max(min(raw_score, 100.0), 0.0), 2)

    if noise_score < NOISE_SCORE_CUTOFF:
        rejection_reason = rejection_reason or (
            f"noise_score={noise_score} < {NOISE_SCORE_CUTOFF}"
        )

    approved = noise_score >= NOISE_SCORE_CUTOFF and rejection_reason is None

    result = {
        "approved":    approved,
        "noise_score": noise_score,
        "reason":      None if approved else rejection_reason,
        "detail": {
            "occurrence_score":         occ_score,
            "diversity_score":          div_score,
            "persistence_score":        pers_score,
            "sarcasm_ratio":            sarcasm_ratio,
            "isolated_spike":           is_spike,
            "dominant_source_rejected": dominant_source_rejected,
        },
    }

    if not approved:
        _handle_rejection(result, cluster_id, snapshot_id, orchestrator, persistence_path)
    else:
        # Persist approved decision too — full audit trail
        persist_noise_decision(result, snapshot_id, persistence_path)
        logger.info(
            f"[NoiseFilter] APPROVED cluster='{cluster_id}' "
            f"noise_score={noise_score} snapshot_id={snapshot_id}"
        )

    return result


# ---------------------------------------------------------------------------
# Internal: handle rejection — emit event + persist
# ---------------------------------------------------------------------------

def _handle_rejection(
    result: dict,
    cluster_id: str,
    snapshot_id: str,
    orchestrator,
    persistence_path: str,
) -> None:
    """Emit cluster_rejected_by_noise event and persist decision."""
    event = {
        "event_type":  "cluster_rejected_by_noise",
        "event_id":    str(uuid.uuid4()),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "cluster_id":  cluster_id,
        "snapshot_id": snapshot_id,
        "noise_score": result.get("noise_score", 0.0),
        "reason":      result.get("reason"),
    }

    if orchestrator is not None:
        try:
            orchestrator.receive_event(event)
        except Exception as exc:
            logger.warning(f"[NoiseFilter] Orchestrator event failed: {exc}")

    persist_noise_decision(result, snapshot_id, persistence_path)

    logger.warning(
        f"[NoiseFilter] REJECTED cluster='{cluster_id}' "
        f"noise_score={result.get('noise_score', 0.0)} "
        f"reason='{result.get('reason')}' snapshot_id={snapshot_id}"
    )
