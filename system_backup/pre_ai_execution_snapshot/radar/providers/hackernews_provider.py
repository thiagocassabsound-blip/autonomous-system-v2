import requests
from datetime import datetime, timezone, timedelta
from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

class HackerNewsProvider(BaseProvider):
    PROVIDER_NAME = "hackernews_api"
    SUPPORTED_SOURCES = ["hackernews"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        cutoff_ts = int((datetime.now(timezone.utc) - timedelta(days=query_spec.days_back)).timestamp())
        url = "https://hn.algolia.com/api/v1/search"
        params = {
            "query": query_spec.keyword,
            "numericFilters": f"created_at_i>{cutoff_ts}",
            "hitsPerPage": min(query_spec.max_per_source, 100)
        }
        
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return self._empty_response(f"HTTP {resp.status_code}")
                
            data = resp.json().get("hits", [])
            entries = []
            for item in data:
                text_content = item.get("story_text") or item.get("comment_text") or item.get("title") or ""
                entries.append({
                    "id": str(item.get("objectID")),
                    "title": item.get("title") or "HN Comment",
                    "text": text_content,
                    "url": item.get("url") or f"https://news.ycombinator.com/item?id={item.get('objectID')}",
                    "created_at": item.get("created_at"),
                    "score": item.get("points", 0),
                    "source": "hackernews"
                })
                
            if not entries:
                return self._empty_response("no hn signals")
                
            dates = [datetime.fromisoformat(e["created_at"].replace("Z", "+00:00")) for e in entries]
            spread_days = max(1, (max(dates) - min(dates)).days)
            
            return {
                "source": self.PROVIDER_NAME,
                "raw_entries": entries,
                "occurrence_count": len(entries),
                "timestamp_range": (min(dates).isoformat(), max(dates).isoformat()),
                "metadata": {
                    "keyword": query_spec.keyword,
                    "provider": self.PROVIDER_NAME
                },
                "text_samples": [e["text"][:200] for e in entries[:10]],
                "avg_pain_intensity": 0.0,
                "temporal_spread_days": spread_days,
                "sources_queried": ["hackernews"],
                "source_counts": {"hackernews": len(entries)},
            }
        except Exception as e:
            return self._empty_response(f"HN Error: {str(e)}")
