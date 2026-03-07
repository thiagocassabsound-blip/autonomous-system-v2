import os
import requests
from datetime import datetime
from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

class ProductHuntProvider(BaseProvider):
    PROVIDER_NAME = "producthunt_api"
    SUPPORTED_SOURCES = ["producthunt"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        ph_token = os.getenv("PRODUCT_HUNT_TOKEN")
        if not ph_token:
            return self._empty_response("PRODUCT_HUNT_TOKEN not configured")
            
        url = "https://api.producthunt.com/v2/api/graphql"
        headers = {
            "Authorization": f"Bearer {ph_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        # We search posts using graphql
        query = """
        query($searchStr: String!) {
          posts(search: $searchStr, first: 20) {
            edges {
              node {
                id
                name
                tagline
                description
                votesCount
                createdAt
                url
              }
            }
          }
        }
        """
        
        try:
            resp = requests.post(url, headers=headers, json={"query": query, "variables": {"searchStr": query_spec.keyword}}, timeout=10)
            if resp.status_code != 200:
                return self._empty_response(f"HTTP {resp.status_code}")
                
            data = resp.json()
            edges = data.get("data", {}).get("posts", {}).get("edges", [])
            entries = []
            
            for edge in edges:
                node = edge["node"]
                entries.append({
                    "id": str(node["id"]),
                    "title": node["name"],
                    "tagline": node["tagline"],
                    "text": node["description"],
                    "votes": node["votesCount"],
                    "created_at": node["createdAt"],
                    "url": node["url"],
                    "source": "producthunt"
                })
                
            if not entries:
                return self._empty_response("No product hunt results found")
                
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
                "text_samples": [e["tagline"] for e in entries[:10] if e["tagline"]],
                "avg_pain_intensity": 0.0,
                "temporal_spread_days": spread_days,
                "sources_queried": ["producthunt"],
                "source_counts": {"producthunt": len(entries)},
            }
        except Exception as e:
            return self._empty_response(f"ProductHunt API Error: {str(e)}")
