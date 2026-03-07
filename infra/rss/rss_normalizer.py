"""
infra/rss/rss_normalizer.py — Normalize raw feedparser entries to a clean dict.

Constitutional guarantees:
  • No Orchestrator dependency
  • No global state mutation
  • No Radar dependency
  • Pure transformation: input entry → output dict
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

# ---------------------------------------------------------------------------
# HTML sanitizer (strips all tags, decodes entities)
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode HTML entities. Returns clean plaintext."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _to_utc_iso(time_struct) -> Optional[str]:
    """
    Convert a feedparser time_struct (9-tuple) to ISO-8601 UTC string.
    Returns None if conversion fails.
    """
    if not time_struct:
        return None
    try:
        dt = datetime(*time_struct[:6], tzinfo=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


def _to_utc_iso_from_string(date_str: str) -> Optional[str]:
    """Parse an RFC-2822 / ISO date string to UTC ISO-8601."""
    if not date_str:
        return None
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public normalizer
# ---------------------------------------------------------------------------

def normalize_entry(entry: object, source_url: str) -> Optional[dict]:
    """
    Convert a feedparser entry object to a standard dict.
    Returns None only if the entry has no usable title or link.

    Output schema:
      title        : str
      link         : str
      published_at : str | None  (ISO-8601 UTC)
      summary      : str
      content      : str
      source       : str         (source feed URL)
    """
    try:
        title = _strip_html(getattr(entry, "title", "") or "")
        link  = (getattr(entry, "link", "") or "").strip()

        if not title and not link:
            return None  # unusable entry

        # published_at — try multiple feedparser attributes
        published_at = (
            _to_utc_iso(getattr(entry, "published_parsed", None))
            or _to_utc_iso(getattr(entry, "updated_parsed", None))
            or _to_utc_iso_from_string(getattr(entry, "published", "") or "")
            or _to_utc_iso_from_string(getattr(entry, "updated", "") or "")
        )

        # summary
        summary_raw = getattr(entry, "summary", "") or ""
        summary = _strip_html(summary_raw)[:500]  # cap to 500 chars

        # content (some feeds put full article here)
        content = ""
        content_list = getattr(entry, "content", None)
        if content_list and isinstance(content_list, list):
            content = _strip_html(content_list[0].get("value", "") or "")[:1000]

        result = {
            "title":        title,
            "link":         link,
            "published_at": published_at,
            "summary":      summary,
            "content":      content,
            "source":       source_url,
        }

        # Remove None/empty fields (keep explicit published_at=None for audit)
        return {k: v for k, v in result.items() if v is not None and v != ""}

    except Exception:
        return None


def normalize_feed(raw_entries: list, source_url: str) -> list[dict]:
    """Normalize an entire list of raw feedparser entries. Drops unparseable items."""
    normalized: list[dict] = []
    for entry in raw_entries:
        item = normalize_entry(entry, source_url)
        if item:
            normalized.append(item)
    return normalized
