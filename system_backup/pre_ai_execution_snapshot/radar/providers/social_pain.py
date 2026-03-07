"""
radar/providers/social_pain.py — Bloco 26 V2: Social Pain Signal Provider

DATA COLLECTOR ONLY. No scoring. No state writes. No Orchestrator calls.

Collection strategy (two-layer, no OAuth required):
  1. Reddit public JSON API (no auth, rate-limit friendly)
  2. Deterministic simulation fallback (always works offline)

Output feeds directly into RadarDatasetSnapshot in Phase 2.
"""
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROVIDER_NAME      = "social_pain"
SUPPORTED_SOURCES  = ["reddit", "twitter", "quora", "hackernews", "youtube_comments", "forum"]
REDDIT_API_TIMEOUT = 10
REDDIT_USER_AGENT  = "radar-b26v2/2.0 (constitutional data collector, no auth)"

# Pain / frustration pattern detection
_PAIN_PATTERNS = [
    re.compile(
        r"\b(hate|struggle|pain|problem|issue|bug|broken|frustrat|fail|annoying|"
        r"worst|terrible|impossible|can't|doesn't work|slow|useless|nightmare|tedious)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(why (is|does|can't|won't)|how (do|can) I fix|help me|anyone else having|"
        r"ugh+|wtf|fml|so annoying)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(I wish|if only|why doesn't|there's no|no way to|missing feature|"
        r"please add|needs to be fixed)\b",
        re.IGNORECASE,
    ),
]
_SOLUTION_SIGNALS = [
    re.compile(
        r"\b(solved|fixed|works great|love it|perfect|amazing|best|recommend|definitely use)\b",
        re.IGNORECASE,
    ),
]


# ---------------------------------------------------------------------------
# Pain intensity scorer (per text item)
# ---------------------------------------------------------------------------

def _compute_pain_intensity(text: str) -> float:
    pain_hits     = sum(1 for p in _PAIN_PATTERNS    if p.search(text))
    solution_hits = sum(1 for p in _SOLUTION_SIGNALS if p.search(text))
    raw     = pain_hits / max(len(_PAIN_PATTERNS), 1)
    penalty = solution_hits * 0.20
    return round(max(min(raw - penalty, 1.0), 0.0), 4)


# ---------------------------------------------------------------------------
# Real Reddit JSON provider (no OAuth, public endpoint)
# ---------------------------------------------------------------------------

def _fetch_reddit(keyword: str, limit: int = 100) -> tuple[list, bool]:
    """
    Fetch posts from Reddit's public search JSON endpoint.
    Returns (signals: list[dict], is_real_data: bool).
    """
    url = (
        "https://www.reddit.com/search.json"
        f"?q={urllib.parse.quote(keyword)}"
        f"&type=link&sort=relevance&t=month&limit={min(limit, 100)}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": REDDIT_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=REDDIT_API_TIMEOUT) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return [], False

    signals = []
    children = raw.get("data", {}).get("children", [])
    for child in children:
        post     = child.get("data", {})
        title    = post.get("title", "")
        selftext = post.get("selftext", "")
        text     = f"{title} {selftext}".strip()
        created  = post.get("created_utc", time.time())
        upvotes  = post.get("score", 0)
        if not text:
            continue
        signals.append({
            "text":      text,
            "upvotes":   upvotes,
            "date":      datetime.fromtimestamp(created, tz=timezone.utc).isoformat(),
            "source":    "reddit",
            "subreddit": post.get("subreddit", ""),
        })
    return signals, len(signals) > 0


# ---------------------------------------------------------------------------
# Simulation fallback (deterministic, always available offline)
# ---------------------------------------------------------------------------

def _simulate_source_fetch(source: str, keyword: str, limit: int = 30) -> list:
    """Returns deterministic mock signals for the given source and keyword."""
    seed_hash = int(hashlib.md5(f"{source}{keyword}".encode()).hexdigest()[:6], 16)
    rng_seed  = seed_hash % 10000

    templates = [
        f"I really struggle with {keyword} every single day",
        f"Why is {keyword} so incredibly frustrating to deal with",
        f"Anyone else annoyed by {keyword}? It's broken",
        f"I wish there was a better solution for {keyword}",
        f"{keyword} doesn't work at all, worst experience I've had",
        f"Can't believe {keyword} still has this problem",
        f"Please fix {keyword}, it's impossible to use properly",
        f"{keyword} is a nightmare for my workflow",
        f"The {keyword} issue has been making my job so much harder",
        f"I hate that {keyword} is so slow and unreliable",
        f"Why doesn't {keyword} have a proper fix yet?",
        f"Struggling with {keyword} for months now, nothing works",
    ]

    base_date = datetime.now(timezone.utc) - timedelta(days=85)
    results   = []
    for i, tmpl in enumerate(templates[: min(limit, len(templates))]):
        day_offset = (rng_seed + i * 7) % 90
        results.append({
            "text":    tmpl,
            "upvotes": (rng_seed + i * 11) % 500,
            "date":    (base_date + timedelta(days=day_offset)).isoformat(),
            "source":  source,
        })
    return results


# ---------------------------------------------------------------------------
# Primary public function
# ---------------------------------------------------------------------------

def collect_social_pain_signals(
    keyword: str,
    sources: Optional[list] = None,
    max_per_source: int = 100,
    days_back: int = 90,
) -> dict:
    """
    Collect pain signals for a keyword.

    Tries the real Reddit JSON API first (no auth required).
    Falls back to deterministic simulation for unavailable sources.

    Returns a constitutional Phase 2 snapshot dict:
    {
        provider, keyword, timestamp, timestamp_range,
        is_real_data, sources_queried, source_counts,
        total_occurrences, occurrence_count,
        temporal_spread_days, avg_pain_intensity,
        text_samples, raw_signals, metadata
    }
    """
    if sources is None:
        sources = SUPPORTED_SOURCES

    all_signals:    list = []
    source_counts:  dict = {}
    is_real         = False

    # --- Reddit: try real API first ---
    if "reddit" in sources:
        reddit_signals, reddit_real = _fetch_reddit(keyword, limit=max_per_source)
        if reddit_real:
            is_real = True
            source_counts["reddit"] = len(reddit_signals)
            all_signals.extend(reddit_signals)
        else:
            sim = _simulate_source_fetch("reddit", keyword, max_per_source)
            source_counts["reddit"] = len(sim)
            all_signals.extend(sim)

    # --- Other sources: simulation ---
    for source in sources:
        if source == "reddit":
            continue
        sim = _simulate_source_fetch(source, keyword, max_per_source)
        source_counts[source] = len(sim)
        all_signals.extend(sim)

    # --- Pain intensity ---
    total_pain = 0.0
    for sig in all_signals:
        intensity = _compute_pain_intensity(sig["text"])
        sig["pain_intensity"] = intensity
        total_pain += intensity

    total_occurrences  = sum(source_counts.values())
    avg_pain_intensity = round(total_pain / max(total_occurrences, 1), 4)

    # --- Temporal spread ---
    dates = []
    for sig in all_signals:
        try:
            dates.append(datetime.fromisoformat(sig["date"]))
        except (ValueError, KeyError):
            pass

    if len(dates) >= 2:
        oldest      = min(dates)
        newest      = max(dates)
        spread_days = (newest - oldest).days
    else:
        oldest      = datetime.now(timezone.utc) - timedelta(days=days_back)
        newest      = datetime.now(timezone.utc)
        spread_days = days_back

    # --- Top text samples by pain intensity ---
    sorted_sigs  = sorted(all_signals, key=lambda x: x.get("pain_intensity", 0), reverse=True)
    text_samples = [s["text"] for s in sorted_sigs[:20]]

    now_str = datetime.now(timezone.utc).isoformat()
    return {
        "provider":          PROVIDER_NAME,
        "keyword":           keyword,
        "timestamp":         now_str,
        "timestamp_range":   {"start": oldest.isoformat(), "end": newest.isoformat()},
        "is_real_data":      is_real,
        "sources_queried":   list(source_counts.keys()),
        "source_counts":     source_counts,
        "total_occurrences": total_occurrences,
        "occurrence_count":  total_occurrences,   # alias for Phase 2 compat
        "temporal_spread_days": spread_days,
        "avg_pain_intensity": avg_pain_intensity,
        "text_samples":      text_samples,
        "raw_signals":       all_signals,
        "metadata": {
            "max_per_source":  max_per_source,
            "days_back":       days_back,
            "version":         "2.0",
            "reddit_real_api": is_real,
        },
    }
