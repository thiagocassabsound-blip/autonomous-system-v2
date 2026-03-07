"""
radar/providers/__init__.py
Radar V2 provider package.

Exports all data providers. Each provider:
  - Implements BaseProvider.collect(query_spec) -> dict
  - Returns raw signal data only (no scoring, no state writes)
  - Is pluggable into RadarEngine.providers list
"""
from radar.providers.base_provider import BaseProvider
from radar.providers.social_pain import collect_social_pain_signals
from radar.providers.search_intent_provider import SearchIntentProvider
from radar.providers.trend_provider import TrendProvider
from radar.providers.commercial_signal_provider import CommercialSignalProvider

# New Real Providers
from radar.providers.reddit_provider import RedditProvider
from radar.providers.stack_overflow_provider import StackOverflowProvider
from radar.providers.hackernews_provider import HackerNewsProvider
from radar.providers.search_intent_provider_real import RealSearchIntentProvider
from radar.providers.google_trends_provider import GoogleTrendsProvider
from radar.providers.product_hunt_provider import ProductHuntProvider
from radar.providers.synthetic_audit_provider import SyntheticAuditProvider

# Adapter class to wrap the functional social_pain API as a BaseProvider subclass
from radar.models.radar_query_spec import RadarQuerySpec as _RadarQuerySpec
from datetime import datetime, timezone as _tz


class SocialPainProvider(BaseProvider):
    """Adapter: wraps collect_social_pain_signals() as a BaseProvider."""

    PROVIDER_NAME     = "social_pain"
    SUPPORTED_SOURCES = ["reddit", "twitter", "quora", "hackernews", "youtube_comments", "forum"]

    def collect(self, query_spec: _RadarQuerySpec) -> dict:
        data = collect_social_pain_signals(
            keyword        = query_spec.keyword,
            sources        = list(query_spec.sources),
            max_per_source = query_spec.max_per_source,
            days_back      = query_spec.days_back,
        )
        # Ensure standard structure
        ts_range = data.get("timestamp_range", {})
        data["source"]           = self.PROVIDER_NAME
        data["raw_entries"]      = data.get("raw_signals", [])
        data["occurrence_count"] = data.get("total_occurrences", 0)
        data["timestamp_range"]  = (
            ts_range.get("start", datetime.now(_tz.utc).isoformat()),
            ts_range.get("end",   datetime.now(_tz.utc).isoformat()),
        )
        return data


__all__ = [
    "BaseProvider",
    "SocialPainProvider",
    "SearchIntentProvider",
    "TrendProvider",
    "CommercialSignalProvider",
    "RedditProvider",
    "StackOverflowProvider",
    "HackerNewsProvider",
    "RealSearchIntentProvider",
    "GoogleTrendsProvider",
    "ProductHuntProvider",
    "SyntheticAuditProvider",
]
