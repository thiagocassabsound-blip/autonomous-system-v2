import os
import requests
from datetime import datetime
from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

class RealSearchIntentProvider(BaseProvider):
    PROVIDER_NAME = "search_intent_api"
    SUPPORTED_SOURCES = ["serper"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        serper_api_key = os.getenv("SERPER_API_KEY")
        if not serper_api_key:
            return self._empty_response("SERPER_API_KEY not configured")
            
        url = "https://google.serper.dev/search"
        headers = {
            "X-API-KEY": serper_api_key,
            "Content-Type": "application/json"
        }
        
        # Test commercial/problem intent keyword
        payload = {"q": f"{query_spec.problema_alvo} alternative or software"}
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            if resp.status_code != 200:
                return self._empty_response(f"HTTP {resp.status_code}")
                
            data = resp.json()
            organic = data.get("organic", [])
            related_searches = [r.get("query") for r in data.get("relatedSearches", [])]
            
            # Extract simple CPC/intent indicators
            has_ads = bool(data.get("ads", []))
            has_shopping = bool(data.get("shopping", []))
            commercial_intent_detected = has_ads or has_shopping
            
            entries = []
            
            now_iso = self._now_iso()
            
            for index, item in enumerate(organic):
                entries.append({
                    "rank": index + 1,
                    "title": item.get("title"),
                    "link": item.get("link"),
                    "snippet": item.get("snippet"),
                    "source": "google_search"
                })
                
            if not entries:
                return self._empty_response("No organic search results found")
                
            return {
                "source": self.PROVIDER_NAME,
                "raw_entries": entries,
                "occurrence_count": len(entries),
                "timestamp_range": (now_iso, now_iso),
                "metadata": {
                    "keyword": query_spec.keyword,
                    "provider": self.PROVIDER_NAME,
                    "commercial_intent": commercial_intent_detected,
                    "related_searches": related_searches[:5],
                    "cpc_indicator": 1.0 if commercial_intent_detected else 0.5
                },
                "text_samples": [e["snippet"] for e in entries[:10] if e["snippet"]],
                "avg_pain_intensity": 0.0,
                "temporal_spread_days": 1,
                "sources_queried": ["google_search_via_serper"],
                "source_counts": {"google_search_via_serper": len(entries)},
            }
        except Exception as e:
            return self._empty_response(f"Serper API Error: {str(e)}")
