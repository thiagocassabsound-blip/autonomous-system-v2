"""
radar/models/radar_cluster.py — Bloco 26 V2: Cluster Grouping Model

RadarCluster represents a semantically grouped set of signals sharing
a common pain theme. Produced by cluster_analysis.build_clusters().

Constitutional constraints:
  - NO Emotional score
  - NO Monetization score
  - NO Final Score
  - Only structural/semantic grouping data
  - cluster_ratio = aggregated_occurrences / total_occurrences
    → used by StrategicOpportunityEngine as INPUT for penalty calc
    → the penalty itself is computed ONLY inside the Core
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class RadarCluster:
    """
    Phase 4 — Semantic grouping of related pain signals from a RadarDatasetSnapshot.

    Mandatory fields (must be provided at construction):
        cluster_id              : Unique cluster identifier (short md5 hash)
        keywords                : Semantic keywords defining this cluster
        aggregated_occurrences  : Total raw signal count assigned to this cluster
        sources_detected        : Distinct data source names in this cluster
        timeline_distribution   : dict of {date_str: count} — temporal spread
        total_snapshot_occurrences: Total occurrences in the parent snapshot

    Auto-computed in __post_init__:
        cluster_ratio           : aggregated_occurrences / total_snapshot_occurrences
                                  → passed to StrategicOpportunityEngine, NOT scored here

    Optional/descriptive fields:
        label                   : Human-readable cluster label
        dominant_theme          : Best-fit theme description
        signal_ids              : References to raw signals (for traceability)
        similarity_score        : Internal cohesion score (0.0–1.0)
        snapshot_reference      : event_id of parent RadarDatasetSnapshot
        event_id                : Unique record identifier (uuid4, auto-generated)
        timestamp               : UTC creation timestamp (auto-generated)
        version                 : Model schema version

    Constitutional field aliases (read-only properties):
        occurrence_count        → aggregated_occurrences   (legacy compat)
        source_distribution     → sources dict             (legacy compat)
        temporal_span_days      → len(timeline_distribution) days coverage
    """
    # --- Mandatory fields ---
    cluster_id:                 str
    keywords:                   list
    aggregated_occurrences:     int
    sources_detected:           list          # list of distinct source names
    timeline_distribution:      dict          # {date_str: count}
    total_snapshot_occurrences: int           # denominator for cluster_ratio

    # --- Auto-computed (set in __post_init__) ---
    cluster_ratio:              float = 0.0   # aggregated_occ / total_snapshot_occ

    # --- Descriptive/optional ---
    label:                      str   = ""
    dominant_theme:             Optional[str] = None
    signal_ids:                 list  = field(default_factory=list)
    similarity_score:           float = 0.0
    snapshot_reference:         Optional[str] = None

    # --- Auto-generated ---
    event_id:   str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version:    str = "2"

    # --- Legacy compat fields (kept for radar_engine.py backward compat) ---
    source_distribution:    dict  = field(default_factory=dict)
    temporal_span_days:     int   = 0
    products_in_cluster:    int   = 0
    total_active_products:  int   = 0

    def __post_init__(self) -> None:
        # Validate aggregated_occurrences
        if self.aggregated_occurrences < 0:
            raise ValueError(
                f"RadarCluster.aggregated_occurrences must be >= 0, "
                f"got {self.aggregated_occurrences}"
            )

        # Auto-compute cluster_ratio = aggregated_occurrences / total_snapshot_occurrences
        # This is the ONLY place cluster_ratio is computed.
        # The Core uses this ratio as INPUT to its penalty formula — the penalty
        # is NOT computed here.
        if self.total_snapshot_occurrences > 0:
            computed_ratio = round(
                self.aggregated_occurrences / self.total_snapshot_occurrences, 4
            )
            self.cluster_ratio = min(computed_ratio, 1.0)
        else:
            self.cluster_ratio = 0.0

        # Validate similarity_score range
        if not (0.0 <= self.similarity_score <= 1.0):
            raise ValueError(
                f"RadarCluster.similarity_score must be in [0, 1], "
                f"got {self.similarity_score}"
            )

        # Fill label if not provided
        if not self.label:
            top_kw = self.keywords[0] if self.keywords else "unknown"
            self.label = f"cluster:{top_kw}"

        # Backfill legacy compat fields
        if not self.source_distribution:
            self.source_distribution = {src: 0 for src in self.sources_detected}
        if self.temporal_span_days == 0 and self.timeline_distribution:
            self.temporal_span_days = len(self.timeline_distribution)

    # --- Constitutional alias properties (read-only) ---
    @property
    def occurrence_count(self) -> int:
        """Legacy alias → aggregated_occurrences."""
        return self.aggregated_occurrences

    # --- Serialization ---
    def to_dict(self) -> dict:
        return {
            "event_id":                    self.event_id,
            "timestamp":                   self.timestamp,
            "version":                     self.version,
            "cluster_id":                  self.cluster_id,
            "label":                       self.label,
            "keywords":                    self.keywords,
            "aggregated_occurrences":      self.aggregated_occurrences,
            "occurrence_count":            self.aggregated_occurrences,  # alias
            "sources_detected":            self.sources_detected,
            "source_distribution":         self.source_distribution,
            "timeline_distribution":       self.timeline_distribution,
            "temporal_span_days":          self.temporal_span_days,
            "total_snapshot_occurrences":  self.total_snapshot_occurrences,
            "cluster_ratio":               self.cluster_ratio,
            "dominant_theme":              self.dominant_theme,
            "signal_ids":                  self.signal_ids,
            "similarity_score":            self.similarity_score,
            "snapshot_reference":          self.snapshot_reference,
        }
