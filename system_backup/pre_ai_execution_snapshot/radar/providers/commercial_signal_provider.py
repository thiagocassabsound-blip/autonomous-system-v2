"""
radar/providers/commercial_signal_provider.py — Bloco 26 V2: Commercial Signal Provider

Collects commercial viability signals for a keyword:
  - Competitor product counts (market size proxy)
  - Price point distribution across existing solutions
  - Affiliate program availability (monetization proxy)
  - Customer reviews mentioning price / value gaps
  - Willingness-to-pay signals from community posts

Constitutional constraints:
  - DATA COLLECTOR ONLY
  - No scoring, no scoring fields returned
  - No Emotional computation (pain_intensity = 0.0 always)
  - No state writes, no persistence, no event emission
  - Implements collect(query_spec: RadarQuerySpec) -> dict

Production path: replace simulation with App Store / G2 / Capterra / Amazon adapter.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional

from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

# Price tier templates by category
_PRICE_TIERS = {
    "saas":          [(9, 29), (49, 149), (199, 499)],
    "info_product":  [(7, 27), (97, 197), (297, 997)],
    "service":       [(50, 200), (300, 800), (1000, 5000)],
    "e_commerce":    [(5, 25), (30, 80), (100, 300)],
    "subscription":  [(5, 19), (29, 79), (99, 299)],
    "marketplace":   [(0, 0), (10, 50), (100, 500)],
    "api_tool":      [(19, 99), (199, 499), (999, 2999)],
    "course":        [(27, 97), (197, 497), (997, 1997)],
}

# Commercial review signals
_COMMERCIAL_SIGNALS = [
    "I'd pay for a better solution to {keyword}",
    "Worth paying premium if {keyword} was solved properly",
    "Current {keyword} tools are overpriced for what they deliver",
    "I switched to paid plan just to get {keyword} working",
    "Need a affordable {keyword} option, enterprise pricing is ridiculous",
    "ROI on {keyword} tool is massive if it actually works",
    "Would buy immediately if {keyword} had this feature",
    "{keyword} market is underserved at the mid-tier price point",
    "Clients ask me about {keyword} budget constantly",
    "Spent 3 months looking for a good {keyword} solution, found nothing",
]


class CommercialSignalProvider(BaseProvider):
    """
    Simulates commercial viability data collection.

    Returns competitor counts, price distributions, affiliate availability
    and WTP signals for use in Phase 2 collection. No scoring.
    """

    PROVIDER_NAME    = "commercial_signal"
    SUPPORTED_SOURCES = ["g2", "capterra", "producthunt", "app_store", "amazon"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        """
        Collect commercial signals for query_spec.keyword.

        Returns:
            Standard provider payload. raw_entries contain commercial signal dicts.
            No Emotional/Monetization/Final scores.
        """
        keyword  = query_spec.keyword
        category = query_spec.category

        # Deterministic seed
        seed = int(hashlib.md5(f"commercial:{keyword}".encode()).hexdigest()[:6], 16)

        # Competitor landscape
        num_competitors = 5 + (seed % 25)   # 5–30 competitors
        price_tiers     = _PRICE_TIERS.get(category, [(10, 50), (100, 300), (500, 2000)])

        raw_entries = []
        base_date   = datetime.now(timezone.utc) - timedelta(days=query_spec.days_back)

        # Commercial WTP signal entries
        for i, tmpl in enumerate(_COMMERCIAL_SIGNALS):
            signal_text = tmpl.format(keyword=keyword)
            day_offset  = (seed + i * 9) % query_spec.days_back
            raw_entries.append({
                "text":     signal_text,
                "source":   "community_simulation",
                "date":     (base_date + timedelta(days=day_offset)).isoformat(),
                "type":     "wtp_signal",
                "keyword":  keyword,
            })

        # Competitor product entries (structural data, not reviews)
        for j in range(min(num_competitors, 10)):
            tier        = price_tiers[j % len(price_tiers)]
            price_point = tier[0] + ((seed + j * 7) % (tier[1] - tier[0] + 1))
            raw_entries.append({
                "type":          "competitor_product",
                "competitor_id": f"comp_{(seed + j * 13) % 9999:04d}",
                "category":      category,
                "price_usd":     price_point,
                "has_affiliate": (seed + j) % 3 == 0,
                "date":          (base_date + timedelta(days=(seed + j * 5) % query_spec.days_back)).isoformat(),
                "source":        "g2_simulation",
                "keyword":       keyword,
            })

        # Derived commercial metrics (raw — not scored)
        wtp_entries   = [e for e in raw_entries if e.get("type") == "wtp_signal"]
        comp_entries  = [e for e in raw_entries if e.get("type") == "competitor_product"]
        prices        = [e["price_usd"] for e in comp_entries]
        avg_price     = round(sum(prices) / max(len(prices), 1), 2)
        affiliate_pct = round(sum(1 for e in comp_entries if e.get("has_affiliate")) / max(len(comp_entries), 1) * 100, 1)

        dates       = []
        for e in raw_entries:
            try:
                dates.append(datetime.fromisoformat(e["date"]))
            except Exception:
                pass
        oldest      = min(dates) if dates else base_date
        newest      = max(dates) if dates else datetime.now(timezone.utc)
        spread_days = (newest - oldest).days
        text_samples = [e["text"] for e in wtp_entries]
        now_str     = datetime.now(timezone.utc).isoformat()

        return {
            "source":           self.PROVIDER_NAME,
            "raw_entries":      raw_entries,
            "occurrence_count": len(raw_entries),
            "timestamp_range":  (oldest.isoformat(), newest.isoformat()),
            "metadata": {
                "keyword":              keyword,
                "category":             category,
                "num_competitors":      num_competitors,
                "avg_competitor_price": avg_price,
                "affiliate_pct":        affiliate_pct,
                "wtp_signal_count":     len(wtp_entries),
                "simulation":           True,
                "version":              "1.0",
            },
            "text_samples":         text_samples,
            "avg_pain_intensity":   0.0,    # commercial signals have no pain intensity
            "temporal_spread_days": spread_days,
            "sources_queried":      ["g2_simulation", "community_simulation"],
            "source_counts": {
                "g2_simulation":         len(comp_entries),
                "community_simulation":  len(wtp_entries),
            },
            "keyword":        keyword,
            "is_real_data":   False,
            "timestamp":      now_str,
            "provider":       self.PROVIDER_NAME,
        }
