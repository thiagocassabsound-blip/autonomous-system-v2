"""
radar/providers/search_intent_provider.py — Bloco 26 V2: Search Intent Signal Provider

Collects commercial search intent signals around a keyword:
  - Keyword search volume proxies (simulated)
  - CPC/bid competition indicators
  - Related search queries and autocomplete signals
  - Question-based queries (how-to, best, vs, alternative)

Constitutional constraints:
  - DATA COLLECTOR ONLY
  - No scoring, no scoring fields returned
  - No state writes, no persistence, no event emission
  - No Emotional score computation
  - Implements collect(query_spec: RadarQuerySpec) -> dict

Production path: replace simulation with Google Ads API / SerpAPI / Semrush adapter.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

PROVIDER_NAME = "search_intent"

# Intent signal templates (simulated keyword query patterns)
_INTENT_TEMPLATES = [
    "best {keyword} tool",
    "alternatives to {keyword}",
    "how to fix {keyword} problem",
    "{keyword} vs competitors",
    "cheapest {keyword} solution",
    "{keyword} review 2025",
    "is {keyword} worth it",
    "{keyword} free alternative",
    "how to solve {keyword} issue",
    "best paid {keyword} software",
    "{keyword} pricing comparison",
    "top rated {keyword} tools",
]

# CPC tier simulation (proxy for monetization signal)
_CPC_TIERS = {
    "saas":          (8.0,  35.0),
    "info_product":  (2.0,  12.0),
    "service":       (5.0,  20.0),
    "e_commerce":    (0.5,   5.0),
    "subscription":  (6.0,  28.0),
    "marketplace":   (3.0,  15.0),
    "api_tool":      (7.0,  40.0),
    "course":        (1.5,  10.0),
}


class SearchIntentProvider(BaseProvider):
    """
    Simulates commercial search intent data collection.

    Returns query patterns, volume proxies, and CPC tier signals
    for use in Phase 2 collection. No scoring.
    """

    PROVIDER_NAME    = "search_intent"
    SUPPORTED_SOURCES = ["google_ads", "serpapi", "semrush", "ubersuggest"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        """
        Collect search intent signals for query_spec.keyword.

        Returns:
            Standard provider payload. raw_entries contain query pattern dicts.
            No Emotional/Monetization scores returned.
        """
        keyword  = query_spec.keyword
        category = query_spec.category

        # Deterministic seed for reproducible simulation
        seed = int(hashlib.md5(f"search_intent:{keyword}".encode()).hexdigest()[:6], 16)

        # Build raw intent entries
        raw_entries = []
        base_date   = datetime.now(timezone.utc) - timedelta(days=query_spec.days_back)

        for i, tmpl in enumerate(_INTENT_TEMPLATES):
            query_text  = tmpl.format(keyword=keyword)
            volume_prox = 1000 + ((seed + i * 137) % 49000)  # 1k–50k proxy
            day_offset  = (seed + i * 11) % query_spec.days_back

            raw_entries.append({
                "query":            query_text,
                "volume_proxy":     volume_prox,
                "source":           "google_ads_simulation",
                "date":             (base_date + timedelta(days=day_offset)).isoformat(),
                "is_question":      query_text.startswith(("how", "is", "what", "best", "why")),
                "is_commercial":    any(w in query_text for w in ("best", "paid", "price", "cheap", "buy")),
                "is_comparison":    "vs" in query_text or "alternative" in query_text,
            })

        # CPC tier range for the category
        cpc_min, cpc_max = _CPC_TIERS.get(category, (3.0, 15.0))
        avg_cpc = round(cpc_min + (seed % 100) / 100 * (cpc_max - cpc_min), 2)

        # Temporal spread
        dates         = [datetime.fromisoformat(e["date"]) for e in raw_entries]
        oldest        = min(dates)
        newest        = max(dates)
        spread_days   = (newest - oldest).days
        text_samples  = [e["query"] for e in raw_entries]
        now_str       = datetime.now(timezone.utc).isoformat()

        return {
            "source":           self.PROVIDER_NAME,
            "raw_entries":      raw_entries,
            "occurrence_count": len(raw_entries),
            "timestamp_range":  (oldest.isoformat(), newest.isoformat()),
            "metadata": {
                "keyword":          keyword,
                "category":         category,
                "avg_cpc_usd":      avg_cpc,
                "cpc_range":        [cpc_min, cpc_max],
                "commercial_count": sum(1 for e in raw_entries if e["is_commercial"]),
                "question_count":   sum(1 for e in raw_entries if e["is_question"]),
                "comparison_count": sum(1 for e in raw_entries if e["is_comparison"]),
                "simulation":       True,
                "version":          "1.0",
            },
            "text_samples":         text_samples,
            "avg_pain_intensity":   0.0,      # search intent has no pain intensity
            "temporal_spread_days": spread_days,
            "sources_queried":      ["google_ads_simulation"],
            "source_counts":        {"google_ads_simulation": len(raw_entries)},
            "keyword":              keyword,
            "is_real_data":         False,
            "timestamp":            now_str,
            "provider":             self.PROVIDER_NAME,
        }
