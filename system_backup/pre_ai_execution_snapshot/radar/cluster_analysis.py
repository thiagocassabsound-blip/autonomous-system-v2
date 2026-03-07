"""
radar/cluster_analysis.py — Bloco 26 V2: Phase 4 Cluster Analysis

Responsibilities:
  • Group raw signals from RadarDatasetSnapshot by semantic similarity
  • Build RadarCluster objects with aggregated_occurrences, sources_detected,
    timeline_distribution and auto-computed cluster_ratio
  • Report cluster saturation metrics (passed to Core as input)

Constitutional constraints:
  - CANNOT compute Emotional Score
  - CANNOT compute Monetization Score
  - CANNOT compute Final Score
  - cluster_ratio is INPUT to StrategicOpportunityEngine penalty
    (penalty is computed ONLY inside the Core, never here)
  - CANNOT modify snapshot (immutable by design)
  - CANNOT access providers
  - Runs AFTER Noise Filter approval (Phase 3) and
    BEFORE StrategicOpportunityEngine scoring (Phase 5)

Clustering strategy (rule-based, no ML dependency):
  • Keyword co-occurrence within text samples (Jaccard similarity)
  • Greedy assignment to first matching cluster
  • Temporal distribution from raw_provider_payloads entry dates
  • Source detection from provider metadata
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from infrastructure.logger import get_logger
from radar.models.radar_cluster import RadarCluster
from radar.models.radar_dataset_snapshot import RadarDatasetSnapshot

logger = get_logger("RadarClusterAnalysis")


# ---------------------------------------------------------------------------
# Semantic similarity helpers (rule-based, no ML)
# ---------------------------------------------------------------------------

_STOPWORDS = {
    "that", "this", "with", "have", "from", "they", "will", "been",
    "were", "when", "what", "your", "just", "into", "more", "also",
    "some", "than", "then", "there", "these", "those", "about", "like",
}


def _extract_keywords(text: str, min_length: int = 4) -> set:
    """Extract meaningful keywords (lowercase tokens ≥ min_length, no stopwords)."""
    tokens = re.findall(r"\b[a-zA-Z]{%d,}\b" % min_length, text.lower())
    return {t for t in tokens if t not in _STOPWORDS}


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two keyword sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union        = len(set_a | set_b)
    return round(intersection / union, 4) if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Timeline and source extraction from raw provider payloads
# ---------------------------------------------------------------------------

def _extract_timeline(raw_entries: list) -> dict:
    """
    Build a {date_str: count} timeline from raw signal entries.
    Falls back to bucketing by 'week_start' or 'month' if 'date' missing.
    """
    timeline: dict = defaultdict(int)
    for entry in raw_entries:
        date_key = (
            entry.get("date")
            or entry.get("week_start")
            or entry.get("month")
            or entry.get("collected_at", "")[:10]  # ISO date prefix
        )
        if date_key and len(date_key) >= 7:
            timeline[date_key[:10]] += 1
    return dict(timeline)


def _extract_sources_from_payloads(raw_payloads: list) -> list:
    """
    Collect distinct source names from a list of raw provider payloads.
    """
    sources = set()
    for payload in raw_payloads:
        src = payload.get("source") or payload.get("provider")
        if src:
            sources.add(src)
        sources.update(payload.get("sources_queried", []))
    return sorted(sources)


# ---------------------------------------------------------------------------
# Primary public function: build_clusters(snapshot) -> list[RadarCluster]
# ---------------------------------------------------------------------------

def build_clusters(
    snapshot: RadarDatasetSnapshot,
    similarity_threshold: float = 0.20,
    products_in_cluster: int = 0,
    total_active_products: int = 0,
) -> list:
    """
    Phase 4 — Group raw signals from a RadarDatasetSnapshot into RadarCluster objects.

    Algorithm:
        1. Extract text samples from snapshot (top 20 audit samples)
        2. Extract keywords per sample (Jaccard-based)
        3. Greedy clustering: assign to first cluster with sim ≥ threshold
        4. Compute aggregated_occurrences per cluster (proportional to signal share)
        5. Build timeline_distribution from raw_provider_payloads entry dates
        6. Detect distinct sources per cluster from sources_queried
        7. Auto-compute cluster_ratio in RadarCluster.__post_init__

    Constitutional guarantee:
        - Does NOT alter snapshot (immutable frozen dataclass)
        - Does NOT compute Emotional / Monetization / Final scores
        - cluster_ratio is an INPUT to the Core — NOT scored here

    Args:
        snapshot:              The RadarDatasetSnapshot (immutable) to cluster
        similarity_threshold:  Min Jaccard similarity to join a cluster (default 0.20)
        products_in_cluster:   Active products in same domain (for saturation reporting)
        total_active_products: Total active products (for saturation reporting)

    Returns:
        List of RadarCluster objects (≥ 1 if snapshot has any text samples)
    """
    texts    = list(snapshot.text_samples)
    total    = snapshot.total_occurrences
    snap_id  = snapshot.event_id
    keyword  = snapshot.keyword

    # --- Extract raw entries for timeline and source info ---
    raw_payloads: list = []
    try:
        raw_payloads = json.loads(snapshot.raw_provider_payloads)
    except (json.JSONDecodeError, AttributeError):
        raw_payloads = []

    all_raw_entries: list = []
    for payload in raw_payloads:
        all_raw_entries.extend(payload.get("raw_entries", []))

    global_timeline   = _extract_timeline(all_raw_entries)
    global_sources    = _extract_sources_from_payloads(raw_payloads)
    snapshot_sources  = list(snapshot.sources_queried) or global_sources

    if not texts:
        # No text samples — create a single synthetic cluster from snapshot metadata
        logger.warning(
            f"[ClusterAnalysis] No text samples in snapshot {snap_id}. "
            f"Creating synthetic cluster from metadata."
        )
        synthetic = _make_synthetic_cluster(
            snap_id    = snap_id,
            keyword    = keyword,
            total      = total,
            sources    = snapshot_sources,
            timeline   = global_timeline,
        )
        logger.info(
            f"[ClusterAnalysis] Synthetic cluster created. "
            f"ratio={synthetic.cluster_ratio:.4f}"
        )
        return [synthetic]

    # --- Step 1–3: Greedy keyword clustering ---
    keyword_sets = [_extract_keywords(t) for t in texts]
    clusters_data: list = []   # [{indices: set, keyword_union: set}]

    for i, kw_set in enumerate(keyword_sets):
        if not kw_set:
            kw_set = {"misc"}  # ensure every sample has at least one bucket
        placed = False
        for cd in clusters_data:
            sim = _jaccard_similarity(kw_set, cd["keyword_union"])
            if sim >= similarity_threshold:
                cd["indices"].add(i)
                cd["keyword_union"] |= kw_set
                placed = True
                break
        if not placed:
            clusters_data.append({"indices": {i}, "keyword_union": set(kw_set)})

    # --- Step 4–7: Build RadarCluster objects ---
    radar_clusters = []
    n_texts        = max(len(texts), 1)

    for idx, cd in enumerate(clusters_data):
        indices     = sorted(cd["indices"])
        n_in_cluster = len(indices)

        # Proportionally distribute total_occurrences across clusters
        aggregated_occ = round(total * n_in_cluster / n_texts)

        # Timeline subset: use the global timeline, bounded to cluster's proportional share
        cluster_timeline = {
            k: max(1, round(v * n_in_cluster / n_texts))
            for k, v in global_timeline.items()
        }
        if not cluster_timeline:
            cluster_timeline = {datetime.now(timezone.utc).isoformat()[:10]: aggregated_occ}

        cluster_kws = sorted(cd["keyword_union"])
        cluster_id  = hashlib.md5(f"{snap_id}:{idx}".encode()).hexdigest()[:12]
        label       = f"{keyword} cluster {idx + 1}"

        rc = RadarCluster(
            cluster_id                 = cluster_id,
            keywords                   = cluster_kws[:15],
            aggregated_occurrences     = aggregated_occ,
            sources_detected           = snapshot_sources,
            timeline_distribution      = cluster_timeline,
            total_snapshot_occurrences = total,
            label                      = label,
            dominant_theme             = cluster_kws[0] if cluster_kws else keyword,
            signal_ids                 = [f"{snap_id}:{i}" for i in indices],
            similarity_score           = round(n_in_cluster / n_texts, 4),
            snapshot_reference         = snap_id,
            source_distribution        = dict(json.loads(snapshot.source_counts)),
            temporal_span_days         = len(cluster_timeline),
            products_in_cluster        = products_in_cluster if idx == 0 else 0,
            total_active_products      = total_active_products,
        )
        radar_clusters.append(rc)
        logger.info(
            f"[ClusterAnalysis] Cluster formed. id={cluster_id} "
            f"signals={n_in_cluster}/{n_texts} "
            f"aggregated_occ={aggregated_occ} "
            f"cluster_ratio={rc.cluster_ratio:.4f} "
            f"keywords={len(cluster_kws)}"
        )

    return radar_clusters


# ---------------------------------------------------------------------------
# Legacy compatibility alias (used by radar_engine.py prior to Etapa 6)
# ---------------------------------------------------------------------------

def group_signals_into_clusters(
    snapshot: RadarDatasetSnapshot,
    similarity_threshold: float = 0.20,
    products_in_cluster: int = 0,
    total_active_products: int = 0,
) -> list:
    """
    Alias for build_clusters() — maintained for backwards compatibility
    with radar_engine.py Phase 5 calls and existing tests.
    """
    return build_clusters(
        snapshot               = snapshot,
        similarity_threshold   = similarity_threshold,
        products_in_cluster    = products_in_cluster,
        total_active_products  = total_active_products,
    )


# ---------------------------------------------------------------------------
# Saturation reporting
# ---------------------------------------------------------------------------

def compute_cluster_saturation(
    clusters: list,
    threshold_ratio: float = 0.30,
) -> dict:
    """
    Assess overall cluster saturation from a list of RadarCluster objects.

    Returns:
        {
            "total_clusters":     int,
            "saturated_clusters": int,   # those with cluster_ratio >= threshold
            "saturation_rate":    float,
            "requires_penalty":   bool,  # True if any cluster is saturated
        }

    Note: the PENALTY itself is computed in StrategicOpportunityEngine. This
    function only reports whether saturation conditions are present.
    """
    saturated = [c for c in clusters if c.cluster_ratio >= threshold_ratio]
    total     = max(len(clusters), 1)
    return {
        "total_clusters":     len(clusters),
        "saturated_clusters": len(saturated),
        "saturation_rate":    round(len(saturated) / total, 4),
        "requires_penalty":   len(saturated) > 0,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_synthetic_cluster(
    snap_id: str,
    keyword: str,
    total: int,
    sources: list,
    timeline: dict,
) -> RadarCluster:
    """Create a single synthetic cluster when no text samples are available."""
    if not timeline:
        timeline = {datetime.now(timezone.utc).isoformat()[:10]: total}
    cluster_id = hashlib.md5(f"{snap_id}:0".encode()).hexdigest()[:12]
    return RadarCluster(
        cluster_id                 = cluster_id,
        keywords                   = [keyword] if keyword else ["unknown"],
        aggregated_occurrences     = total,
        sources_detected           = sources,
        timeline_distribution      = timeline,
        total_snapshot_occurrences = total,
        label                      = f"{keyword} cluster 1",
        snap_reference             = snap_id if False else None,   # noqa
        snapshot_reference         = snap_id,
    )
