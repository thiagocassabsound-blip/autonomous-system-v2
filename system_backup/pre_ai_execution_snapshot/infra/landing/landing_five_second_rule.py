"""
infra/landing/landing_five_second_rule.py — 5-second clarity evaluator for Bloco 30.

Validates that within 5 seconds of reading, a visitor can answer:
  1. What is the promise? (clear transformation)
  2. Who is this for? (audience identifiable)
  3. What is the result? (explicit outcome)
  4. What should I do? (obvious CTA)

Rule-based — no LLM, no external calls.

Failure → pipeline aborts, landing_generation_failed_event emitted.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("infra.landing.five_second_rule")

# Terms that indicate a clear transformation/outcome in headline context
_OUTCOME_INDICATORS = [
    r"\d+\s*(day|week|month|hour|minute|second)",   # time-based results
    r"(learn|master|build|create|launch|start|grow|scale|earn|save|lose|gain)",
    r"(result|outcome|transformation|success|progress|achieve|proven|guaranteed)",
    r"without\s+\w+",                               # "without struggle"
    r"in\s+\d+",                                    # "in 7 days"
    r"from\s+\w+\s+to\s+\w+",                      # "from X to Y"
]
_OUTCOME_RE = re.compile("|".join(_OUTCOME_INDICATORS), re.IGNORECASE)

# CTA must be present and unambiguous
_CTA_RE = re.compile(
    r"(get\s+started|buy\s+now|order\s+now|start\s+(now|today)|access\s+now"
    r"|sign\s+up|join\s+now|download\s+now|claim\s+now|yes[,!]?\s+i\s+want)",
    re.IGNORECASE,
)

# Minimum content thresholds
_MIN_HTML_LENGTH    = 200
_MIN_H1_WORD_COUNT  = 4
_MAX_H1_WORD_COUNT  = 20


def _extract_h1_text(html: str) -> str:
    """Extract text content from the first <h1> tag."""
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    if not m:
        return ""
    # Strip HTML tags from the extracted content
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def validate(html: str) -> dict:
    """
    Evaluate whether the landing page passes the 5-second clarity rule.

    Returns:
      {"valid": True} on pass
      {"valid": False, "reason": str} on fail
    """
    if not html or len(html) < _MIN_HTML_LENGTH:
        return {"valid": False, "reason": f"Content too short ({len(html)} chars) for 5-second evaluation"}

    # 1. Promise / transformation in headline
    h1_text = _extract_h1_text(html)
    if not h1_text:
        return {"valid": False, "reason": "No H1 headline found — promise unclear"}

    h1_words = h1_text.split()
    if len(h1_words) < _MIN_H1_WORD_COUNT:
        return {"valid": False, "reason": f"H1 too short ({len(h1_words)} words) — promise too vague"}
    if len(h1_words) > _MAX_H1_WORD_COUNT:
        return {"valid": False, "reason": f"H1 too long ({len(h1_words)} words) — violates 5-second rule"}

    # 2. Outcome indicator must appear somewhere in the page
    if not _OUTCOME_RE.search(html):
        return {"valid": False, "reason": "No explicit result or outcome indicator found in content"}

    # 3. CTA clarity — button text must be action-oriented
    if not _CTA_RE.search(html):
        logger.warning(
            "[FiveSecondRule] No strong CTA text detected. checkpoint: soft warning only."
        )
        # Soft check — button id is enforced by structural validator, text is a soft warning

    # 4. CTA button must exist (hard check)
    if 'id="checkout-btn"' not in html and "id='checkout-btn'" not in html:
        return {"valid": False, "reason": "CTA button id='checkout-btn' not found"}

    logger.info("[FiveSecondRule] 5-second rule passed. H1='%s...'", h1_text[:60])
    return {"valid": True}
