"""
radar/dashboard_output.py — Bloco 26 V2: Phase 8 Dashboard Output Layer

Purpose:
    Read-only aggregation of Radar pipeline results for dashboard display.
    Joins data from the three canonical JSONL audit files and returns a
    deterministic, ordered list of cluster opportunity cards.

Constitutional constraints:
    - ZERO executive authority
    - ZERO arithmetic / scoring logic
    - ZERO persistence writes
    - ZERO event emissions
    - ZERO calls to StrategicOpportunityEngine or any provider
    - Reads from JSONL files only; data returned verbatim
    - Ordered exclusively by score_final DESC (never by emotional/monetization/ICE)
    - status_elegibilidade derived from ice field verbatim (no extra rules)

Data sources (read-only):
    radar_score_results.jsonl     — score_final, emotional, monetization, growth, cluster_ratio, ice
    radar_metrics_snapshots.jsonl — noise, text_evidence (from validation_strategy.icp), cluster_id
    radar_ice_decisions.jsonl     — ice_classification (cross-reference for status_elegibilidade)
"""
from __future__ import annotations

import json
import os
from typing import Optional

from infrastructure.logger import get_logger

logger = get_logger("RadarDashboardOutput")

# ---------------------------------------------------------------------------
# JSONL default paths (same defaults as RadarEngine attributes)
# ---------------------------------------------------------------------------
_DEFAULT_SCORE_PATH    = "radar_score_results.jsonl"
_DEFAULT_METRICS_PATH  = "radar_metrics_snapshots.jsonl"
_DEFAULT_ICE_PATH      = "radar_ice_decisions.jsonl"

# Number of text evidence samples to surface per cluster (max 3, per spec)
_MAX_TEXT_EVIDENCE     = 3

# ICE value that produces NOT_QUALIFIED status
_ICE_BLOCKED           = "BLOQUEADO"


# ---------------------------------------------------------------------------
# Internal reader helpers (all read-only, no side effects)
# ---------------------------------------------------------------------------

def _read_jsonl(path: str) -> list[dict]:
    """
    Read all records from a JSONL file.

    Returns:
        List of dicts, one per valid line. Silently skips blank or malformed lines.
        Returns [] if file does not exist or cannot be opened.
    """
    records: list[dict] = []
    if not os.path.isfile(path):
        logger.debug(f"[DashboardOutput] File not found (empty result): {path}")
        return records
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    records.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass  # skip malformed lines silently
    except OSError as exc:
        logger.warning(f"[DashboardOutput] Cannot read {path}: {exc}")
    return records


def _index_by_cluster(records: list[dict], key: str = "cluster_id") -> dict[str, dict]:
    """
    Build dict keyed by cluster_id; last record wins (latest write = most current).
    Read-only — no mutation of input.
    """
    index: dict[str, dict] = {}
    for rec in records:
        cid = rec.get(key)
        if cid:
            index[cid] = rec
    return index


def _extract_text_evidence(metrics_record: Optional[dict]) -> list[str]:
    """
    Extract up to _MAX_TEXT_EVIDENCE text samples from a metrics snapshot record.

    Reads from validation_strategy.icp or falls back to []. No arithmetic.
    """
    if not metrics_record:
        return []
    strat = metrics_record.get("validation_strategy") or {}
    icp   = strat.get("icp", "")
    # Use icp as single narrative evidence item; future: expose raw text_samples
    if icp:
        return [icp[:200]]  # trim to reasonable length for display
    return []


def _derive_status(ice: str) -> str:
    """
    Derive status_elegibilidade from ice (verbatim rule, no extra logic).

    Returns "NOT_QUALIFIED" for BLOQUEADO, "QUALIFIED" for everything else.
    """
    return "NOT_QUALIFIED" if ice == _ICE_BLOCKED else "QUALIFIED"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_dashboard_cards(
    score_path:   str = _DEFAULT_SCORE_PATH,
    metrics_path: str = _DEFAULT_METRICS_PATH,
    ice_path:     str = _DEFAULT_ICE_PATH,
) -> list[dict]:
    """
    Build read-only dashboard opportunity cards from Radar pipeline JSONL files.

    Reads:
        score_path:   radar_score_results.jsonl
        metrics_path: radar_metrics_snapshots.jsonl
        ice_path:     radar_ice_decisions.jsonl

    Returns:
        List of dicts ordered by score_final DESC (highest first).

    Card schema (per specification):
        cluster_id          str
        dor_principal       str   — keyword / product_id from score record
        score_final         float — verbatim from score file
        emotional           float — verbatim from score file
        monetization        float — verbatim from score file
        growth              float — growth_score verbatim from score file
        noise               float — noise_score from metrics file (0.0 if absent)
        cluster_ratio       float — verbatim from score file
        ice                 str   — verbatim from score file
        status_elegibilidade str  — "QUALIFIED" | "NOT_QUALIFIED" (from ice)
        text_evidence       list  — max 3 samples from metrics validation_strategy

    Constitutional guarantees:
        - NO arithmetic operations on any field
        - NO calls to Core, providers, or Orchestrator
        - NO writes, mutations, or event emissions
        - Ordering key: score_final DESC only
    """
    logger.info("[DashboardOutput] Building dashboard cards (read-only)")

    # Step 1 — Load all three JSONL sources (read-only)
    score_records   = _read_jsonl(score_path)
    metrics_records = _read_jsonl(metrics_path)
    ice_records     = _read_jsonl(ice_path)

    if not score_records:
        logger.info("[DashboardOutput] No score records found — returning empty dashboard")
        return []

    # Step 2 — Index metrics and ice by cluster_id for O(1) lookup
    metrics_idx = _index_by_cluster(metrics_records, key="cluster_id")
    ice_idx     = _index_by_cluster(ice_records,     key="cluster_id")

    # Step 3 — Build one card per score record (verbatim copy, no math)
    cards: list[dict] = []
    for rec in score_records:
        cluster_id  = rec.get("cluster_id", "")
        ice_rec     = ice_idx.get(cluster_id)
        metrics_rec = metrics_idx.get(cluster_id)

        # ICE: prefer ice_decisions record (most explicit), fall back to score record
        ice = (ice_rec.get("ice_classification") if ice_rec else None) or rec.get("ice", "BLOQUEADO")

        noise = 0.0
        if metrics_rec:
            noise = float(metrics_rec.get("noise_score", 0.0))

        card = {
            "cluster_id":           cluster_id,
            "dor_principal":        rec.get("product_id", rec.get("cluster_id", "")),
            "score_final":          rec.get("score_final"),
            "emotional":            rec.get("emotional"),
            "monetization":         rec.get("monetization"),
            "growth":               rec.get("growth"),
            "noise":                noise,
            "cluster_ratio":        rec.get("cluster_ratio"),
            "ice":                  ice,
            "status_elegibilidade": _derive_status(ice),
            "text_evidence":        _extract_text_evidence(metrics_rec)[:_MAX_TEXT_EVIDENCE],
        }
        cards.append(card)

    # Step 4 — Sort EXCLUSIVELY by score_final DESC, no secondary key
    cards_sorted = sorted(
        cards,
        key=lambda c: float(c.get("score_final") or 0.0),
        reverse=True,
    )

    logger.info(
        f"[DashboardOutput] {len(cards_sorted)} card(s) built. "
        f"Top score_final={cards_sorted[0]['score_final'] if cards_sorted else 'n/a'}"
    )
    return cards_sorted


def get_qualified_cards(
    score_path:   str = _DEFAULT_SCORE_PATH,
    metrics_path: str = _DEFAULT_METRICS_PATH,
    ice_path:     str = _DEFAULT_ICE_PATH,
) -> list[dict]:
    """
    Return only QUALIFIED cards (ice != BLOQUEADO), ordered by score_final DESC.

    Pure filter on build_dashboard_cards() — no additional logic.
    """
    return [
        c for c in build_dashboard_cards(score_path, metrics_path, ice_path)
        if c["status_elegibilidade"] == "QUALIFIED"
    ]
