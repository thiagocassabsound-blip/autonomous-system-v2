"""
radar/providers/base_provider.py — Bloco 26 V2: Provider Interface Contract

All radar data providers MUST implement this interface.

Constitutional constraints for all providers:
  - CANNOT emit events
  - CANNOT persist data internally
  - CANNOT modify system state
  - CANNOT compute Emotional, Monetization, or Final scores
  - MUST return raw signal data only
  - MUST use RadarQuerySpec as input contract
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from radar.models.radar_query_spec import RadarQuerySpec


class BaseProvider(ABC):
    """
    Abstract base for all Radar data providers.

    Subclasses implement collect() only.
    No scoring. No persistence. No state changes. No event emission.
    """

    # Override in subclass
    PROVIDER_NAME: str = "base"
    SUPPORTED_SOURCES: list = []

    @abstractmethod
    def collect(self, query_spec: RadarQuerySpec) -> dict:
        """
        Collect raw signals for the given query specification.

        Args:
            query_spec: Validated RadarQuerySpec from input_layer.

        Returns:
            {
                "source":           str,          # provider identifier
                "raw_entries":      list[dict],   # raw signal items
                "occurrence_count": int,           # total raw items
                "timestamp_range":  tuple[str, str],  # (start_iso, end_iso)
                "metadata":         dict,          # provider-specific metadata
                # optional extended fields:
                "text_samples":            list[str],
                "avg_pain_intensity":      float,
                "temporal_spread_days":    int,
                "sources_queried":         list[str],
                "source_counts":           dict[str, int],
            }
        """
        ...

    # ------------------------------------------------------------------
    # Shared helpers — available to all providers, no side effects
    # ------------------------------------------------------------------

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _empty_response(self, reason: str = "no data") -> dict:
        now = self._now_iso()
        return {
            "source":           self.PROVIDER_NAME,
            "raw_entries":      [],
            "occurrence_count": 0,
            "timestamp_range":  (now, now),
            "metadata":         {"reason": reason, "provider": self.PROVIDER_NAME},
            "text_samples":            [],
            "avg_pain_intensity":      0.0,
            "temporal_spread_days":    0,
            "sources_queried":         [],
            "source_counts":           {},
        }
