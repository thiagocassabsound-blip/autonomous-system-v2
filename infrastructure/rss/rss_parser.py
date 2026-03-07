import feedparser
from datetime import datetime, timezone
import logging

logger = logging.getLogger("rss_parser")

class RSSParser:
    @staticmethod
    def fetch_and_extract(source_dict):
        results = []
        try:
            feed = feedparser.parse(source_dict["rss_url"])
            if feed.bozo and hasattr(feed, "bozo_exception"):
                logger.warning(f"Malformed feed detected for {source_dict['source_name']}: {feed.bozo_exception}")
            
            for entry in feed.entries:
                title = getattr(entry, "title", "No Title")
                description = getattr(entry, "summary", getattr(entry, "description", ""))
                url = getattr(entry, "link", "")
                
                # Timestamp parsing
                try:
                    if hasattr(entry, "published_parsed") and entry.published_parsed:
                        import time
                        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
                        timestamp_iso = dt.isoformat()
                    else:
                        timestamp_iso = datetime.now(timezone.utc).isoformat()
                except Exception:
                    timestamp_iso = datetime.now(timezone.utc).isoformat()
                    
                results.append({
                    "title": title,
                    "description": description,
                    "url": url,
                    "timestamp": timestamp_iso,
                    "source_name": source_dict["source_name"],
                    "category": source_dict["category"]
                })
        except Exception as e:
            logger.error(f"Failed to fetch RSS feed {source_dict['source_name']}: {e}")
        return results
