from __future__ import annotations
import os
import requests
from datetime import datetime, timezone, timedelta
from typing import Optional

from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

class RedditProvider(BaseProvider):
    PROVIDER_NAME = "reddit_api"
    SUPPORTED_SOURCES = ["reddit"]
    
    def collect(self, query_spec: RadarQuerySpec) -> dict:
        keyword = query_spec.keyword
        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        user_agent = "radar-b26v2/2.0 (constitutional data collector)"
        
        # We can try to use PRAW if installed and credentials exist,
        # otherwise fallback to public JSON API via requests.
        try:
            if client_id and client_secret:
                import praw
                reddit = praw.Reddit(
                    client_id=client_id,
                    client_secret=client_secret,
                    user_agent=user_agent
                )
                return self._collect_with_praw(reddit, query_spec)
        except ImportError:
            pass
            
        return self._collect_with_requests(query_spec)

    def _collect_with_requests(self, query_spec: RadarQuerySpec) -> dict:
        url = f"https://www.reddit.com/search.json?q={query_spec.keyword}&sort=relevance&limit={min(query_spec.max_per_source, 100)}"
        headers = {"User-Agent": "radar-b26v2/2.0 (constitutional data collector)"}
        
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code != 200:
                return self._empty_response(f"HTTP {response.status_code}")
                
            data = response.json()
            children = data.get("data", {}).get("children", [])
            entries = []
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=query_spec.days_back)
            
            for child in children:
                post = child.get("data", {})
                created_utc = post.get("created_utc")
                if not created_utc:
                    continue
                    
                post_dt = datetime.fromtimestamp(created_utc, timezone.utc)
                if post_dt < cutoff:
                    continue
                    
                text_content = f"{post.get('title', '')} {post.get('selftext', '')}".strip()
                if not text_content:
                    continue
                    
                entries.append({
                    "id": post.get("id"),
                    "title": post.get("title"),
                    "text": text_content,
                    "url": f"https://reddit.com{post.get('permalink')}",
                    "created_at": post_dt.isoformat(),
                    "score": post.get("score", 0),
                    "num_comments": post.get("num_comments", 0),
                    "source": "reddit"
                })
                
            return self._build_payload(entries, query_spec.keyword)
            
        except Exception as e:
            return self._empty_response(f"Reddit HTTP error: {str(e)}")
            
    def _collect_with_praw(self, reddit, query_spec) -> dict:
        try:
            entries = []
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(days=query_spec.days_back)
            
            for submission in reddit.subreddit("all").search(query_spec.keyword, sort="relevance", limit=query_spec.max_per_source):
                post_dt = datetime.fromtimestamp(submission.created_utc, timezone.utc)
                if post_dt < cutoff:
                    continue
                 
                text_content = f"{submission.title} {submission.selftext}".strip()
                entries.append({
                    "id": submission.id,
                    "title": submission.title,
                    "text": text_content,
                    "url": f"https://reddit.com{submission.permalink}",
                    "created_at": post_dt.isoformat(),
                    "score": submission.score,
                    "num_comments": submission.num_comments,
                    "source": "reddit"
                })
            
            return self._build_payload(entries, query_spec.keyword)
        except Exception as e:
            return self._empty_response(f"PRAW error: {str(e)}")
            
    def _build_payload(self, entries: list[dict], keyword: str) -> dict:
        if not entries:
            return self._empty_response("no signals found")
            
        dates = [datetime.fromisoformat(e["created_at"]) for e in entries]
        start_iso = min(dates).isoformat()
        end_iso = max(dates).isoformat()
        spread_days = max(1, (max(dates) - min(dates)).days)
        text_samples = [e["text"][:200] for e in entries[:10]]
        
        return {
            "source": self.PROVIDER_NAME,
            "raw_entries": entries,
            "occurrence_count": len(entries),
            "timestamp_range": (start_iso, end_iso),
            "metadata": {
                "keyword": keyword,
                "provider": self.PROVIDER_NAME,
                "avg_score": sum(e["score"] for e in entries) / len(entries) if entries else 0
            },
            "text_samples": text_samples,
            "avg_pain_intensity": 0.0,
            "temporal_spread_days": spread_days,
            "sources_queried": ["reddit"],
            "source_counts": {"reddit": len(entries)},
        }
