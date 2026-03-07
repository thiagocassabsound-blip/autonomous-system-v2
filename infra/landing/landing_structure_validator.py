"""
infra/landing/landing_structure_validator.py — Content structure validator for Bloco 30.

Validates that the generated HTML contains required structural elements:
  - Headline (h1)
  - Subheadline (h2)
  - CTA button with id="checkout-btn"
  - At least 3 bullet points
  - No placeholder text

Failure → pipeline aborts, landing_generation_failed_event emitted.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("infra.landing.structure_validator")

# Placeholders that indicate incomplete content
_PLACEHOLDER_PATTERNS = [
    r"\[INSERT",
    r"\[YOUR ",
    r"\[PRODUCT",
    r"\[NAME\]",
    r"\[PRICE\]",
    r"\[HEADLINE\]",
    r"\[BENEFIT",
    r"Lorem ipsum",
]

_PLACEHOLDER_RE = re.compile("|".join(_PLACEHOLDER_PATTERNS), re.IGNORECASE)


def validate(html: str, *, icp: str = "") -> dict:
    """
    Validate landing page structural completeness.

    Returns:
      {"valid": True} on success
      {"valid": False, "reason": str} on failure
    """
    if not html or len(html) < 200:
        return {"valid": False, "reason": "HTML too short (< 200 chars)"}

    lower = html.lower()

    # Must contain <h1>
    if "<h1" not in lower:
        return {"valid": False, "reason": "Missing <h1> headline"}

    # Must contain <h2>
    if "<h2" not in lower:
        return {"valid": False, "reason": "Missing <h2> subheadline"}

    # Must contain CTA button with id="checkout-btn"
    if 'id="checkout-btn"' not in html and "id='checkout-btn'" not in html:
        return {"valid": False, "reason": "Missing CTA button with id='checkout-btn'"}

    # Must contain at least 3 <li> elements (bullet points)
    li_count = len(re.findall(r"<li[\s>]", html, re.IGNORECASE))
    if li_count < 3:
        return {"valid": False, "reason": f"Insufficient bullet points: {li_count} (minimum 3)"}

    # Must not contain placeholder text
    match = _PLACEHOLDER_RE.search(html)
    if match:
        return {"valid": False, "reason": f"Placeholder text detected: '{match.group()}'"}

    # Must contain <html> tag
    if "<html" not in lower:
        return {"valid": False, "reason": "Not a valid HTML document (missing <html>)"}

    logger.info("[LandingStructureValidator] Structure valid. li_count=%d", li_count)
    return {"valid": True}
