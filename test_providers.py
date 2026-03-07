import sys
import json
from datetime import datetime, timezone
from radar.models.radar_query_spec import RadarQuerySpec
from radar.providers import (
    RedditProvider,
    StackOverflowProvider,
    HackerNewsProvider,
    RealSearchIntentProvider,
    GoogleTrendsProvider,
    ProductHuntProvider
)

def test_providers():
    spec = RadarQuerySpec(
        keyword="productivity software",
        category="saas",
        segment="freelancers",
        publico="designers",
        contexto="needs time tracking",
        problema_alvo="wasting time on emails",
        days_back=7
    )

    providers = [
        RedditProvider(),
        StackOverflowProvider(),
        HackerNewsProvider(),
        RealSearchIntentProvider(),
        GoogleTrendsProvider(),
        ProductHuntProvider()
    ]
    
    results = {}
    for p in providers:
        print(f"Testing {p.PROVIDER_NAME}...")
        try:
            res = p.collect(spec)
            print(f"  -> SUCCESS! occurrence_count: {res.get('occurrence_count')}")
            results[p.PROVIDER_NAME] = "OK"
        except Exception as e:
            print(f"  -> FAILED! {e}")
            results[p.PROVIDER_NAME] = f"ERROR: {e}"
            
    print("\n--- Summary ---")
    for k, v in results.items():
        print(f"{k}: {v}")

if __name__ == "__main__":
    test_providers()
