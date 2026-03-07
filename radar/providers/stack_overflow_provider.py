import requests
from datetime import datetime, timezone, timedelta
from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

class StackOverflowProvider(BaseProvider):
    PROVIDER_NAME = "stackoverflow_api"
    SUPPORTED_SOURCES = ["stackoverflow"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        limit = min(query_spec.max_per_source, 100)
        from_date = int((datetime.now(timezone.utc) - timedelta(days=query_spec.days_back)).timestamp())
        
        url = "https://api.stackexchange.com/2.3/search/advanced"
        params = {
            "order": "desc",
            "sort": "creation",
            "q": query_spec.keyword,
            "site": "stackoverflow",
            "pagesize": limit,
            "fromdate": from_date,
            "filter": "withbody" # to get the question body
        }
        
        try:
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return self._empty_response(f"HTTP {resp.status_code}")
                
            data = resp.json().get("items", [])
            entries = []
            for item in data:
                text_content = f"{item.get('title', '')} {item.get('body_markdown', '')}".strip()
                post_dt = datetime.fromtimestamp(item.get('creation_date', 0), timezone.utc)
                entries.append({
                    "id": str(item.get('question_id')),
                    "title": item.get('title'),
                    "text": text_content,
                    "url": item.get('link'),
                    "created_at": post_dt.isoformat(),
                    "score": item.get('score', 0),
                    "is_answered": item.get('is_answered', False),
                    "source": "stackoverflow"
                })
                
            if not entries:
                return self._empty_response("no stackoverflow signals")
                
            dates = [datetime.fromisoformat(e["created_at"]) for e in entries]
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
                "text_samples": [e["title"] for e in entries[:10]],
                "avg_pain_intensity": 0.0,
                "temporal_spread_days": spread_days,
                "sources_queried": ["stackoverflow"],
                "source_counts": {"stackoverflow": len(entries)},
            }
        except Exception as e:
            return self._empty_response(f"SO Error: {str(e)}")
