"""
radar/providers/trend_provider.py — Bloco 26 V2: Growth Trend Signal Provider

Collects temporal growth trend signals for a keyword:
  - Relative search interest over time (Google Trends proxy)
  - Growth velocity and acceleration
  - Trend classification (rising / stable / declining)
  - Week-over-week and month-over-month change rates

Constitutional constraints:
  - DATA COLLECTOR ONLY
  - No scoring, no scoring fields returned
  - No Emotional/Monetization computation
  - No state writes, no persistence, no event emission
  - Implements collect(query_spec: RadarQuerySpec) -> dict

Production path: replace simulation with Google Trends API / Pytrends adapter.
"""
from __future__ import annotations

import hashlib
import math
from datetime import datetime, timezone, timedelta
from typing import Optional

from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider


class TrendProvider(BaseProvider):
    """
    Simulates temporal search trend data for a keyword.

    Returns weekly interest indices and growth rate signals
    for use in Phase 2 collection. No scoring.
    """

    PROVIDER_NAME    = "trend"
    SUPPORTED_SOURCES = ["google_trends", "similarweb", "semrush_trends"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        """
        Collect trend signals for query_spec.keyword.

        Returns:
            Standard provider payload. raw_entries contain weekly data points.
            Includes growth_percent and growth_pattern for Phase 4 payload building.
            NO Emotional/Monetization/Final scores.
        """
        keyword  = query_spec.keyword
        days     = query_spec.days_back

        # Deterministic seed
        seed = int(hashlib.md5(f"trend:{keyword}".encode()).hexdigest()[:6], 16)

        # Simulate weekly relative interest (0–100 scale, trending upward)
        num_weeks   = max(days // 7, 4)
        base_index  = 30 + (seed % 40)       # starting interest index
        trend_bias  = ((seed % 30) - 10) / 100  # -0.10 to +0.20 weekly drift

        weekly_data  = []
        base_date    = datetime.now(timezone.utc) - timedelta(weeks=num_weeks)

        for w in range(num_weeks):
            week_date   = base_date + timedelta(weeks=w)
            noise       = math.sin(w * 0.8 + seed) * 8   # periodic noise
            index       = max(1, min(100, base_index + trend_bias * w * 100 + noise))
            weekly_data.append({
                "week_start":     week_date.isoformat(),
                "interest_index": round(index, 1),
                "source":         "google_trends_simulation",
                "keyword":        keyword,
            })

        # Compute growth metrics from weekly data
        start_idx     = weekly_data[0]["interest_index"]
        end_idx       = weekly_data[-1]["interest_index"]
        growth_pct    = round((end_idx - start_idx) / max(start_idx, 1) * 100, 2)

        mid           = len(weekly_data) // 2
        first_half    = sum(d["interest_index"] for d in weekly_data[:mid]) / max(mid, 1)
        second_half   = sum(d["interest_index"] for d in weekly_data[mid:]) / max(len(weekly_data) - mid, 1)
        acceleration  = round(second_half - first_half, 2)

        if growth_pct >= 20:
            trend_class = "rising_fast"
        elif growth_pct >= 5:
            trend_class = "rising"
        elif growth_pct >= -5:
            trend_class = "stable"
        else:
            trend_class = "declining"

        positive_trend = growth_pct >= 5

        # Weekly MoM (last vs previous month)
        last_4w   = [d["interest_index"] for d in weekly_data[-4:]]
        prev_4w   = [d["interest_index"] for d in weekly_data[-8:-4]] if len(weekly_data) >= 8 else last_4w
        mom_change = round((sum(last_4w) / len(last_4w)) - (sum(prev_4w) / len(prev_4w)), 2)

        oldest  = datetime.fromisoformat(weekly_data[0]["week_start"])
        newest  = datetime.fromisoformat(weekly_data[-1]["week_start"])
        now_str = datetime.now(timezone.utc).isoformat()

        return {
            "source":           self.PROVIDER_NAME,
            "raw_entries":      weekly_data,
            "occurrence_count": len(weekly_data),
            "timestamp_range":  (oldest.isoformat(), newest.isoformat()),
            "metadata": {
                "keyword":          keyword,
                "trend_class":      trend_class,
                "growth_pct":       growth_pct,
                "acceleration":     acceleration,
                "mom_change":       mom_change,
                "positive_trend":   positive_trend,
                "start_index":      start_idx,
                "end_index":        end_idx,
                "simulation":       True,
                "version":          "1.0",
            },
            # Extended fields for Phase 4 payload assembly
            "growth_percent":       growth_pct,
            "positive_trend":       positive_trend,
            "trend_class":          trend_class,
            "text_samples":         [
                f"{keyword} showing {trend_class} trend with {growth_pct}% growth",
                f"Interest index: {start_idx:.1f} -> {end_idx:.1f} over {num_weeks} weeks",
            ],
            "avg_pain_intensity":   0.0,    # trends have no pain intensity
            "temporal_spread_days": (newest - oldest).days,
            "sources_queried":      ["google_trends_simulation"],
            "source_counts":        {"google_trends_simulation": len(weekly_data)},
            "keyword":              keyword,
            "is_real_data":         False,
            "timestamp":            now_str,
            "provider":             self.PROVIDER_NAME,
        }
