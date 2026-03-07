"""
radar/models/radar_query_spec.py — Bloco 26 V2: Phase 1 Input Specification

RadarQuerySpec is the immutable input contract for the Radar pipeline.
It is produced by input_layer.py and consumed by providers and dataset_snapshot.py.

Constitutional constraints:
  - Read-only after creation (frozen=True)
  - No state writes
  - No scoring
  - Validated at construction — no silent failures

V2 additions:
  - segment:        Market segment (e.g. "freelancers B2B")
  - publico:        Target audience description
  - contexto:       Business context / trigger
  - problema_alvo:  Specific pain problem being investigated
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional


ExecutionMode = Literal["autonomous", "assisted"]

VALID_CATEGORIES = {
    "saas", "info_product", "service", "e_commerce",
    "subscription", "marketplace", "api_tool", "course",
}

# Fields that must be non-empty strings in both modes
_REQUIRED_DOMAIN_FIELDS = ("segment", "publico", "contexto", "problema_alvo", "keyword", "category")


@dataclass(frozen=True)
class RadarQuerySpec:
    """
    Phase 1 — Immutable input specification for a Radar execution cycle.

    Core domain fields (mandatory, non-empty):
        keyword         : Core market/pain keyword to investigate
        category        : Product domain (must be in VALID_CATEGORIES)
        segment         : Market segment (e.g. "freelancers B2B", "SaaS founders")
        publico         : Target audience description
        contexto        : Business context / trigger (why this Radar is running)
        problema_alvo   : Specific pain being investigated

    Execution fields:
        execution_mode  : "autonomous" (system-driven) or "assisted" (human-driven)
        sources         : Data sources to query (at least 1 required)
        days_back       : Lookback window for signal collection (1–365)
        max_per_source  : Maximum signals per source (10–500)
        min_occurrences : Minimum signals required to qualify for noise filter

    Auto-generated fields:
        event_id        : Unique execution identifier (uuid4, auto-generated)
        timestamp       : UTC creation timestamp ISO-8601 (auto-generated)
        version         : Spec schema version (default "2")

    Optional fields:
        operator_id     : Required for "assisted" mode — human operator ID
        tags            : Optional metadata tags for downstream filtering
    """
    # --- Core domain fields ---
    keyword:        str
    category:       str
    segment:        str
    publico:        str
    contexto:       str
    problema_alvo:  str

    # --- Execution fields ---
    execution_mode:  ExecutionMode = "autonomous"
    sources:         tuple = ("reddit", "twitter", "quora", "hackernews")
    days_back:       int   = 90
    max_per_source:  int   = 100
    min_occurrences: int   = 50

    # --- Auto-generated fields ---
    event_id:  str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version:   str = "2"

    # --- Optional fields ---
    operator_id: Optional[str] = None
    tags:        tuple = ()

    def __post_init__(self) -> None:
        # 1. Validate all required domain string fields are non-empty
        for fname in _REQUIRED_DOMAIN_FIELDS:
            val = getattr(self, fname)
            if not isinstance(val, str) or not val.strip():
                raise ValueError(
                    f"RadarQuerySpec.{fname} must be a non-empty string, got: {val!r}"
                )

        # 2. Category must be valid
        if self.category not in VALID_CATEGORIES:
            raise ValueError(
                f"RadarQuerySpec.category='{self.category}' is not valid. "
                f"Must be one of: {sorted(VALID_CATEGORIES)}"
            )

        # 3. execution_mode
        if self.execution_mode not in ("autonomous", "assisted"):
            raise ValueError(
                f"RadarQuerySpec.execution_mode must be 'autonomous' or 'assisted', "
                f"got '{self.execution_mode}'"
            )

        # 4. Sources: at least one required
        if not self.sources:
            raise ValueError("RadarQuerySpec.sources must contain at least one source")

        # 5. Range constraints
        if not (1 <= self.days_back <= 365):
            raise ValueError(f"RadarQuerySpec.days_back={self.days_back} must be in [1, 365]")
        if not (10 <= self.max_per_source <= 500):
            raise ValueError(f"RadarQuerySpec.max_per_source={self.max_per_source} must be in [10, 500]")

        # 6. Assisted mode requires operator_id
        if self.execution_mode == "assisted" and not self.operator_id:
            raise ValueError("RadarQuerySpec.operator_id is required in 'assisted' mode")

        # 7. event_id must look like a uuid4
        if not self.event_id or len(self.event_id) != 36:
            raise ValueError(f"RadarQuerySpec.event_id is malformed: {self.event_id!r}")

        # 8. timestamp must be a non-empty ISO string
        if not self.timestamp or not self.timestamp.strip():
            raise ValueError("RadarQuerySpec.timestamp must be a non-empty ISO-8601 string")

    def to_dict(self) -> dict:
        return {
            "event_id":       self.event_id,
            "timestamp":      self.timestamp,
            "version":        self.version,
            # Domain fields
            "keyword":        self.keyword,
            "category":       self.category,
            "segment":        self.segment,
            "publico":        self.publico,
            "contexto":       self.contexto,
            "problema_alvo":  self.problema_alvo,
            # Execution fields
            "execution_mode":  self.execution_mode,
            "sources":         list(self.sources),
            "days_back":       self.days_back,
            "max_per_source":  self.max_per_source,
            "min_occurrences": self.min_occurrences,
            # Optional
            "operator_id":    self.operator_id,
            "tags":           list(self.tags),
        }
