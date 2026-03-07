from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers.base_provider import BaseProvider

class GoogleTrendsProvider(BaseProvider):
    PROVIDER_NAME = "google_trends_api"
    SUPPORTED_SOURCES = ["google_trends"]

    def collect(self, query_spec: RadarQuerySpec) -> dict:
        # Without PyTrends and valid cookies, Google Trends will block Python requests with 429 Too Many Requests.
        # So we try pytrends if installed, else fallback to empty dataset gracefully instead of breaking.
        try:
            import pytrends
            from pytrends.request import TrendReq
            
            pytrend = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
            pytrend.build_payload(kw_list=[query_spec.keyword], timeframe='today 3-m')
            df = pytrend.interest_over_time()
            
            if df.empty:
                return self._empty_response("No Google Trends data returned")
                
            # Process dataframe to raw entries
            entries = []
            for date, row in df.iterrows():
                if query_spec.keyword in row:
                    entries.append({
                        "date": date.isoformat(),
                        "interest": row[query_spec.keyword],
                        "source": "google_trends"
                    })
                    
            if not entries:
                return self._empty_response("No matching keywords in Google Trends dataframe")
                
            start_iso = entries[0]["date"]
            end_iso = entries[-1]["date"]
            
            # Simple growth computation
            start_idx = float(entries[0]["interest"])
            end_idx = float(entries[-1]["interest"])
            growth_pct = round((end_idx - start_idx) / max(start_idx, 1) * 100, 2)
            
            return {
                "source": self.PROVIDER_NAME,
                "raw_entries": entries,
                "occurrence_count": len(entries),
                "timestamp_range": (start_iso, end_iso),
                "metadata": {
                    "keyword": query_spec.keyword,
                    "provider": self.PROVIDER_NAME,
                    "trend_growth_pct": growth_pct
                },
                "text_samples": [],
                "avg_pain_intensity": 0.0,
                "temporal_spread_days": 90,
                "sources_queried": ["google_trends"],
                "source_counts": {"google_trends": len(entries)},
            }
        except ImportError:
            return self._empty_response("pytrends not installed - fallback to empty trends")
        except Exception as e:
            return self._empty_response(f"Trends Error: {str(e)}")
