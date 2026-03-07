"""
radar/dataset_snapshot.py — Bloco 26 V2: Phase 2.5 Dataset Snapshot Manager

Responsibilities:
  • Validate individual provider payload structure
  • Apply Phase 2 data quality gates (3 conditions)
  • Build RadarDatasetSnapshot from merged multi-provider data
  • Generate SHA-256 integrity hash (hash_integridade)
  • Persist append-only BEFORE any noise filter, cluster, or scoring

Phase 2 Quality Gates (applied BEFORE snapshot creation):
  Gate A: ≥ 3 distinct sources collected
  Gate B: total occurrence_count ≥ 100
  Gate C: timestamp_range within last 90 days

If any gate fails:
  → Emit "insufficient_data_for_analysis" event
  → Persist rejection record (append-only)
  → Return failure result — pipeline aborts, no noise/scoring

Constitutional constraints:
  - CANNOT compute Emotional Score
  - CANNOT compute Monetization Score
  - CANNOT compute Final Score
  - CANNOT modify system state
  - CANNOT call Orchestrator directly (uses orchestrator.receive_event)
  - Snapshot MUST be persisted BEFORE noise filter or scoring
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from infrastructure.logger import get_logger
from radar.models.radar_dataset_snapshot import RadarDatasetSnapshot

logger = get_logger("RadarDatasetSnapshot")

# ---------------------------------------------------------------------------
# Phase 2 configuration constants
# ---------------------------------------------------------------------------
MIN_DISTINCT_SOURCES  = 3   # Gate A: at least 3 distinct data sources
MIN_OCCURRENCES       = 100 # Gate B: at least 100 total signals
MAX_DATA_AGE_DAYS     = 90  # Gate C: all data must be within 90 days

# Required keys in every individual provider payload
_REQUIRED_PROVIDER_KEYS = {"source", "raw_entries", "occurrence_count", "timestamp_range", "metadata"}


# ---------------------------------------------------------------------------
# Phase 2.1 — Individual provider structural validation
# ---------------------------------------------------------------------------

def validate_provider_payload(payload: dict, provider_name: str = "unknown") -> None:
    """
    Validate that a single provider payload has the required structure.

    Raises:
        ValueError if any required field is missing or of wrong type
    """
    missing = _REQUIRED_PROVIDER_KEYS - set(payload.keys())
    if missing:
        raise ValueError(
            f"[DatasetSnapshot] Provider '{provider_name}' payload missing "
            f"required fields: {missing}"
        )
    if not isinstance(payload["raw_entries"], list):
        raise ValueError(
            f"[DatasetSnapshot] Provider '{provider_name}' raw_entries must be list, "
            f"got {type(payload['raw_entries']).__name__}"
        )
    if not isinstance(payload["occurrence_count"], (int, float)):
        raise ValueError(
            f"[DatasetSnapshot] Provider '{provider_name}' occurrence_count must be numeric"
        )
    if not isinstance(payload["metadata"], dict):
        raise ValueError(
            f"[DatasetSnapshot] Provider '{provider_name}' metadata must be dict"
        )


# ---------------------------------------------------------------------------
# Phase 2.2 — Data quality gates
# ---------------------------------------------------------------------------

def check_data_quality_gates(
    merged_data: dict,
    raw_payloads: list,
    query_spec_id: str,
    orchestrator=None,
    persistence_path: str = "radar_collection_rejections.jsonl",
) -> dict:
    """
    Apply three mandatory data quality gates to the merged collection.

    Gates:
        A) ≥ 3 distinct source identifiers across all providers
        B) total occurrence_count ≥ 100
        C) all timestamp_range endpoints within last 90 days

    Args:
        merged_data:    Output from _collect_from_providers()
        raw_payloads:   List of individual provider payloads
        query_spec_id:  Linked RadarQuerySpec event_id
        orchestrator:   Optional, for event emission on failure
        persistence_path: JSONL file for rejection records

    Returns:
        {"passed": True}                     — all gates passed
        {"passed": False, "reason": str, "gate": str}   — gate failed
    """
    now_utc     = datetime.now(timezone.utc)
    cutoff_date = now_utc - timedelta(days=MAX_DATA_AGE_DAYS)

    all_sources = list(merged_data.get("sources_queried", []))
    distinct_sources = len(set(all_sources))
    total_occurrences = int(merged_data.get("total_occurrences", 0))

    # --- Gate A: distinct sources ---
    if distinct_sources < MIN_DISTINCT_SOURCES:
        reason = (
            f"Gate A FAILED: only {distinct_sources} distinct source(s) collected, "
            f"minimum required = {MIN_DISTINCT_SOURCES}"
        )
        gate = "A_min_sources"
        return _handle_gate_failure(reason, gate, query_spec_id, orchestrator, persistence_path)

    # --- Gate B: occurrence count ---
    if total_occurrences < MIN_OCCURRENCES:
        reason = (
            f"Gate B FAILED: occurrence_count={total_occurrences} < "
            f"minimum required {MIN_OCCURRENCES}"
        )
        gate = "B_min_occurrences"
        return _handle_gate_failure(reason, gate, query_spec_id, orchestrator, persistence_path)

    # --- Gate C: data recency (timestamp check) ---
    ts_range = merged_data.get("timestamp_range", {})
    ts_start_str = ts_range.get("start", "") if isinstance(ts_range, dict) else ""
    if ts_start_str:
        try:
            ts_start = datetime.fromisoformat(ts_start_str.replace("Z", "+00:00"))
            # Make timezone-aware for comparison
            if ts_start.tzinfo is None:
                ts_start = ts_start.replace(tzinfo=timezone.utc)
            if ts_start < cutoff_date:
                reason = (
                    f"Gate C FAILED: earliest data timestamp {ts_start_str} "
                    f"is older than {MAX_DATA_AGE_DAYS} days (cutoff: {cutoff_date.isoformat()})"
                )
                gate = "C_data_recency"
                return _handle_gate_failure(reason, gate, query_spec_id, orchestrator, persistence_path)
        except (ValueError, TypeError) as exc:
            logger.warning(f"[DatasetSnapshot] Gate C: could not parse timestamp '{ts_start_str}': {exc}")

    logger.info(
        f"[DatasetSnapshot] All quality gates passed. "
        f"sources={distinct_sources} occurrences={total_occurrences} "
        f"recency_ok=True"
    )
    return {"passed": True}


def _handle_gate_failure(
    reason: str,
    gate: str,
    query_spec_id: str,
    orchestrator,
    persistence_path: str,
) -> dict:
    """Emit event, persist rejection record, return failure result."""
    event_id  = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    rejection_record = {
        "event_type":        "insufficient_data_for_analysis",
        "event_id":          event_id,
        "timestamp":         timestamp,
        "gate_failed":       gate,
        "reason":            reason,
        "query_spec_id":     query_spec_id,
    }

    # Append-only persistence
    try:
        with open(persistence_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rejection_record, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.warning(f"[DatasetSnapshot] Could not persist rejection: {exc}")

    # Emit event
    if orchestrator is not None:
        try:
            orchestrator.receive_event(rejection_record)
        except Exception as exc:
            logger.warning(f"[DatasetSnapshot] Orchestrator event failed: {exc}")

    logger.warning(f"[DatasetSnapshot] COLLECTION REJECTED. {reason}")

    return {
        "passed":   False,
        "reason":   reason,
        "gate":     gate,
        "event_id": event_id,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Phase 2.5 — Snapshot build, verify, persist
# ---------------------------------------------------------------------------

def build_snapshot(
    merged_data: dict,
    raw_payloads: list,
    query_spec_id: str,
) -> RadarDatasetSnapshot:
    """
    Build a RadarDatasetSnapshot from merged multi-provider data.

    Args:
        merged_data:      Merged output from RadarEngine._collect_from_providers()
        raw_payloads:     Individual raw provider payload dicts (for audit)
        query_spec_id:    event_id of the linked RadarQuerySpec

    Returns:
        RadarDatasetSnapshot — immutable, integrity-hashed, ready for persistence

    Raises:
        ValueError if merged_data is missing required fields
    """
    required = {"sources_queried", "source_counts", "total_occurrences", "provider"}
    missing  = required - set(merged_data.keys())
    if missing:
        raise ValueError(f"[DatasetSnapshot] Merged data missing required fields: {missing}")

    snapshot = RadarDatasetSnapshot.from_merged_provider_data(
        merged_data           = merged_data,
        raw_provider_payloads = raw_payloads,
        query_spec_id         = query_spec_id,
    )

    logger.info(
        f"[DatasetSnapshot] Built snapshot. snapshot_id={snapshot.snapshot_id} "
        f"keyword='{snapshot.keyword}' hash={snapshot.hash_integridade[:16]}... "
        f"occurrences={snapshot.occurrence_total} spread={snapshot.temporal_spread_days}d"
    )
    return snapshot


def persist_dataset_snapshot(
    snapshot: RadarDatasetSnapshot,
    persistence_path: str = "radar_dataset_snapshots.jsonl",
) -> None:
    """
    Append-only persistence of a RadarDatasetSnapshot.

    Format persisted:
        snapshot_id, query_spec_reference, collected_at,
        occurrence_total, sources, hash_integridade
        (raw_provider_payloads excluded from default persist for file size)

    MUST be called BEFORE noise filter, cluster analysis, or scoring.

    Constitutional guarantee: append-only, never overwrites.
    """
    line = json.dumps(snapshot.to_dict(), ensure_ascii=False)
    with open(persistence_path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
    logger.info(
        f"[DatasetSnapshot] Persisted. snapshot_id={snapshot.snapshot_id} "
        f"path={persistence_path} hash={snapshot.hash_integridade[:16]}..."
    )


def verify_integrity(snapshot: RadarDatasetSnapshot) -> bool:
    """
    Recompute and compare the hash_integridade.
    Returns True if intact, False if tamper detected.
    """
    import hashlib, json as _json

    canonical = _json.dumps({
        "query_spec_id":        snapshot.query_spec_id,
        "keyword":              snapshot.keyword,
        "sources_queried":      list(snapshot.sources_queried),
        "source_counts":        snapshot.source_counts,
        "total_occurrences":    snapshot.total_occurrences,
        "temporal_spread_days": snapshot.temporal_spread_days,
        "timestamp_start":      snapshot.timestamp_start,
        "timestamp_end":        snapshot.timestamp_end,
        "provider":             snapshot.provider,
        "event_id":             snapshot.event_id,
        "timestamp":            snapshot.timestamp,
        "version":              snapshot.version,
        "raw_provider_payloads": snapshot.raw_provider_payloads,
    }, sort_keys=True, separators=(",", ":"))

    expected = hashlib.sha256(canonical.encode()).hexdigest()
    intact   = expected == snapshot.integrity_hash

    if not intact:
        logger.warning(
            f"[DatasetSnapshot] INTEGRITY VIOLATION. "
            f"snapshot_id={snapshot.snapshot_id} "
            f"expected={expected[:16]}... got={snapshot.integrity_hash[:16]}..."
        )
    return intact


def build_and_persist_snapshot(
    provider_data: dict,
    query_spec_id: str,
    persistence_path: str = "radar_dataset_snapshots.jsonl",
) -> RadarDatasetSnapshot:
    """
    Backwards-compatible convenience: build from single provider_data and persist.
    Used by tests and older callers.
    """
    snapshot = RadarDatasetSnapshot.from_provider_data(
        provider_data = provider_data,
        query_spec_id = query_spec_id,
    )
    persist_dataset_snapshot(snapshot, persistence_path)
    return snapshot
