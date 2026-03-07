"""
infra/rss/rss_client.py — Resilient RSS feed fetcher.

Constitutional guarantees:
  • No Orchestrator dependency
  • No Radar dependency
  • No global state mutation
  • Never raises unhandled exceptions (all errors are caught and returned)
  • Isolated from all system components

Features:
  • Configurable timeout (default 5s)
  • Retry policy (default max 2 retries with 0.5s back-off)
  • User-Agent header
  • Structured result per feed URL
  • Parallel fetching via ThreadPoolExecutor
"""
from __future__ import annotations

import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import feedparser
import requests

from infra.rss.rss_errors import (
    RSSFetchTimeout,
    RSSHTTPError,
    RSSInvalidXML,
    RSSUnknownError,
)
from infra.rss.rss_normalizer import normalize_feed

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_AGENT = (
    "Mozilla/5.0 (compatible; AutonomousSystemRadar/2.0; +https://fastoolhub.com)"
)
_DEFAULT_TIMEOUT_SECONDS = 5
_DEFAULT_MAX_RETRIES      = 2
_DEFAULT_RETRY_DELAY_SEC  = 0.5
_DEFAULT_MAX_WORKERS       = 10


# ---------------------------------------------------------------------------
# Result shape
# ---------------------------------------------------------------------------

def _ok_result(source_url: str, entries: list[dict]) -> dict:
    return {
        "source_url": source_url,
        "status":     "ok",
        "entries":    entries,
        "error_type": None,
    }


def _err_result(source_url: str, error_type: str, detail: str = "") -> dict:
    return {
        "source_url": source_url,
        "status":     "error",
        "entries":    [],
        "error_type": error_type,
        "detail":     detail,
    }


# ---------------------------------------------------------------------------
# Single-feed fetch with retry
# ---------------------------------------------------------------------------

def fetch_feed(
    url: str,
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY_SEC,
) -> dict:
    """
    Fetch and parse a single RSS/Atom feed URL.

    Returns a structured result dict:
      {
        source_url,
        status:     "ok" | "error",
        entries:    [normalized dicts],
        error_type: None | "RSSFetchTimeout" | "RSSHTTPError"
                        | "RSSInvalidXML" | "RSSUnknownError",
        detail:     str  (only on error),
      }

    Never raises. Retries up to max_retries times on transient errors.
    """
    attempt = 0
    last_error: Optional[Exception] = None

    while attempt <= max_retries:
        attempt += 1
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": _USER_AGENT},
                allow_redirects=True,
            )

            if response.status_code >= 400:
                err = RSSHTTPError(
                    f"HTTP {response.status_code}",
                    url=url,
                    status_code=response.status_code,
                )
                # 4xx errors are not retried (client error)
                if response.status_code < 500:
                    return _err_result(url, "RSSHTTPError", str(err))
                last_error = err
                if attempt <= max_retries:
                    time.sleep(retry_delay)
                continue

            # Parse with feedparser (handles RSS 0.9x, 1.0, 2.0, Atom)
            raw_content = response.content
            feed = feedparser.parse(io.BytesIO(raw_content))

            # feedparser signals parse errors via bozo flag + bozo_exception
            if feed.get("bozo") and feed.bozo_exception is not None:
                exc = feed.bozo_exception
                if "not well-formed" in str(exc) or isinstance(exc, Exception):
                    last_error = RSSInvalidXML(str(exc), url=url)
                    if attempt <= max_retries:
                        time.sleep(retry_delay)
                    continue

            entries = normalize_feed(feed.entries, url)
            return _ok_result(url, entries)

        except requests.exceptions.Timeout:
            last_error = RSSFetchTimeout(f"Timeout after {timeout}s", url=url)
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except requests.exceptions.ConnectionError as exc:
            last_error = RSSUnknownError(str(exc), url=url)
            if attempt <= max_retries:
                time.sleep(retry_delay)

        except Exception as exc:
            last_error = RSSUnknownError(str(exc), url=url)
            if attempt <= max_retries:
                time.sleep(retry_delay)

    # All retries exhausted — return error result
    if last_error is None:
        last_error = RSSUnknownError("Unknown error after retries", url=url)

    error_type = type(last_error).__name__
    return _err_result(url, error_type, str(last_error))


# ---------------------------------------------------------------------------
# Batch fetch (concurrent)
# ---------------------------------------------------------------------------

def fetch_feeds(
    urls: list[str],
    timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    retry_delay: float = _DEFAULT_RETRY_DELAY_SEC,
    max_workers: int = _DEFAULT_MAX_WORKERS,
) -> list[dict]:
    """
    Fetch multiple RSS feeds concurrently.

    Args:
        urls:        List of feed URLs.
        timeout:     Per-request timeout in seconds.
        max_retries: Maximum retry attempts per URL.
        retry_delay: Seconds to wait between retries.
        max_workers: Maximum number of parallel HTTP threads.

    Returns:
        List of result dicts (one per URL), in the same order as input.
        Never raises.
    """
    if not urls:
        return []

    # Cap workers to number of URLs to avoid unnecessary threads
    workers = min(max_workers, len(urls))
    results: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_to_url = {
            executor.submit(
                fetch_feed, url, timeout, max_retries, retry_delay
            ): url
            for url in urls
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                results[url] = future.result()
            except Exception as exc:
                results[url] = _err_result(url, "RSSUnknownError", str(exc))

    # Return in original URL order
    return [results[url] for url in urls]
