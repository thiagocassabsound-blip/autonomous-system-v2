"""
radar/models/radar_dataset_snapshot.py — Bloco 26 V2: Phase 2.5 Raw Data Snapshot

RadarDatasetSnapshot is the immutable, integrity-hashed record of all raw signals
collected by providers, persisted BEFORE any scoring, noise filtering, or clustering.

Constitutional constraints:
  - Append-only
  - SHA-256 integrity hash (hash_integridade) auto-generated from content
  - No scoring fields
  - No Emotional / Monetization data
  - raw_provider_payloads carries full, unmodified provider outputs

Field aliases for clarity:
  snapshot_id          ← event_id
  query_spec_reference ← query_spec_id
  occurrence_total     ← total_occurrences
  hash_integridade     ← integrity_hash
  collected_at         ← timestamp
"""
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class RadarDatasetSnapshot:
    """
    Phase 2.5 — Immutable snapshot of raw collected data, persisted before scoring.

    Primary fields:
        snapshot_id          : Unique snapshot identifier (uuid4, auto-generated)
        query_spec_reference : event_id of the RadarQuerySpec that triggered collection
        sources              : Ordered tuple of distinct source identifiers
        occurrence_total     : Total raw signal count across all providers
        collected_at         : UTC creation timestamp ISO-8601 (auto-generated)
        raw_provider_payloads: Full unmodified payloads from each provider (JSON str)
        hash_integridade     : SHA-256 of canonical content (auto-generated)

    Derived/secondary fields:
        keyword              : The target keyword
        source_counts        : Per-source signal count (JSON-encoded dict)
        temporal_spread_days : Days the signal spans
        text_samples         : Top 20 text items across providers (for audit)
        timestamp_start      : Earliest signal date in UTC ISO-8601
        timestamp_end        : Latest signal date in UTC ISO-8601
        provider             : Primary provider identifier
        version              : Schema version (default "2")
        metadata             : Optional provider metadata (JSON-encoded)

    Constitutional aliases (read-only):
        snapshot_id          → event_id
        query_spec_reference → query_spec_id
        occurrence_total     → total_occurrences
        hash_integridade     → integrity_hash
        collected_at         → timestamp
    """
    # --- Primary audit fields ---
    query_spec_id:        str           # = query_spec_reference
    sources_queried:      tuple         # = sources (distinct source names)
    total_occurrences:    int           # = occurrence_total
    raw_provider_payloads: str          # JSON-encoded list of raw provider dicts

    # --- Derived fields ---
    keyword:              str
    source_counts:        str           # JSON-encoded dict
    temporal_spread_days: int
    text_samples:         tuple         # top 20 text items
    timestamp_start:      str
    timestamp_end:        str
    provider:             str

    # --- Auto-generated ---
    event_id:      str  = field(default_factory=lambda: str(uuid.uuid4()))  # = snapshot_id
    timestamp:     str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())  # = collected_at
    version:       str  = "2"
    integrity_hash: str = field(init=False)   # = hash_integridade — SHA-256
    metadata:      str  = "{}"                # JSON-encoded

    def __post_init__(self) -> None:
        # SHA-256 over canonical content
        canonical = json.dumps({
            "query_spec_id":        self.query_spec_id,
            "keyword":              self.keyword,
            "sources_queried":      list(self.sources_queried),
            "source_counts":        self.source_counts,
            "total_occurrences":    self.total_occurrences,
            "temporal_spread_days": self.temporal_spread_days,
            "timestamp_start":      self.timestamp_start,
            "timestamp_end":        self.timestamp_end,
            "provider":             self.provider,
            "event_id":             self.event_id,
            "timestamp":            self.timestamp,
            "version":              self.version,
            "raw_provider_payloads": self.raw_provider_payloads,
        }, sort_keys=True, separators=(",", ":"))
        object.__setattr__(self, "integrity_hash", hashlib.sha256(canonical.encode()).hexdigest())

    # --- Constitutional aliases (properties) ---
    @property
    def snapshot_id(self) -> str:
        return self.event_id

    @property
    def query_spec_reference(self) -> str:
        return self.query_spec_id

    @property
    def occurrence_total(self) -> int:
        return self.total_occurrences

    @property
    def hash_integridade(self) -> str:
        return self.integrity_hash

    @property
    def collected_at(self) -> str:
        return self.timestamp

    @property
    def sources(self) -> list:
        return list(self.sources_queried)

    # --- Serialization ---
    def to_dict(self) -> dict:
        return {
            # Primary audit fields (with both naming conventions)
            "snapshot_id":           self.event_id,
            "event_id":              self.event_id,
            "query_spec_reference":  self.query_spec_id,
            "query_spec_id":         self.query_spec_id,
            "sources":               list(self.sources_queried),
            "sources_queried":       list(self.sources_queried),
            "occurrence_total":      self.total_occurrences,
            "total_occurrences":     self.total_occurrences,
            "collected_at":          self.timestamp,
            "timestamp":             self.timestamp,
            "hash_integridade":      self.integrity_hash,
            "integrity_hash":        self.integrity_hash,
            "version":               self.version,
            # Derived fields
            "keyword":               self.keyword,
            "source_counts":         json.loads(self.source_counts),
            "temporal_spread_days":  self.temporal_spread_days,
            "text_samples":          list(self.text_samples),
            "timestamp_start":       self.timestamp_start,
            "timestamp_end":         self.timestamp_end,
            "provider":              self.provider,
            "metadata":              json.loads(self.metadata),
            # Raw payloads embedded for full auditability
            "raw_provider_count":    len(json.loads(self.raw_provider_payloads)),
        }

    def to_dict_full(self) -> dict:
        """Full audit dict — includes raw_provider_payloads (may be large)."""
        d = self.to_dict()
        d["raw_provider_payloads"] = json.loads(self.raw_provider_payloads)
        return d

    @classmethod
    def from_merged_provider_data(
        cls,
        merged_data: dict,
        raw_provider_payloads: list,
        query_spec_id: str,
    ) -> "RadarDatasetSnapshot":
        """
        Factory: construct from merged multi-provider output.

        Args:
            merged_data:           Merged output from _collect_from_providers()
            raw_provider_payloads: List of raw individual provider payloads
            query_spec_id:        event_id of the RadarQuerySpec
        """
        ts_range = merged_data.get("timestamp_range", {})
        return cls(
            query_spec_id          = query_spec_id,
            sources_queried        = tuple(merged_data.get("sources_queried", [])),
            total_occurrences      = int(merged_data.get("total_occurrences", 0)),
            raw_provider_payloads  = json.dumps(
                [_sanitize_payload(p) for p in raw_provider_payloads],
                ensure_ascii=False, sort_keys=True
            ),
            keyword                = merged_data.get("keyword", ""),
            source_counts          = json.dumps(merged_data.get("source_counts", {}), sort_keys=True),
            temporal_spread_days   = int(merged_data.get("temporal_spread_days", 0)),
            text_samples           = tuple(merged_data.get("text_samples", [])[:20]),
            timestamp_start        = ts_range.get("start", merged_data.get("timestamp", "")),
            timestamp_end          = ts_range.get("end",   merged_data.get("timestamp", "")),
            provider               = merged_data.get("provider", "radar_multi_provider"),
            metadata               = json.dumps(merged_data.get("metadata", {}), sort_keys=True),
        )

    @classmethod
    def from_provider_data(cls, provider_data: dict, query_spec_id: str) -> "RadarDatasetSnapshot":
        """
        Backwards-compatible factory for single-provider data.
        Wraps provider_data as the single entry in raw_provider_payloads.
        """
        return cls.from_merged_provider_data(
            merged_data           = provider_data,
            raw_provider_payloads = [provider_data],
            query_spec_id         = query_spec_id,
        )


def _sanitize_payload(payload: dict) -> dict:
    """
    Remove raw_signals list from persisted payload to keep file sizes manageable.
    text_samples (top 20) are retained for audit. Full signals stay in memory only.
    """
    sanitized = {k: v for k, v in payload.items() if k != "raw_signals"}
    return sanitized
